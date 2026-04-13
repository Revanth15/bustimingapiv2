FROM python:3.13.1 AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app


RUN python -m venv .venv
COPY requirements.txt ./
RUN .venv/bin/pip install -r requirements.txt
FROM python:3.13.1-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY . .
CMD ["/app/.venv/bin/gunicorn", "main:app", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", "--max-requests", "20000", "--max-requests-jitter", "2000", "--timeout", "30", "--bind", "0.0.0.0:8000"]
