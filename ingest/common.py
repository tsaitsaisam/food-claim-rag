"""Shared helpers for ingest scripts."""
from __future__ import annotations
import os, re, json
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parents[2]  # drive-download-...
OUT_DIR = Path(__file__).resolve().parent.parent / "corpus"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def pdf_to_text(path: Path) -> str:
    """Extract text from a PDF preserving page breaks."""
    out = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            out.append(f"\n\n[PAGE {i+1}]\n" + page.get_text())
    return "".join(out)


def docx_to_text(path: Path) -> str:
    from docx import Document
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def read_any(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return pdf_to_text(path)
    if ext == ".docx":
        return docx_to_text(path)
    if ext == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Paragraph-aware chunker. Splits on double newline then packs to ~max_chars."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = (buf + "\n\n" + p) if buf else p
        else:
            if buf:
                chunks.append(buf)
            if len(p) <= max_chars:
                buf = p
            else:
                # hard split very long paragraph
                for i in range(0, len(p), max_chars - overlap):
                    chunks.append(p[i:i + max_chars])
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n
