"""Extract & chunk core regulations relevant to 食品/健康食品 廣告宣稱.

Scope (MVP): 認定準則、食安法第28條相關公告、健康食品管理法、113年食品標示法規手冊。
Output: corpus/regulations.jsonl
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, OUT_DIR, read_any, chunk_text, write_jsonl

# Directories / files to ingest as "regulations"
TARGETS = [
    # Most important: 認定準則 + 廣告處理 (食安法第28條 folder)
    ROOT / "食藥署" / "食安法" / "食安法第28條",
    # 健康食品 (whole folder)
    ROOT / "食藥署" / "健康食品管理法",
    # 標示法規手冊與指引
    ROOT / "食藥署" / "113年版食品標示法規手冊指引與問答集",
    # 額外指引（包裝食品宣稱素食、咖啡因等）
    ROOT / "食藥署" / "額外補充、指引",
    # 食安法第45/47/49條之一/49條之二（罰則條文）
    ROOT / "食藥署" / "食安法" / "食安法第45條",
    ROOT / "食藥署" / "食安法" / "食安法第47條",
    ROOT / "食藥署" / "食安法" / "食安法第49條之一",
    ROOT / "食藥署" / "食安法" / "食安法第49條之二",
    # 食安法第22條 (產品標示)
    ROOT / "食藥署" / "食安法" / "食安法第22條",
]

KEEP_EXT = {".pdf", ".docx", ".txt"}


def iter_files():
    for t in TARGETS:
        if not t.exists():
            print(f"[skip missing] {t}")
            continue
        if t.is_file() and t.suffix.lower() in KEEP_EXT:
            yield t
        elif t.is_dir():
            for f in t.rglob("*"):
                if f.is_file() and f.suffix.lower() in KEEP_EXT:
                    # Skip duplicates: if both .docx and .txt + .pdf exist, prefer .txt (AI資料庫)
                    yield f


def dedupe(files):
    """Prefer .txt over .docx over .pdf when same stem exists."""
    by_stem: dict[tuple[Path, str], Path] = {}
    pri = {".txt": 0, ".docx": 1, ".pdf": 2}
    for f in files:
        key = (f.parent, f.stem.replace(" AI資料庫", ""))
        if key not in by_stem or pri[f.suffix.lower()] < pri[by_stem[key].suffix.lower()]:
            by_stem[key] = f
    return list(by_stem.values())


def main():
    files = dedupe(list(iter_files()))
    print(f"Ingesting {len(files)} regulation files…")

    rows = []
    for i, f in enumerate(files, 1):
        try:
            txt = read_any(f)
        except Exception as e:
            print(f"  [err] {f}: {e}")
            continue
        if not txt or len(txt.strip()) < 50:
            continue
        chunks = chunk_text(txt, max_chars=1200, overlap=150)
        rel = f.relative_to(ROOT)
        # category from path: 食安法第XX條 / 健康食品管理法 / 標示手冊 / 額外指引
        parts = rel.parts
        if "食安法" in parts:
            idx = parts.index("食安法")
            category = parts[idx + 1] if idx + 1 < len(parts) else "食安法"
        elif "健康食品管理法" in parts:
            category = "健康食品管理法"
        elif "113年版食品標示法規手冊指引與問答集" in parts:
            category = "食品標示法規手冊"
        else:
            category = "其他指引"
        for j, ch in enumerate(chunks):
            rows.append({
                "id": f"reg::{rel.as_posix()}::{j}",
                "text": ch,
                "metadata": {
                    "source": rel.as_posix(),
                    "filename": f.name,
                    "category": category,
                    "chunk_index": j,
                    "doc_type": "regulation",
                },
            })
        if i % 10 == 0:
            print(f"  [{i}/{len(files)}] {rel}")

    out = OUT_DIR / "regulations.jsonl"
    n = write_jsonl(out, rows)
    print(f"\nWrote {n} chunks from {len(files)} files → {out}")


if __name__ == "__main__":
    main()
