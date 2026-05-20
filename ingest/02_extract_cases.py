"""Extract violation-case rows from 臺北市政府衛生局 monthly statistics PDFs.

Each case becomes one document (rich metadata + full 違規情節 as searchable text).
Output: corpus/cases.jsonl
"""
from __future__ import annotations
import re, sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, OUT_DIR, write_jsonl

CASE_DIRS = [
    ROOT / "台北市政府公告114年違規廣告",
    ROOT / "台北市政府公告115年違規廣告",
]

# Column header aliases (handle line breaks in header cells)
HEADER_MAP = {
    "項次": "item",
    "裁處書\n發文日期": "issued_date",
    "裁處書發文日期": "issued_date",
    "產品名稱": "product",
    "來源": "source",
    "違規情節": "violation",
    "處分商號\n名稱": "company",
    "處分商號名稱": "company",
    "罰鍰金額\n(元)": "fine",
    "罰鍰金額(元)": "fine",
    "罰則註記": "penalty_basis",
    "排名": "rank",
}


def clean(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.replace("\n", " ").strip())


def parse_year_month(filename: str) -> tuple[str, str] | None:
    m = re.search(r"(\d{3})年(\d{1,2})月", filename)
    if not m:
        return None
    return m.group(1), m.group(2).zfill(2)


def extract_cases_from_pdf(pdf_path: Path) -> list[dict]:
    year_month = parse_year_month(pdf_path.name)
    if not year_month:
        print(f"  [skip] cannot parse year/month: {pdf_path.name}")
        return []
    year, month = year_month
    out: list[dict] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                header_row = table[0]
                col_keys = [HEADER_MAP.get((h or "").strip(), None) for h in header_row]
                if "violation" not in col_keys or "item" not in col_keys:
                    continue
                for row in table[1:]:
                    rec = {col_keys[i]: row[i] for i in range(len(col_keys)) if col_keys[i]}
                    # Skip empty / header-repeat rows
                    item = (rec.get("item") or "").strip()
                    violation = (rec.get("violation") or "").strip()
                    if not item or not item.isdigit() or not violation:
                        continue
                    out.append({
                        "year": year,
                        "month": month,
                        "item": item,
                        "product": clean(rec.get("product")),
                        "source": clean(rec.get("source")),
                        "violation": violation,  # keep newlines for readability
                        "company": clean(rec.get("company")),
                        "fine": clean(rec.get("fine")),
                        "penalty_basis": clean(rec.get("penalty_basis")),
                        "page": page_no,
                        "pdf": pdf_path.name,
                    })
    return out


def main():
    all_cases: list[dict] = []
    for d in CASE_DIRS:
        if not d.exists():
            print(f"[skip missing] {d}")
            continue
        for pdf in sorted(d.glob("*.pdf")):
            cases = extract_cases_from_pdf(pdf)
            print(f"  {pdf.name}: {len(cases)} cases")
            all_cases.extend(cases)

    # Convert to ingestion records (one chunk per case)
    rows = []
    for c in all_cases:
        # Searchable text bundles every signal for retrieval
        text = (
            f"產品：{c['product']}｜來源：{c['source']}｜罰鍰：{c['fine']}元｜"
            f"處分商號：{c['company']}｜罰則：{c['penalty_basis']}\n\n"
            f"違規情節：\n{c['violation']}"
        )
        rid = f"case::{c['year']}-{c['month']}::{c['item']}::{c['pdf']}"
        rows.append({
            "id": rid,
            "text": text,
            "metadata": {
                "doc_type": "case",
                "year": c["year"],
                "month": c["month"],
                "item": c["item"],
                "product": c["product"][:200],
                "company": c["company"][:200],
                "source_channel": c["source"][:50],
                "fine": c["fine"],
                "penalty_basis": c["penalty_basis"][:200],
                "pdf": c["pdf"],
                "page": c["page"],
            },
        })

    out = OUT_DIR / "cases.jsonl"
    n = write_jsonl(out, rows)
    print(f"\nWrote {n} cases → {out}")


if __name__ == "__main__":
    main()
