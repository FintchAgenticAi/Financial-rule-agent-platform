FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY rules ./rules

RUN mkdir -p /app/data /app/outputs /app/job-state \
    && groupadd --gid 10001 appgroup \
    && useradd --create-home --uid 10001 --gid 10001 appuser \
    && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["python", "-m", "src.main"]
