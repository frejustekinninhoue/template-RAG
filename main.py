import asyncio
import json
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx
import motor.motor_asyncio
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.graph.graph import build_graph
from app.middleware.auth import auth_middleware
from app.middleware.input_guard import input_guard_middleware
from app.middleware.rate_limit import limiter
from app.observability.logging import configure_logging, get_logger
from app.services.llm_factory import create_chat_model
from app.services.source_ingestion import (
    build_tree_from_text,
    fetch_url_text,
    parse_docx_text,
    parse_xlsx_text,
    text_from_google_doc,
    text_from_google_sheet,
)

configure_logging()

# ── App state ─────────────────────────────────────────────────────────────────

_graph = None
_pg_pool = None
_mongo_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph, _pg_pool
    _pg_pool = await asyncpg.create_pool(settings.POSTGRES_DSN, min_size=2, max_size=10)
    _graph = await build_graph(_pg_pool)
    yield
    await _pg_pool.close()


app = FastAPI(title="Apple Support Bot", lifespan=lifespan)

# ── Middleware (order matters: added last = runs first) ───────────────────────

app.middleware("http")(input_guard_middleware)
app.middleware("http")(auth_middleware)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


# ── Request / response models ─────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None


class QueryResponse(BaseModel):
    response: str
    session_id: str
    request_id: str
    faithfulness_score: float
    completeness_score: float
    validation_passed: bool
    model_used: str


class RAGCollectionRead(BaseModel):
    name: str
    document_count: int


class RAGCollectionList(BaseModel):
    collections: list[RAGCollectionRead]


class RAGTrackedDocument(BaseModel):
    doc_id: str
    collection_name: str
    domain: str
    filename: str
    updated_at: int


class RAGTrackedDocumentList(BaseModel):
    documents: list[RAGTrackedDocument]


class RAGSearchRequest(BaseModel):
    query: str
    collection_names: list[str] = Field(default_factory=list)
    top_k: int = 6


class RAGSearchResult(BaseModel):
    content: str
    score: float
    metadata: dict


class RAGSearchResponse(BaseModel):
    results: list[RAGSearchResult]


# ── Data helpers ───────────────────────────────────────────────────────────────

def get_mongo_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGODB_URI)
    return _mongo_client.support_bot


async def _ensure_collection_exists(name: str):
    db = get_mongo_db()
    await db.rag_collections.update_one(
        {"name": name},
        {"$setOnInsert": {"name": name, "created_at": int(time.time())}},
        upsert=True,
    )


async def _list_collection_counts() -> dict[str, int]:
    db = get_mongo_db()
    pipeline = [
        {"$group": {"_id": "$metadata.collection", "document_count": {"$sum": 1}}},
    ]
    rows = await db.document_trees.aggregate(pipeline).to_list(length=5000)
    return {(row.get("_id") or "default"): int(row.get("document_count", 0)) for row in rows}


async def _list_declared_collections() -> list[str]:
    db = get_mongo_db()
    rows = await db.rag_collections.find({}, {"_id": 0, "name": 1}).to_list(length=5000)
    return [row.get("name", "") for row in rows if row.get("name")]


def _to_tracked_document(doc: dict) -> RAGTrackedDocument:
    return RAGTrackedDocument(
        doc_id=doc.get("doc_id", ""),
        collection_name=doc.get("metadata", {}).get("collection", "default"),
        domain=doc.get("metadata", {}).get("domain", "general"),
        filename=doc.get("metadata", {}).get("filename", doc.get("doc_id", "")),
        updated_at=doc.get("updated_at", 0),
    )


def _sanitize_slug(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in lowered)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "document"


def _tree_search_model():
    return create_chat_model(
        settings.TREE_SEARCH_PROVIDER,
        settings.TREE_SEARCH_MODEL,
        temperature=0,
    )


def _strip_text(tree: list) -> list:
    result = []
    for node in tree:
        n = {k: v for k, v in node.items() if k not in ("text",)}
        if "nodes" in node:
            n["nodes"] = _strip_text(node["nodes"])
        result.append(n)
    return result


def _build_node_map(tree: list, node_map: dict | None = None) -> dict:
    if node_map is None:
        node_map = {}
    for node in tree:
        node_map[node["node_id"]] = node
        if "nodes" in node:
            _build_node_map(node["nodes"], node_map)
    return node_map


async def _search_tree(tree: list, query: str) -> list[dict]:
    prompt = (
        "You are given a question and a tree structure of an enterprise knowledge document. "
        "Each node has node_id, title and summary. Return JSON only: "
        '{"node_list": ["node_id_1", "node_id_2"]}\n\n'
        f"Question: {query}\n\nDocument tree:\n{json.dumps(_strip_text(tree), indent=2)}"
    )

    result = await _tree_search_model().ainvoke(prompt)
    payload = json.loads(result.content)
    node_ids = payload.get("node_list", [])
    node_map = _build_node_map(tree)
    return [node_map[nid] for nid in node_ids if nid in node_map]


async def _index_pdf_to_pageindex(pdf_path: str) -> list:
    # Local import to avoid loading dependency path when not indexing.
    from pageindex import PageIndexClient

    client = PageIndexClient(api_key=settings.PAGEINDEX_API_KEY)
    result = client.submit_document(pdf_path)
    pi_doc_id = result["doc_id"]

    max_attempts = 30
    for _ in range(max_attempts):
        if client.is_retrieval_ready(pi_doc_id):
            return client.get_tree(pi_doc_id, node_summary=True)["result"]
        await asyncio.sleep(10)

    raise TimeoutError("PageIndex processing timeout")


async def _store_tree(doc_id: str, tree: list, metadata: dict):
    db = get_mongo_db()
    await db.document_trees.replace_one(
        {"doc_id": doc_id},
        {
            "doc_id": doc_id,
            "tree": tree,
            "metadata": metadata,
            "updated_at": int(time.time()),
        },
        upsert=True,
    )


# ── Cache helper ──────────────────────────────────────────────────────────────

async def check_cache(query: str) -> str | None:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.GPTCACHE_URL}/get",
                json={"prompt": query},
                timeout=2.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                answer = data.get("answer")
                if answer:
                    return answer
    except Exception:
        pass
    return None


# ── Graph execution helper ────────────────────────────────────────────────────

async def _run_query_graph(body: QueryRequest, request: Request) -> QueryResponse:
    request_id = str(uuid.uuid4())
    session_id = body.session_id or str(uuid.uuid4())
    log = get_logger(request_id, session_id=session_id, user_id=request.state.user_id)

    log.info("request_received", query_length=len(body.query))

    cached = await check_cache(body.query)
    if cached:
        log.info("cache_hit")
        return QueryResponse(
            response=cached,
            session_id=session_id,
            request_id=request_id,
            faithfulness_score=1.0,
            completeness_score=1.0,
            validation_passed=True,
            model_used="cache",
        )

    log.info("cache_miss")

    initial_state = {
        "raw_query": body.query,
        "session_id": session_id,
        "request_id": request_id,
        "scrubbed_query": "",
        "pii_found": [],
        "is_attack": False,
        "attack_confidence": 0.0,
        "intent": "",
        "sub_queries": [],
        "complexity": "low",
        "needs_decomp": False,
        "prompt_version": "",
        "current_subquery": "",
        "session_history": [],
        "retrieved_context": [],
        "sub_responses": [],
        "raw_response": "",
        "model_used": "",
        "faithfulness_score": 0.0,
        "completeness_score": 0.0,
        "validation_passed": False,
        "final_response": "",
    }

    config = {"configurable": {"thread_id": session_id}}

    try:
        result = await _graph.ainvoke(initial_state, config=config)
    except Exception as exc:
        log.error("graph_invocation_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    if result.get("is_attack"):
        log.warning("request_rejected_attack", confidence=result.get("attack_confidence"))
        raise HTTPException(status_code=403, detail="Request rejected")

    log.info("request_success")

    return QueryResponse(
        response=result["final_response"],
        session_id=session_id,
        request_id=request_id,
        faithfulness_score=result.get("faithfulness_score", 0.0),
        completeness_score=result.get("completeness_score", 0.0),
        validation_passed=result.get("validation_passed", False),
        model_used=result.get("model_used", "unknown"),
    )


# ── Core query endpoint ───────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
@limiter.limit("30/minute")
async def query_endpoint(body: QueryRequest, request: Request):
    return await _run_query_graph(body, request)


# ── Vstorm-compatible endpoints ───────────────────────────────────────────────

@app.get("/api/v1/health")
async def health_v1():
    return {"status": "ok", "graph_ready": _graph is not None}


@app.get("/api/v1/agent/models")
async def list_models_v1():
    return {
        "low": {
            "provider": settings.LOW_COMPLEXITY_PROVIDER,
            "model": settings.LOW_COMPLEXITY_MODEL,
        },
        "high": {
            "provider": settings.HIGH_COMPLEXITY_PROVIDER,
            "model": settings.HIGH_COMPLEXITY_MODEL,
        },
    }


@app.get("/api/v1/rag/supported-formats")
async def rag_supported_formats_v1():
    return {
        "formats": ["pdf", "docx", "xlsx", "google_docs", "google_sheets", "url"],
        "notes": {
            "pdf": "PageIndex native parsing",
            "docx": "text extraction + semantic chunk tree",
            "xlsx": "sheet extraction + semantic chunk tree",
            "google_docs": "Drive export via service account",
            "google_sheets": "Sheets API via service account",
            "url": "HTML extraction via HTTP + BeautifulSoup",
        },
    }


@app.get("/api/v1/rag/collections", response_model=RAGCollectionList)
async def rag_list_collections_v1():
    counts = await _list_collection_counts()
    declared = await _list_declared_collections()

    names = set(counts.keys()) | set(declared)
    if not names:
        names = {"default"}

    collections = [
        RAGCollectionRead(name=name, document_count=counts.get(name, 0))
        for name in sorted(names)
    ]
    return RAGCollectionList(collections=collections)


@app.get("/api/v1/rag/collections/{name}/info")
async def rag_collection_info_v1(name: str):
    db = get_mongo_db()
    safe_name = _sanitize_slug(name)
    count = await db.document_trees.count_documents({"metadata.collection": safe_name})
    exists = count > 0 or await db.rag_collections.count_documents({"name": safe_name}) > 0
    if not exists:
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"name": safe_name, "document_count": count}


@app.get("/api/v1/rag/documents", response_model=RAGTrackedDocumentList)
async def rag_documents_v1(collection_name: str | None = Query(default=None)):
    db = get_mongo_db()
    query = {"metadata.collection": collection_name} if collection_name else {}
    docs = await db.document_trees.find(query).sort("updated_at", -1).to_list(length=2000)

    items = [
        RAGTrackedDocument(
            doc_id=d.get("doc_id", ""),
            collection_name=d.get("metadata", {}).get("collection", "default"),
            domain=d.get("metadata", {}).get("domain", "general"),
            filename=d.get("metadata", {}).get("filename", d.get("doc_id", "")),
            updated_at=d.get("updated_at", 0),
        )
        for d in docs
    ]
    return RAGTrackedDocumentList(documents=items)


@app.post("/api/v1/rag/search", response_model=RAGSearchResponse)
async def rag_search_v1(body: RAGSearchRequest):
    db = get_mongo_db()
    query = {}
    if body.collection_names:
        query = {"metadata.collection": {"$in": body.collection_names}}

    docs = await db.document_trees.find(query).to_list(length=max(body.top_k * 8, 20))
    if not docs:
        return RAGSearchResponse(results=[])

    tasks = [_search_tree(doc.get("tree", []), body.query) for doc in docs if doc.get("tree")]
    search_results = await asyncio.gather(*tasks, return_exceptions=True)

    flattened: list[RAGSearchResult] = []
    for doc, result in zip(docs, search_results):
        if isinstance(result, Exception):
            continue

        doc_meta = doc.get("metadata", {})
        for rank, node in enumerate(result):
            content = node.get("text", "").strip()
            if not content:
                continue
            flattened.append(
                RAGSearchResult(
                    content=content,
                    score=max(0.0, 1.0 - rank * 0.1),
                    metadata={
                        "doc_id": doc.get("doc_id"),
                        "collection": doc_meta.get("collection", "default"),
                        "domain": doc_meta.get("domain", "general"),
                        "node_id": node.get("node_id"),
                        "title": node.get("title", ""),
                    },
                )
            )

    return RAGSearchResponse(results=flattened[: max(body.top_k, 1)])


@app.post("/api/v1/rag/collections/{name}/ingest")
async def rag_ingest_collection_v1(
    name: str,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    google_doc_id: str | None = Form(default=None),
    google_sheet_id: str | None = Form(default=None),
    doc_id: str | None = Form(default=None),
    replace: bool = Query(default=False),
    domain: str = Form(default="general"),
    source: str = Form(default="api_upload"),
    tags: str = Form(default=""),
):
    safe_name = _sanitize_slug(name)
    await _ensure_collection_exists(safe_name)

    provided_sources = [
        bool(file),
        bool(url and url.strip()),
        bool(google_doc_id and google_doc_id.strip()),
        bool(google_sheet_id and google_sheet_id.strip()),
    ]
    if sum(provided_sources) != 1:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one source: file OR url OR google_doc_id OR google_sheet_id",
        )

    if replace:
        db = get_mongo_db()
        await db.document_trees.delete_many({"metadata.collection": safe_name})

    tree: list[dict] = []
    source_label = ""
    source_type = ""

    if file:
        filename = file.filename or "uploaded"
        suffix = Path(filename).suffix.lower()
        source_label = filename
        source_type = suffix.removeprefix(".") or "file"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".tmp") as tmp:
            content = await file.read()
            tmp.write(content)
            temp_path = tmp.name

        try:
            if suffix == ".pdf":
                tree = await _index_pdf_to_pageindex(temp_path)
            elif suffix == ".docx":
                text = await asyncio.to_thread(parse_docx_text, temp_path)
                tree = build_tree_from_text(filename, text, "docx")
            elif suffix == ".xlsx":
                text = await asyncio.to_thread(parse_xlsx_text, temp_path)
                tree = build_tree_from_text(filename, text, "xlsx")
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported file type. Allowed: .pdf, .docx, .xlsx",
                )
        finally:
            Path(temp_path).unlink(missing_ok=True)

    elif url and url.strip():
        source_label = url.strip()
        source_type = "url"
        text = await fetch_url_text(source_label)
        tree = build_tree_from_text(source_label, text, "url")

    elif google_doc_id and google_doc_id.strip():
        source_label = google_doc_id.strip()
        source_type = "google_docs"
        text = await text_from_google_doc(source_label, settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        tree = build_tree_from_text(f"google-doc-{source_label}", text, "gdoc")

    elif google_sheet_id and google_sheet_id.strip():
        source_label = google_sheet_id.strip()
        source_type = "google_sheets"
        text = await text_from_google_sheet(source_label, settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        tree = build_tree_from_text(f"google-sheet-{source_label}", text, "gsheet")

    if not tree:
        raise HTTPException(status_code=422, detail="No extractable content found for source")

    auto_doc_id_source = source_type if "://" in source_label else Path(source_label).stem
    final_doc_id = doc_id or f"{safe_name}-{_sanitize_slug(auto_doc_id_source or source_type)}"

    metadata = {
        "collection": safe_name,
        "domain": domain,
        "source": source,
        "source_type": source_type,
        "source_ref": source_label,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "filename": source_label,
    }
    await _store_tree(final_doc_id, tree, metadata)

    return {
        "status": "indexed",
        "doc_id": final_doc_id,
        "collection": safe_name,
        "source_type": source_type,
        "source_ref": source_label,
    }


@app.post("/api/v1/knowledge-bases/upload")
async def kb_upload_v1(
    file: UploadFile = File(...),
    collection: str = Form(default="default"),
    domain: str = Form(default="general"),
):
    return await rag_ingest_collection_v1(
        name=collection,
        file=file,
        replace=False,
        domain=domain,
        source="kb_upload",
        tags="",
    )


@app.post("/api/v1/files/upload")
async def files_upload_v1(file: UploadFile = File(...)):
    uploads_dir = Path(tempfile.gettempdir()) / "support_bot_uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    file_id = str(uuid.uuid4())
    safe_name = f"{file_id}_{Path(file.filename).name}"
    target = uploads_dir / safe_name

    content = await file.read()
    target.write_bytes(content)

    return {
        "id": file_id,
        "filename": file.filename,
        "mime_type": file.content_type,
        "size": len(content),
        "storage_path": str(target),
    }


@app.post("/api/v1/query/stream")
@limiter.limit("30/minute")
async def query_stream_v1(body: QueryRequest, request: Request):
    result = await _run_query_graph(body, request)

    async def event_stream():
        for token in result.response.split():
            payload = {"type": "text_delta", "content": token + " "}
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.01)

        done = {
            "type": "done",
            "session_id": result.session_id,
            "request_id": result.request_id,
            "model_used": result.model_used,
        }
        yield f"data: {json.dumps(done)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "graph_ready": _graph is not None}


# ── Sprint 1 Vstorm RAG compatibility endpoints ──────────────────────────────

@app.post("/api/v1/rag/collections", status_code=201)
async def rag_create_collection_v1(request: Request):
    body = await request.json()
    name = _sanitize_slug(str(body.get("name", "")).strip())
    if not name:
        raise HTTPException(status_code=400, detail="Collection name is required")

    await _ensure_collection_exists(name)
    return {"name": name, "document_count": 0}


@app.post("/api/v1/rag/collections/{name}", status_code=201)
async def rag_create_collection_by_name_v1(name: str):
    safe_name = _sanitize_slug(name)
    await _ensure_collection_exists(safe_name)
    return {"name": safe_name, "document_count": 0}


@app.delete("/api/v1/rag/collections/{name}", status_code=204)
async def rag_delete_collection_v1(name: str):
    db = get_mongo_db()
    safe_name = _sanitize_slug(name)
    await db.document_trees.delete_many({"metadata.collection": safe_name})
    await db.rag_collections.delete_one({"name": safe_name})
    return None


@app.get("/api/v1/rag/collections/{name}/documents", response_model=RAGTrackedDocumentList)
async def rag_collection_documents_v1(name: str):
    db = get_mongo_db()
    safe_name = _sanitize_slug(name)
    docs = await db.document_trees.find({"metadata.collection": safe_name}).sort("updated_at", -1).to_list(length=5000)
    return RAGTrackedDocumentList(documents=[_to_tracked_document(d) for d in docs])


@app.delete("/api/v1/rag/collections/{name}/documents/{documentId}", status_code=204)
async def rag_delete_collection_document_v1(name: str, documentId: str):
    db = get_mongo_db()
    safe_name = _sanitize_slug(name)
    result = await db.document_trees.delete_one({"metadata.collection": safe_name, "doc_id": documentId})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return None


@app.get("/api/v1/rag/status/stream")
async def rag_status_stream_v1():
    async def event_stream():
        while True:
            payload = {"status": "ok", "ts": int(time.time())}
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
