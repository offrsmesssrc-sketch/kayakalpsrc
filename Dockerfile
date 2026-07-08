# ─────────────────────────────────────────────────────────────
#  Kaya Kalp Beauty Parlour — Dockerfile (Optimized for Free Tier)
# ─────────────────────────────────────────────────────────────

# Use Python 3.10 slim as base (lightweight and fast)
FROM python:3.10-slim

# ── Working directory ────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────
# Installing requirements (very fast since heavy libraries are optional)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────
COPY server.py .

# ── Data volume ──────────────────────────────────────────────
# Ephemeral in Free tier, but persists if using a paid volume mount
VOLUME ["/data"]

# ── Environment defaults ─────────────────────────────────────
ENV DATA_FOLDER=/data
ENV PORT=8000

# Render.com injects PORT automatically — server.py reads it
EXPOSE 8000

# ── Start command ─────────────────────────────────────────────
CMD ["python", "server.py"]
