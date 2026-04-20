FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Corporate CA bundle (Uber + Zscaler) — present in local dev, skipped on Railway/cloud.
# If the file doesn't exist the standard system bundle is used unchanged.
COPY certs/ /tmp/certs/
RUN mkdir -p /app/certs && \
    if [ -f /tmp/certs/uber-corp-ca-bundle.pem ]; then \
        cat /etc/ssl/certs/ca-certificates.crt /tmp/certs/uber-corp-ca-bundle.pem \
            > /app/certs/combined-ca-bundle.pem; \
    else \
        cp /etc/ssl/certs/ca-certificates.crt /app/certs/combined-ca-bundle.pem; \
    fi && \
    rm -rf /tmp/certs

COPY pyproject.toml .

RUN pip install --no-cache-dir \
    --trusted-host pypi.python.org \
    --trusted-host files.pythonhosted.org \
    --trusted-host pypi.org \
    --upgrade pip setuptools wheel

RUN pip install --no-cache-dir \
    --trusted-host pypi.python.org \
    --trusted-host files.pythonhosted.org \
    --trusted-host pypi.org \
    . asyncpg

COPY . .

EXPOSE 8000

# PORT is injected by Railway; falls back to 8000 for local Docker.
CMD ["sh", "-c", "exec uvicorn nichescope.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
