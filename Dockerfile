FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build deps for chromadb / pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app + pre-built ChromaDB + corpus
COPY . .

# HF Spaces routes traffic to port 7860 by default
EXPOSE 7860

# HF Spaces makes / read-only at runtime; ChromaDB only reads at query-time
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
