"""FastAPI app: POST /api/ask  → three-part legal analysis."""
from __future__ import annotations
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .rag import analyze_claim

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
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.get("/api/health")
def health():
    return {"ok": True}


# Serve frontend
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/")
    def root():
        return FileResponse(FRONTEND / "index.html")
