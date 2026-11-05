FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY config ./config
COPY shambasense ./shambasense
COPY web ./web
COPY data/templates ./data/templates
COPY scripts ./scripts
COPY start.sh ./

# Train the demo model at build time (deterministic synthetic data), so a free
# server with a wiped disk starts in seconds. Real deployments retrain from the
# admin dashboard after loading agency data.
RUN DATABASE_URL=sqlite:////tmp/build.db SHAMBA_DEMO=1 SHAMBA_OFFLINE=1 \
    python -m shambasense.cli bootstrap --no-figures && rm -f /tmp/build.db

RUN useradd --create-home shamba && chown -R shamba /app
USER shamba

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.getenv(\"PORT\", \"8000\")}/health')"
CMD ["./start.sh"]
