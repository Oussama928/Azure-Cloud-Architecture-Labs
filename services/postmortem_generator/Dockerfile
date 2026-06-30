# Postmortem Generator Dockerfile
FROM python:3.12-slim as builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ libffi-dev libssl-dev && rm -rf /var/lib/apt/lists/*
COPY services/postmortem_generator/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libffi8 libssl3 ca-certificates && rm -rf /var/lib/apt/lists/*
RUN groupadd -r appuser && useradd -r -g appuser appuser
COPY --from=builder /root/.local /home/appuser/.local
COPY services/postmortem_generator/src/ ./services/postmortem_generator/src/
COPY services/shared/ ./services/shared/
RUN chown -R appuser:appuser /app
USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 CMD python -c "import httpx; httpx.get('http://localhost:8006/health', timeout=5)"
EXPOSE 8006
CMD ["python", "-m", "uvicorn", "services.postmortem_generator.src.main:app", "--host", "0.0.0.0", "--port", "8006"]
