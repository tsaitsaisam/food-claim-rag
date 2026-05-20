"""Embed JSONL corpora with Gemini and write to a persistent ChromaDB."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
import chromadb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if not GEMINI_KEY:
    sys.exit("Missing GEMINI_API_KEY. Put it in rag_app/.env")

EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
CHROMA_DIR = ROOT / os.environ.get("CHROMA_DIR", "./data/chroma").lstrip("./")

client = genai.Client(api_key=GEMINI_KEY)
chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def embed_batch(texts: list[str], task_type: str, retries: int = 6) -> list[list[float]]:
    """Gemini embedding with exponential backoff on 429."""
    import re
    for attempt in range(retries):
        try:
            resp = client.models.embed_content(
                model=EMBED_MODEL,
                contents=texts,
                config=types.EmbedContentConfig(task_type=task_type),
            )
            return [e.values for e in resp.embeddings]
        except Exception as e:
            msg = str(e)
            if attempt == retries - 1:
                raise
            # Parse server-suggested retryDelay if present (e.g. 58.06s)
            m = re.search(r"retry in ([\d.]+)s", msg)
            wait = float(m.group(1)) + 2 if m else 2 ** (attempt + 2)
            wait = min(wait, 90)
            print(f"  embed retry {attempt+1} after {wait:.0f}s ({type(e).__name__})")
            time.sleep(wait)
    return []


def index_jsonl(jsonl_path: Path, collection_name: str, batch_size: int = 10,
                pause_per_batch: float = 1.2, resume: bool = True):
    """Free-tier safe: batch_size=10, pause 1.2s/batch.

    resume=True: keep existing collection, skip IDs already indexed.
    resume=False: wipe and rebuild.
    """
    rows = load_jsonl(jsonl_path)
    print(f"\n=== {collection_name}: {len(rows)} docs total ===")

    if resume:
        try:
            coll = chroma.get_collection(collection_name)
        except Exception:
            coll = chroma.create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        existing = set(coll.get(include=[])["ids"])
        if existing:
            before = len(rows)
            rows = [r for r in rows if r["id"] not in existing]
            print(f"  resume: skipping {before - len(rows)} already-indexed docs, {len(rows)} remaining")
        if not rows:
            print(f"  → '{collection_name}' already complete ({coll.count()} docs)")
            return
    else:
        try:
            chroma.delete_collection(collection_name)
        except Exception:
            pass
        coll = chroma.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    for i in tqdm(range(0, len(rows), batch_size), desc=collection_name):
        chunk = rows[i:i + batch_size]
        ids = [r["id"] for r in chunk]
        docs = [r["text"][:8000] for r in chunk]  # Gemini embedding input limit
        metas = [r["metadata"] for r in chunk]
        embs = embed_batch(docs, task_type="RETRIEVAL_DOCUMENT")
        coll.add(ids=ids, documents=docs, metadatas=metas, embeddings=embs)
        time.sleep(pause_per_batch)

    print(f"  → indexed {coll.count()} docs in '{collection_name}'")


def main():
    corpus = ROOT / "corpus"
    index_jsonl(corpus / "regulations.jsonl", "regulations")
    index_jsonl(corpus / "cases.jsonl", "violations")
    print(f"\nChromaDB persisted at: {CHROMA_DIR}")


if __name__ == "__main__":
    main()
