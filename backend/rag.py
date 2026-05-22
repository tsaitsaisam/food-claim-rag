"""RAG core: embed query with Gemini, retrieve from ChromaDB, generate with Gemini.

Hardened version:
- Uses `response_schema` (Pydantic) so Gemini's output is structurally guaranteed.
- Lenient JSON parsing as a second-layer guard.
- Categorized exceptions (quota / overload / parse / empty / unknown) so the
  HTTP layer can return clear, user-facing Chinese messages instead of stack traces.
"""
from __future__ import annotations
import json, os, re, time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import chromadb
from google import genai
from google.genai import types
from pydantic import ValidationError

from .prompts import SYSTEM, USER_TEMPLATE
from .schemas import ComplianceResponse

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


# ──────────────────────────────────────────────────────────────────────
#  Exception taxonomy — HTTP layer maps these to user-facing 中文 messages
# ──────────────────────────────────────────────────────────────────────
class RagError(Exception):
    """Base. Subclasses carry a `user_message` (中文) and `code`."""
    code = "unknown_error"
    user_message = "系統發生未預期錯誤，請稍後再試。"

    def __init__(self, detail: str = "", user_message: str | None = None):
        super().__init__(detail or self.user_message)
        self.detail = detail
        if user_message:
            self.user_message = user_message


class QuotaExceededError(RagError):
    code = "quota_exceeded"
    user_message = "Gemini API 今日免費額度已用完，請等待重置（每日台灣時間下午 3 點左右）或開啟 Billing。"


class ModelOverloadedError(RagError):
    code = "model_overloaded"
    user_message = "Gemini 模型暫時擁塞（高峰時段常見），請 10-30 秒後重試。"


class EmptyRetrievalError(RagError):
    code = "empty_retrieval"
    user_message = "向量資料庫沒有檢索到任何相關內容，可能是索引尚未建立完成。"


class ResponseParseError(RagError):
    code = "parse_error"
    user_message = "模型回應格式不符合預期，已嘗試修補但失敗。請重新送出或縮短輸入。"


class AuthError(RagError):
    code = "auth_error"
    user_message = "Gemini API key 認證失敗，請檢查環境變數設定。"


class NetworkError(RagError):
    code = "network_error"
    user_message = "與 Gemini 服務的連線中斷或逾時，請稍後再試。"


def _classify_gemini_error(e: Exception) -> RagError:
    msg = str(e)
    low = msg.lower()
    if "401" in msg or "403" in msg or "permission" in low or "unauthenticated" in low or "api key" in low:
        return AuthError(msg)
    if "429" in msg or "resource_exhausted" in low or "quota" in low:
        return QuotaExceededError(msg)
    if "503" in msg or "unavailable" in low or "overload" in low:
        return ModelOverloadedError(msg)
    if "timeout" in low or "timed out" in low or "connection" in low:
        return NetworkError(msg)
    return RagError(msg)


# ──────────────────────────────────────────────────────────────────────
#  Clients
# ──────────────────────────────────────────────────────────────────────
def genai_client() -> genai.Client:
    global _genai
    if _genai is None:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise AuthError("GEMINI_API_KEY missing — set it in environment or .env")
        _genai = genai.Client(api_key=key)
    return _genai


def chroma_client():
    global _chroma
    if _chroma is None:
        _chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _chroma


# ──────────────────────────────────────────────────────────────────────
#  Retrieval
# ──────────────────────────────────────────────────────────────────────
def embed_query(text: str) -> list[float]:
    try:
        resp = genai_client().models.embed_content(
            model=EMBED_MODEL,
            contents=[text[:8000]],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        return resp.embeddings[0].values
    except Exception as e:
        raise _classify_gemini_error(e) from e


def retrieve(query: str, collection: str, k: int) -> list[dict]:
    try:
        coll = chroma_client().get_collection(collection)
    except Exception as e:
        raise EmptyRetrievalError(f"Collection '{collection}' not found: {e}") from e
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


# ──────────────────────────────────────────────────────────────────────
#  Lenient JSON parser
# ──────────────────────────────────────────────────────────────────────
def _try_parse_json(raw: str) -> dict | None:
    """Best-effort JSON extraction. Returns dict or None.

    Handles:
    - Pure JSON
    - JSON wrapped in ```json fences
    - Leading / trailing prose around an outer { ... }
    - Trailing commas (light cleanup)
    """
    if not raw:
        return None

    candidates: list[str] = [raw.strip()]

    # Strip code fences if present
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.DOTALL)
    if m:
        candidates.insert(0, m.group(1))

    # Outermost {...}
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(raw[start:end + 1])

    for c in candidates:
        for variant in (c, re.sub(r",\s*([}\]])", r"\1", c)):
            try:
                obj = json.loads(variant)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


# ──────────────────────────────────────────────────────────────────────
#  Main entry
# ──────────────────────────────────────────────────────────────────────
def analyze_claim(claim: str, k_reg: int = 6, k_case: int = 6) -> dict[str, Any]:
    """Returns a dict conforming to ComplianceResponse, plus _debug.

    Raises a subclass of RagError on any failure that the HTTP layer should
    surface as a user-facing message.
    """
    # 1. Retrieval (raises EmptyRetrievalError / AuthError / QuotaExceededError)
    reg_hits = retrieve(claim, "regulations", k_reg)
    case_hits = retrieve(claim, "violations", k_case)
    if not reg_hits and not case_hits:
        raise EmptyRetrievalError("Both regulation and case collections returned 0 hits.")

    user_msg = USER_TEMPLATE.format(
        claim=claim.strip(),
        regulations=format_regs(reg_hits),
        cases=format_cases(case_hits),
    )

    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_schema=ComplianceResponse,  # ← structured-output enforcement
        temperature=0.2,
        # 中文回應每字 1-2 tokens；6 violations + 3 cases + 改寫 + 變更說明
        # 約需 5-7k tokens。預留到 16k 避免被切斷。
        max_output_tokens=16384,
    )

    # 2. Generate with retries + model fallback
    raw = ""
    model_used = CHAT_MODEL
    last_err: Exception | None = None
    candidates = [CHAT_MODEL] + [m for m in FALLBACK_MODELS if m != CHAT_MODEL]
    overloaded_streak = 0

    for model in candidates:
        for attempt in range(3):
            try:
                resp = genai_client().models.generate_content(
                    model=model, contents=user_msg, config=cfg,
                )
                raw = resp.text or ""
                if raw:
                    model_used = model
                    last_err = None
                    break
            except Exception as e:
                classified = _classify_gemini_error(e)
                last_err = classified
                if isinstance(classified, ModelOverloadedError):
                    overloaded_streak += 1
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if isinstance(classified, (AuthError, QuotaExceededError)):
                    raise classified from e  # no point retrying these
                # other errors: break to next model
                break
        if raw:
            break

    if not raw:
        # All models exhausted
        if isinstance(last_err, RagError):
            raise last_err
        raise ModelOverloadedError(f"All models failed. last={last_err}")

    # 3. Parse + validate with Pydantic
    parsed_dict = _try_parse_json(raw)
    if parsed_dict is None:
        # Detect truncation (unbalanced braces) to give a clearer hint
        open_braces = raw.count("{") - raw.count("}")
        if open_braces > 0:
            raise ResponseParseError(
                f"Model output was truncated mid-JSON ({open_braces} unbalanced braces). "
                f"This usually means the response exceeded max_output_tokens. "
                f"Tail: …{raw[-200:]}",
                user_message="模型回應在中途被截斷（內容過長）。請減少檢索 K 值或縮短輸入後重試。",
            )
        raise ResponseParseError(f"Could not extract JSON from output. First 200 chars: {raw[:200]}")

    try:
        validated = ComplianceResponse.model_validate(parsed_dict)
    except ValidationError as ve:
        # Try one more time: maybe model returned partial; supply safe defaults
        try:
            patched = _patch_missing_fields(parsed_dict)
            validated = ComplianceResponse.model_validate(patched)
        except ValidationError as ve2:
            raise ResponseParseError(
                f"Schema validation failed even after patching: {ve2.errors()[:3]}"
            ) from ve

    out = validated.model_dump()
    out["_debug"] = {
        "model": model_used,
        "embed_model": EMBED_MODEL,
        "overload_retries": overloaded_streak,
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
    return out


def _patch_missing_fields(d: dict) -> dict:
    """Inject empty defaults for any missing required leaf field.

    Only patches structural fields, not factual content. Used as a last
    resort so that the frontend always renders something sensible.
    """
    d = dict(d)
    la = d.get("legal_analysis") or {}
    la.setdefault("summary", "")
    la.setdefault("violations", [])
    d["legal_analysis"] = la

    d.setdefault("similar_cases", [])

    sr = d.get("suggested_revision") or {}
    sr.setdefault("revised_text", "")
    sr.setdefault("changes_explained", [])
    d["suggested_revision"] = sr
    return d
