#!/bin/bash
# Resume embedding ingest after Gemini free-tier quota resets.
# Safe to re-run: script skips already-indexed docs.

set -u
cd "$(dirname "$0")/.." || exit 1

LOG="$(pwd)/logs/ingest_$(date +%Y%m%d_%H%M%S).log"
LATEST="$(pwd)/logs/ingest_latest.log"

{
  echo "=============================================="
  echo "Ingest run started: $(date)"
  echo "=============================================="

  /usr/bin/env python3 ingest/03_embed_index.py
  RC=$?

  echo ""
  echo "=============================================="
  echo "Ingest exit code: $RC"
  echo "Finished: $(date)"
  echo "=============================================="

  echo ""
  echo "[ChromaDB final state]"
  /usr/bin/env python3 -c "
import chromadb
c = chromadb.PersistentClient(path='./data/chroma')
for name in ['regulations','violations']:
    try:
        col = c.get_collection(name)
        print(f'  {name}: {col.count()} docs')
    except Exception as e:
        print(f'  {name}: MISSING ({e})')
"

  exit $RC
} > "$LOG" 2>&1

ln -sf "$LOG" "$LATEST"
