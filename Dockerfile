FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cache-friendly)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code — keep the /app/app/ layout so main.py's relative paths resolve
COPY backend/app ./app
COPY backend/db ./db
COPY backend/migrations ./migrations
COPY backend/alembic.ini .
COPY backend/start.sh .
RUN chmod +x start.sh

# Frontend — main.py expects /frontend (parent.parent.parent from /app/app/main.py)
COPY frontend /frontend

RUN useradd --create-home --shell /bin/bash erp && chown -R erp:erp /app /frontend
USER erp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/utils/health || exit 1

CMD ["./start.sh"]
