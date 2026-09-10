FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TEMP=/app/tmp TMP=/app/tmp TMPDIR=/app/tmp
WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN mkdir -p /app/tmp && chmod 1777 /app/tmp \
    && python -m pip install --no-cache-dir -r requirements.txt && python -m pip check \
    && useradd --uid 10001 --create-home app
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/container-entrypoint.sh ./
RUN chmod 755 container-entrypoint.sh
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=12 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
ENTRYPOINT ["/bin/sh", "/app/backend/container-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
