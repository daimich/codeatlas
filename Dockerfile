FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ARG ENABLE_SEMANTIC=0
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . \
    && if [ "$ENABLE_SEMANTIC" = "1" ]; then \
         pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
         && pip install --no-cache-dir '.[semantic]'; fi \
    && apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home appuser && mkdir -p /data /home/appuser/.cache \
    && chown -R appuser:appuser /app /data /home/appuser/.cache
USER appuser
RUN python -m codeatlas --db /data/index.sqlite3 index examples/sample_repo
VOLUME ["/data"]
EXPOSE 8081
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/api/health',timeout=2)"
ENTRYPOINT ["python", "-m", "codeatlas", "--db", "/data/index.sqlite3"]
CMD ["serve", "--bind", "0.0.0.0"]
