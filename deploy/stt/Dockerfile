# Speech to text for voice tasks (deploy/stt/server.py): Whisper on the CPU behind an
# OpenAI-compatible endpoint. Its own small image, because CTranslate2 and PyAV wheels follow
# their own Python releases; the backend talks to it over HTTP only.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models

COPY requirements.txt /srv/requirements.txt
RUN pip install --require-hashes -r /srv/requirements.txt \
    && useradd --system --uid 10001 --home-dir /srv stt \
    && mkdir -p /models && chown stt /models

COPY server.py /srv/server.py
WORKDIR /srv
USER stt
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
