# syntax=docker/dockerfile:1
FROM python:3.12-slim

# --- system deps -----------------------------------------------------------
# curl is used by the healthcheck; build-essential covers any wheels that need
# compilation (ephem/scipy ship wheels, but this keeps the build robust).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# --- python deps (cached layer) --------------------------------------------
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# --- app -------------------------------------------------------------------
COPY . .

# Run as a non-root user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", \
    "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
