# syntax=docker/dockerfile:1
#
# Container image for the Flask app. Production on the LiteSpeed host runs
# under Passenger instead (see DEPLOYMENT.md); this exists for local testing
# and for anyone deploying to a container platform.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install gunicorn

COPY . .

RUN useradd --create-home appuser \
    && mkdir -p /app/.cache \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/robots.txt || exit 1

# DATABASE_URL, SECRET_KEY and the rest come from the environment.
# Run migrations separately:  docker run ... alembic upgrade head
CMD ["gunicorn", "-w", "3", "-b", "0.0.0.0:8000", "--timeout", "60", "wsgi:application"]
