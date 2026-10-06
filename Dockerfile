FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . && useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
RUN python -m codeatlas index examples/sample_repo
EXPOSE 8081
CMD ["python", "-m", "codeatlas", "serve", "--bind", "0.0.0.0"]
