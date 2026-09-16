#!/usr/bin/env bash
# Gunicorn launcher for Sneha Creations ERP.
#
# Worker count: (2 * cores) + 1 capped at 3 for this 2-core / 6 GB box.
# Connection budget: 3 workers * (pool_size 10 + overflow 20) = 90,
# leaving 10 of Postgres' 100 max_connections as admin reserve.
#
# When moving to a bigger instance, adjust both:
#   workers  -> (2 * cores) + 1
#   pool     -> so workers * (pool_size + max_overflow) < max_connections
set -e

exec gunicorn app.main:app \
    --workers "${GUNICORN_WORKERS:-3}" \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind "${BIND:-0.0.0.0:8000}" \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --access-logfile - \
    --error-logfile - \
    --log-level "${LOG_LEVEL:-info}"
