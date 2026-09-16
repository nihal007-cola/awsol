FROM python:3.13-slim

# System deps:
#   build-essential + libpq-dev  -> psycopg2-binary fallback if wheel is missing
#   curl                         -> HEALTHCHECK against /utils/health
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app ./app
COPY db ./db
COPY migrations ./migrations
COPY alembic.ini .
COPY start.sh .
RUN chmod +x start.sh

# Non-root user for runtime
RUN useradd --create-home --shell /bin/bash erp && chown -R erp:erp /app
USER erp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/utils/health || exit 1

CMD ["./start.sh"]
