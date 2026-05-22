"""FastAPI app: POST /api/ask → three-part legal analysis."""
from __future__ import annotations
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .rag import analyze_claim, RagError

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="食品宣稱合規檢查 RAG")


class AskRequest(BaseModel):
    claim: str = Field(..., min_length=2, max_length=5000)
    k_reg: int = Field(6, ge=1, le=15)
    k_case: int = Field(6, ge=1, le=15)


@app.post("/api/ask")
def ask(req: AskRequest):
    if not req.claim.strip():
        raise HTTPException(400, "claim is empty")
    try:
        return analyze_claim(req.claim, k_reg=req.k_reg, k_case=req.k_case)
    except RagError as e:
        # Categorized error → clean JSON envelope the frontend can display
        status_map = {
            "auth_error": 401,
            "quota_exceeded": 429,
            "model_overloaded": 503,
            "network_error": 504,
            "empty_retrieval": 502,
            "parse_error": 502,
            "unknown_error": 500,
        }
        status = status_map.get(e.code, 500)
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": e.code,
                    "message": e.user_message,
                    "detail": e.detail[:500] if e.detail else "",
                }
            },
        )
    except Exception as e:
        # Anything truly unexpected
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "系統內部錯誤，請稍後再試或聯絡管理員。",
                    "detail": f"{type(e).__name__}: {str(e)[:300]}",
                }
            },
        )


@app.get("/api/health")
def health():
    return {"ok": True}


# Serve frontend
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/")
    def root():
        return FileResponse(
            FRONTEND / "index.html",
            headers={
                # No-cache so users always get the latest frontend on deploy
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
