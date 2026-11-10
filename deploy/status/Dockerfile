FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    STATUS_CONFIG=/app/config.json STATUS_DB=/data/status.sqlite3 PORT=8080
RUN useradd -u 10001 -m status && mkdir /data && chown status /data
WORKDIR /app
COPY status/ /app/status/
COPY config.json /app/config.json
USER status
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)"
CMD ["python", "-m", "status"]
