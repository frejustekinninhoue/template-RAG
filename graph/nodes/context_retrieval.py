import asyncio
import json

import motor.motor_asyncio
import pybreaker

from app.config import settings
from app.graph.state import SupportBotState
from app.observability.logging import get_logger
from app.resilience.breakers import pageindex_breaker
from app.services.llm_factory import create_chat_model

_mongo_client = None


def get_mongo():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGODB_URI)
    return _mongo_client.support_bot


def _parse_csv(raw: str) -> list[str]:
    value = raw.strip()
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_target_doc_ids() -> list[str]:
    return _parse_csv(settings.RETRIEVAL_DOC_IDS)


def _get_target_domains() -> list[str]:
    return _parse_csv(settings.RETRIEVAL_DOMAINS)


def _tree_search_model():
    return create_chat_model(
        settings.TREE_SEARCH_PROVIDER,
        settings.TREE_SEARCH_MODEL,
        temperature=0,
    )


_TREE_SEARCH_PROMPT = """
You are given a question and a tree structure of an enterprise knowledge document.
Each node has a node_id, title, and summary.
Find all nodes likely to contain the answer.

Question: {query}

Document tree:
{tree_json}

Reply ONLY with JSON: {{"node_list": ["node_id_1", "node_id_2"]}}
"""


def _build_node_map(tree: list, node_map: dict | None = None) -> dict:
    if node_map is None:
        node_map = {}
    for node in tree:
        node_map[node["node_id"]] = node
        if "nodes" in node:
            _build_node_map(node["nodes"], node_map)
    return node_map


def _strip_text(tree: list) -> list:
    """Remove text content from tree for the search prompt (reduce tokens)."""
    result = []
    for node in tree:
        n = {k: v for k, v in node.items() if k not in ("text",)}
        if "nodes" in node:
            n["nodes"] = _strip_text(node["nodes"])
        result.append(n)
    return result


async def _search_tree(tree: list, query: str) -> list[dict]:
    stripped = _strip_text(tree)
    prompt = _TREE_SEARCH_PROMPT.format(
        query=query,
        tree_json=json.dumps(stripped, indent=2),
    )
    result = await _tree_search_model().ainvoke(prompt)
    node_ids = json.loads(result.content)["node_list"]
    node_map = _build_node_map(tree)
    return [node_map[nid] for nid in node_ids if nid in node_map]


async def _load_documents(db):
    doc_ids = _get_target_doc_ids()
    domains = _get_target_domains()

    query: dict = {}
    and_conditions: list[dict] = []

    if doc_ids:
        and_conditions.append({"doc_id": {"$in": doc_ids}})
    if domains:
        and_conditions.append({"metadata.domain": {"$in": domains}})

    if len(and_conditions) == 1:
        query = and_conditions[0]
    elif and_conditions:
        query = {"$and": and_conditions}

    limit = max(settings.RETRIEVAL_MAX_DOCS, 1)
    return await db.document_trees.find(query).to_list(length=limit)


async def context_retrieval_node(state: SupportBotState) -> dict:
    log = get_logger(state["request_id"], node="context_retrieval")

    try:
        with pageindex_breaker:
            db = get_mongo()
            docs = await _load_documents(db)
            if not docs:
                log.warning("no_document_tree_found")
                return {"retrieved_context": []}

            search_tasks = [
                _search_tree(doc.get("tree", []), state["scrubbed_query"])
                for doc in docs
                if doc.get("tree")
            ]
            search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

            context = []
            for result in search_results:
                if isinstance(result, Exception):
                    log.warning("tree_search_failed", error=str(result))
                    continue
                context.extend([node.get("text", "") for node in result if node.get("text")])

            log.info(
                "retrieval_complete",
                num_docs=len(docs),
                num_context_chunks=len(context),
                retrieval_domains=_get_target_domains(),
            )
            return {"retrieved_context": context}

    except pybreaker.CircuitBreakerError:
        log.warning("pageindex_circuit_open")
        return {"retrieved_context": []}
    except Exception as exc:
        log.warning("retrieval_failed", error=str(exc))
        return {"retrieved_context": []}
