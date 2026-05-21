"""RAG core: embed query with Gemini, retrieve from ChromaDB, generate with Gemini."""
from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import chromadb
from google import genai
from google.genai import types

from .prompts import SYSTEM, USER_TEMPLATE

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gemini-2.5-flash")
FALLBACK_MODELS = [m.strip() for m in os.environ.get(
    "FALLBACK_MODELS", "gemini-2.0-flash,gemini-2.5-flash-lite"
).split(",") if m.strip()]
CHROMA_DIR = ROOT / os.environ.get("CHROMA_DIR", "./data/chroma").lstrip("./")

_genai: genai.Client | None = None
_chroma: chromadb.PersistentClient | None = None


def genai_client() -> genai.Client:
    global _genai
    if _genai is None:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY missing — set it in rag_app/.env")
        _genai = genai.Client(api_key=key)
    return _genai


def chroma_client():
    global _chroma
    if _chroma is None:
        _chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _chroma


def embed_query(text: str) -> list[float]:
    resp = genai_client().models.embed_content(
        model=EMBED_MODEL,
        contents=[text[:8000]],
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    return resp.embeddings[0].values


def retrieve(query: str, collection: str, k: int) -> list[dict]:
    coll = chroma_client().get_collection(collection)
    q_emb = embed_query(query)
    res = coll.query(query_embeddings=[q_emb], n_results=k)
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0] if res.get("distances") else [None] * len(docs)
    return [
        {"text": d, "metadata": m, "distance": dist}
        for d, m, dist in zip(docs, metas, dists)
    ]


def format_regs(hits: list[dict]) -> str:
    out = []
    for i, h in enumerate(hits, 1):
        m = h["metadata"]
        header = f"[法規片段 {i}] 來源：{m.get('filename')}（{m.get('category')}）"
        out.append(f"{header}\n{h['text']}")
    return "\n\n---\n\n".join(out) if out else "（無檢索結果）"


def format_cases(hits: list[dict]) -> str:
    out = []
    for i, h in enumerate(hits, 1):
        m = h["metadata"]
        header = (
            f"[案例 {i}] {m.get('year')}年{m.get('month')}月 第{m.get('item')}件"
            f"｜產品：{m.get('product')}"
            f"｜處分商號：{m.get('company')}"
            f"｜罰鍰：{m.get('fine')}元"
            f"｜罰則：{m.get('penalty_basis')}"
        )
        out.append(f"{header}\n{h['text']}")
    return "\n\n---\n\n".join(out) if out else "（無檢索結果）"


def analyze_claim(claim: str, k_reg: int = 6, k_case: int = 6) -> dict[str, Any]:
    reg_hits = retrieve(claim, "regulations", k_reg)
    case_hits = retrieve(claim, "violations", k_case)

    user_msg = USER_TEMPLATE.format(
        claim=claim.strip(),
        regulations=format_regs(reg_hits),
        cases=format_cases(case_hits),
    )

    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        temperature=0.2,
        max_output_tokens=4096,
    )

    # Try primary model with retries; on persistent failure, try fallbacks.
    raw = ""
    model_used = CHAT_MODEL
    last_err: Exception | None = None
    candidates = [CHAT_MODEL] + [m for m in FALLBACK_MODELS if m != CHAT_MODEL]
    for model in candidates:
        for attempt in range(3):
            try:
                resp = genai_client().models.generate_content(
                    model=model, contents=user_msg, config=cfg,
                )
                raw = resp.text or ""
                model_used = model
                last_err = None
                break
            except Exception as e:
                msg = str(e)
                last_err = e
                # 503 UNAVAILABLE / overloaded → quick retry
                if "503" in msg or "UNAVAILABLE" in msg or "overload" in msg.lower():
                    wait = 1.5 * (attempt + 1)
                    print(f"[{model}] 503 attempt {attempt+1}, retry in {wait}s")
                    time.sleep(wait)
                    continue
                # Anything else: break inner, try next model
                break
        if raw:
            break

    if not raw:
        raise RuntimeError(
            f"All Gemini models unavailable (tried: {candidates}). "
            f"Last error: {last_err}"
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "error": "Model returned non-JSON output",
            "raw": raw,
            "retrieved": {"regulations": reg_hits, "cases": case_hits},
        }

    parsed["_debug"] = {
        "model": model_used,
        "embed_model": EMBED_MODEL,
        "retrieved_regulations": [
            {"filename": h["metadata"].get("filename"),
             "category": h["metadata"].get("category"),
             "distance": h["distance"]}
            for h in reg_hits
        ],
        "retrieved_cases": [
            {"year_month": f"{h['metadata'].get('year')}-{h['metadata'].get('month')}",
             "product": h["metadata"].get("product"),
             "fine": h["metadata"].get("fine"),
             "distance": h["distance"]}
            for h in case_hits
        ],
    }
    return parsed
