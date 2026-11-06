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
COPY data/real ./data/real
COPY scripts ./scripts
COPY start.sh ./

# Train the model at build time from the real-data snapshot in data/real/ (county yields,
# NASA POWER weather, SoilGrids soil), so the server starts in seconds. Build with
# --build-arg SHAMBA_DEMO=1 for the synthetic demo instead.
ARG SHAMBA_DEMO=0
RUN DATABASE_URL=sqlite:////tmp/build.db SHAMBA_DEMO=$SHAMBA_DEMO SHAMBA_OFFLINE=1 \
    python -m shambasense.cli bootstrap --no-figures && rm -f /tmp/build.db

RUN useradd --create-home shamba && chown -R shamba /app
USER shamba

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.getenv(\"PORT\", \"8000\")}/health')"
CMD ["./start.sh"]
