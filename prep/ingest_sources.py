"""
Offline multi-source ingestion for RAG collections.

Supports:
- PDF
- DOCX
- XLSX
- URL
- Google Docs ID
- Google Sheets ID

Examples:

  python -m prep.ingest_sources --file ./docs/report.pdf --collection kb-a --domain finance
  python -m prep.ingest_sources --file ./docs/spec.docx --collection kb-a
  python -m prep.ingest_sources --url https://example.com/article --collection kb-web
  python -m prep.ingest_sources --google-doc-id <doc_id> --collection kb-gdocs
  python -m prep.ingest_sources --google-sheet-id <sheet_id> --collection kb-gsheets
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
from pathlib import Path

import motor.motor_asyncio
from pageindex import PageIndexClient

from app.config import settings
from app.services.source_ingestion import (
    build_tree_from_text,
    fetch_url_text,
    parse_docx_text,
    parse_xlsx_text,
    text_from_google_doc,
    text_from_google_sheet,
)


def _sanitize_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return slug or "source"


async def _store_tree(doc_id: str, tree: list, metadata: dict):
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGODB_URI)
    try:
        db = client.support_bot
        await db.rag_collections.update_one(
            {"name": metadata["collection"]},
            {"$setOnInsert": {"name": metadata["collection"], "created_at": int(time.time())}},
            upsert=True,
        )
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
    finally:
        client.close()


def _index_pdf_sync(path: str) -> list:
    client = PageIndexClient(api_key=os.environ["PAGEINDEX_API_KEY"])
    result = client.submit_document(path)
    pi_doc_id = result["doc_id"]

    for _ in range(30):
        if client.is_retrieval_ready(pi_doc_id):
            return client.get_tree(pi_doc_id, node_summary=True)["result"]
        time.sleep(10)

    raise TimeoutError(f"PageIndex timeout for {path}")


async def _tree_from_source(args) -> tuple[list, str, str]:
    if args.file:
        source_ref = str(Path(args.file).resolve())
        suffix = Path(args.file).suffix.lower()
        if suffix == ".pdf":
            tree = await asyncio.to_thread(_index_pdf_sync, args.file)
            return tree, "pdf", source_ref
        if suffix == ".docx":
            text = await asyncio.to_thread(parse_docx_text, args.file)
            return build_tree_from_text(Path(args.file).name, text, "docx"), "docx", source_ref
        if suffix == ".xlsx":
            text = await asyncio.to_thread(parse_xlsx_text, args.file)
            return build_tree_from_text(Path(args.file).name, text, "xlsx"), "xlsx", source_ref
        raise ValueError("Unsupported file format. Allowed: .pdf, .docx, .xlsx")

    if args.url:
        text = await fetch_url_text(args.url)
        return build_tree_from_text(args.url, text, "url"), "url", args.url

    if args.google_doc_id:
        text = await text_from_google_doc(args.google_doc_id, settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        return build_tree_from_text(f"google-doc-{args.google_doc_id}", text, "gdoc"), "google_docs", args.google_doc_id

    text = await text_from_google_sheet(args.google_sheet_id, settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    return build_tree_from_text(f"google-sheet-{args.google_sheet_id}", text, "gsheet"), "google_sheets", args.google_sheet_id


async def main(args):
    supplied = [
        bool(args.file),
        bool(args.url),
        bool(args.google_doc_id),
        bool(args.google_sheet_id),
    ]
    if sum(supplied) != 1:
        raise SystemExit("Provide exactly one source: --file OR --url OR --google-doc-id OR --google-sheet-id")

    collection = _sanitize_slug(args.collection)
    tree, source_type, source_ref = await _tree_from_source(args)
    if not tree:
        raise SystemExit("No extractable content found")

    auto_name = Path(source_ref).stem if "://" not in source_ref else source_type
    doc_id = args.doc_id or f"{collection}-{_sanitize_slug(auto_name)}"

    metadata = {
        "collection": collection,
        "domain": args.domain,
        "source": args.source,
        "source_type": source_type,
        "source_ref": source_ref,
        "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
        "filename": Path(source_ref).name if "://" not in source_ref else source_ref,
    }

    await _store_tree(doc_id, tree, metadata)
    print(f"Indexed source -> doc_id={doc_id} collection={collection} source_type={source_type}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Local file path (.pdf, .docx, .xlsx)")
    parser.add_argument("--url", help="Web URL source")
    parser.add_argument("--google-doc-id", help="Google Docs file ID")
    parser.add_argument("--google-sheet-id", help="Google Sheets file ID")

    parser.add_argument("--doc-id", help="Optional explicit doc_id")
    parser.add_argument("--collection", default="default", help="Target collection")
    parser.add_argument("--domain", default="general", help="Domain metadata")
    parser.add_argument("--source", default="offline", help="Source channel metadata")
    parser.add_argument("--tags", default="", help="CSV tags")

    asyncio.run(main(parser.parse_args()))
