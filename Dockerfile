# Single container, no storage volume. Debian slim (glibc) because curl_cffi wheels need it.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY data ./data

# Run as non-root. Nothing in the app writes to disk.
RUN useradd --system --no-create-home appuser
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/healthz').status==200 else 1)"

# One worker on purpose: scan state lives in memory. Exec form so a host command
# override cannot leave the container "up" with nothing running.
ENTRYPOINT ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --no-server-header"]
