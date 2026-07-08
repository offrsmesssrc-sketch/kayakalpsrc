# ─────────────────────────────────────────────────────────────
#  Kaya Kalp Beauty Parlour — Dockerfile
#  Builds the headless cloud server for Render.com
# ─────────────────────────────────────────────────────────────

# Use Python 3.10 slim as base (good balance of size and compatibility)
FROM python:3.10-slim

# ── System dependencies ──────────────────────────────────────
# cmake + build-essential  → needed to compile dlib (face recognition)
# libgl1 + libglib2.0-0    → needed by OpenCV
# libsm6, libxext6         → OpenCV display libraries (needed even headless)
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake \
    g++ \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────
# Copy requirements first for Docker layer caching
# (packages only reinstall when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────
COPY server.py .

# ── Data volume ──────────────────────────────────────────────
# /data is mounted as a Render Persistent Disk
# This keeps your SQLite database and face photos safe across redeploys
VOLUME ["/data"]

# ── Environment defaults ─────────────────────────────────────
ENV DATA_FOLDER=/data
ENV PORT=8000

# Render.com injects PORT automatically — server.py reads it
EXPOSE 8000

# ── Start command ─────────────────────────────────────────────
CMD ["python", "server.py"]
