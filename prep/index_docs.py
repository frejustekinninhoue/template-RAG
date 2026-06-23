"""
Offline preparation script.

Use this script to index one PDF or a whole folder into PageIndex,
then store the resulting trees in MongoDB for runtime retrieval.

Examples:

Single file:
  python -m prep.index_docs --pdf ./docs/hr_policy.pdf --doc-id hr-policy

Batch folder:
  python -m prep.index_docs --pdf-dir ./docs --recursive --workers 4 --domain hr --collection kb-hr

Environment:
  - PAGEINDEX_API_KEY (required)
  - MONGODB_URI (optional, default: mongodb://localhost:27017)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import motor.motor_asyncio
import pageindex.utils as utils
from pageindex import PageIndexClient


PAGEINDEX_API_KEY = os.environ["PAGEINDEX_API_KEY"]
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")


def _sanitize_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return slug or "document"


def _build_doc_id(path: Path, prefix: str = "") -> str:
    core = _sanitize_slug(path.stem)
    if prefix:
        return f"{_sanitize_slug(prefix)}-{core}"
    return core


def _collect_pdfs(pdf: str | None, pdf_dir: str | None, recursive: bool) -> list[Path]:
    files: list[Path] = []
    if pdf:
        files.append(Path(pdf))

    if pdf_dir:
        root = Path(pdf_dir)
        pattern = "**/*.pdf" if recursive else "*.pdf"
        files.extend(sorted(root.glob(pattern)))

    dedup = []
    seen = set()
    for p in files:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            dedup.append(rp)
    return dedup


@dataclass
class IndexJob:
    path: Path
    doc_id: str


async def store_tree(doc_id: str, tree: list, metadata: dict):
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
    try:
        db = client.support_bot
        payload = {
            "doc_id": doc_id,
            "tree": tree,
            "metadata": metadata,
            "updated_at": int(time.time()),
        }
        await db.document_trees.replace_one({"doc_id": doc_id}, payload, upsert=True)
    finally:
        client.close()


def submit_and_wait(pdf_path: str, max_attempts: int, poll_seconds: int) -> list:
    pi_client = PageIndexClient(api_key=PAGEINDEX_API_KEY)

    result = pi_client.submit_document(pdf_path)
    pi_doc_id = result["doc_id"]
    print(f"Submitted to PageIndex: {pi_doc_id} ({pdf_path})")

    for attempt in range(max_attempts):
        if pi_client.is_retrieval_ready(pi_doc_id):
            tree = pi_client.get_tree(pi_doc_id, node_summary=True)["result"]
            print(f"Tree ready: {len(tree)} top-level nodes ({pdf_path})")
            return tree
        print(f"  Waiting PageIndex ({attempt + 1}/{max_attempts}) for {pdf_path}")
        time.sleep(poll_seconds)

    raise TimeoutError(
        f"PageIndex did not finish processing {pdf_path} after {max_attempts * poll_seconds}s"
    )


async def _index_one(job: IndexJob, args, semaphore: asyncio.Semaphore):
    metadata = {
        "collection": args.collection,
        "domain": args.domain,
        "source": args.source,
        "tags": [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else [],
        "filename": job.path.name,
    }

    async with semaphore:
        print(f"Indexing '{job.path}' as doc_id='{job.doc_id}'")
        tree = await asyncio.to_thread(
            submit_and_wait,
            str(job.path),
            args.max_attempts,
            args.poll_seconds,
        )
        if args.print_tree:
            print(f"\nTree structure for {job.doc_id}:")
            utils.print_tree(tree)

        await store_tree(job.doc_id, tree, metadata)
        print(f"Stored tree for '{job.doc_id}' in MongoDB.")


async def main(args):
    files = _collect_pdfs(args.pdf, args.pdf_dir, args.recursive)
    if not files:
        raise FileNotFoundError("No PDF file found. Provide --pdf or --pdf-dir.")

    jobs: list[IndexJob] = []
    for path in files:
        if not path.exists():
            print(f"Skipping missing file: {path}")
            continue
        if path.suffix.lower() != ".pdf":
            print(f"Skipping non-PDF file: {path}")
            continue

        if args.pdf and args.doc_id and path == Path(args.pdf).resolve():
            doc_id = args.doc_id
        else:
            doc_id = _build_doc_id(path, prefix=args.doc_prefix)

        jobs.append(IndexJob(path=path, doc_id=doc_id))

    if not jobs:
        raise RuntimeError("No valid PDF jobs to process.")

    semaphore = asyncio.Semaphore(max(args.workers, 1))
    failures: list[tuple[str, str]] = []

    tasks = [
        _index_one(job, args, semaphore)
        for job in jobs
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for job, result in zip(jobs, results):
        if isinstance(result, Exception):
            failures.append((job.doc_id, str(result)))

    print("\nBatch completed.")
    print(f"  Total files: {len(jobs)}")
    print(f"  Success: {len(jobs) - len(failures)}")
    print(f"  Failed: {len(failures)}")

    if failures:
        print("\nFailed documents:")
        for doc_id, error in failures:
            print(f"  - {doc_id}: {error}")
        raise RuntimeError("Some documents failed to index.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", help="Path to a single PDF to index")
    parser.add_argument("--doc-id", help="Identifier for --pdf mode")
    parser.add_argument("--pdf-dir", help="Folder containing PDFs to index")
    parser.add_argument("--recursive", action="store_true", help="Recursively scan --pdf-dir")
    parser.add_argument("--workers", type=int, default=2, help="Parallel indexing workers")
    parser.add_argument("--max-attempts", type=int, default=30, help="PageIndex readiness poll attempts")
    parser.add_argument("--poll-seconds", type=int, default=10, help="Seconds between PageIndex polls")

    parser.add_argument("--doc-prefix", default="", help="Prefix applied to auto-generated doc_id values")
    parser.add_argument("--collection", default="default", help="Collection metadata for retrieval partitioning")
    parser.add_argument("--domain", default="general", help="Domain metadata (hr, legal, finance, tech...)" )
    parser.add_argument("--source", default="local", help="Source metadata (local, gdrive, sharepoint, s3)")
    parser.add_argument("--tags", default="", help="Comma-separated tags metadata")
    parser.add_argument("--print-tree", action="store_true", help="Print PageIndex tree for each indexed PDF")

    args = parser.parse_args()

    if not args.pdf and not args.pdf_dir:
        raise SystemExit("Use --pdf or --pdf-dir")

    asyncio.run(main(args))
