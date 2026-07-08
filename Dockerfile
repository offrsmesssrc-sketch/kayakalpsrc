# ─────────────────────────────────────────────────────────────
#  Kaya Kalp Beauty Parlour — Dockerfile (Optimized for Free Tier)
# ─────────────────────────────────────────────────────────────

# Use a pre-built face recognition image as base to avoid compilation timeouts on free tier
FROM datamachines/face_recognition:cpu

# ── Working directory ────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────
# Installing opencv-python-headless (prebuilt wheel, very fast)
RUN pip install --no-cache-dir opencv-python-headless

# ── Application code ─────────────────────────────────────────
COPY server.py favicon.ico ./

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
