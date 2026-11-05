#!/bin/sh
# Server start: prepare data, model and admin account if missing, then serve.
set -e
python -m shambasense.cli bootstrap --no-figures
exec uvicorn shambasense.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
