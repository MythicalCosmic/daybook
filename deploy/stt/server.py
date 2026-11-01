"""Speech to text for voice tasks: a small OpenAI-compatible transcription service.

The backend sends voice messages here (`AI_SPEECH_URL=http://stt:8000/v1`) the same way it would
send them to a hosted provider, so switching to OpenAI or Groq is a matter of settings:

    POST /v1/audio/transcriptions  multipart: file, [model], [language], [prompt],
                                   [response_format]
    GET  /health                   {"status": "ok" | "loading" | "error", "models": {...}}

Whisper runs with CTranslate2 (faster-whisper) on the CPU. Stock Whisper is weak at Uzbek, so a
language can have its own fine-tuned model: with STT_MODELS_BY_LANGUAGE="uz=<model>", a request
whose `language` is "uz" uses that model and everything else the multilingual STT_MODEL. Models
load once at start-up (downloading into HF_HOME the first time); transcriptions run one at a time
(STT_CONCURRENCY) in a worker thread, so a burst of voice messages queues instead of starving
the web server of CPU.

Settings (environment): STT_MODEL (large-v3-turbo), STT_MODELS_BY_LANGUAGE ("");
a model is a faster-whisper size ("large-v3") or a Hugging Face repository, optionally pinned to
a commit ("org/model@<sha>"),
STT_COMPUTE_TYPE (int8), STT_CPU_THREADS (4), STT_BEAM_SIZE (1), STT_CONCURRENCY (1),
STT_MAX_BYTES (25 MB), STT_MAX_SECONDS (300), STT_API_KEY (optional: when set, requests need
`Authorization: Bearer <key>`).
"""

import asyncio
import contextlib
import logging
import os
import tempfile
import threading
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

log = logging.getLogger("stt")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DEFAULT_MODEL = os.environ.get("STT_MODEL", "large-v3-turbo")
COMPUTE_TYPE = os.environ.get("STT_COMPUTE_TYPE", "int8")
CPU_THREADS = int(os.environ.get("STT_CPU_THREADS", "4"))
BEAM_SIZE = int(os.environ.get("STT_BEAM_SIZE", "1"))
CONCURRENCY = int(os.environ.get("STT_CONCURRENCY", "1"))
MAX_BYTES = int(os.environ.get("STT_MAX_BYTES", str(25 * 1024 * 1024)))
# Clients say how long a recording is, but only the audio itself can be trusted: a few MB of
# low-bitrate audio can hold an hour. Longer than this is refused after decoding, before Whisper.
MAX_SECONDS = int(os.environ.get("STT_MAX_SECONDS", "300"))
SAMPLE_RATE = 16_000  # what decode_audio gives and Whisper reads
API_KEY = os.environ.get("STT_API_KEY", "")
LANGUAGES = {"uz", "ru", "en", "tr", "kk", "tg", "ky"}
PROMPT_MAX = 600  # characters; Whisper reads ~224 tokens of prompt at most


def _by_language(raw: str) -> dict[str, str]:
    """ "uz=org/model, ru=other/model" -> {"uz": "org/model", "ru": "other/model"}."""
    pairs = (item.split("=", 1) for item in raw.split(",") if "=" in item)
    return {lang.strip().lower(): name.strip() for lang, name in pairs if name.strip()}


BY_LANGUAGE = _by_language(os.environ.get("STT_MODELS_BY_LANGUAGE", ""))
# name -> {"status": loading|ok|error, "model": WhisperModel | None, "error": str}
_models: dict[str, dict] = {
    name: {"status": "loading", "model": None, "error": ""}
    for name in dict.fromkeys([DEFAULT_MODEL, *BY_LANGUAGE.values()])
}
_slots = asyncio.Semaphore(CONCURRENCY)


def _load_all() -> None:
    from faster_whisper import WhisperModel

    for name, entry in _models.items():  # the default first: it serves every language
        started = time.monotonic()
        # "org/model@<commit>" pins a Hugging Face repository to one revision.
        repo, _, revision = name.partition("@")
        try:
            entry["model"] = WhisperModel(
                repo,
                device="cpu",
                compute_type=COMPUTE_TYPE,
                cpu_threads=CPU_THREADS,
                revision=revision or None,
            )
            entry["status"] = "ok"
            log.info("loaded %s (%s) in %.1f s", name, COMPUTE_TYPE, time.monotonic() - started)
        except Exception as error:  # the service stays up and says why on /health
            entry.update(status="error", error=str(error)[:300])
            log.exception("could not load %s", name)


def _pick(language: str | None) -> tuple[str, object] | None:
    """The model for `language`: its own when it has one and it loaded, else the default."""
    for name in (BY_LANGUAGE.get(language or ""), DEFAULT_MODEL):
        entry = _models.get(name or "")
        if entry and entry["status"] == "ok":
            return name, entry["model"]
    return None


class TooLong(Exception):
    pass


def _transcribe(model, path: str, language: str | None, prompt: str | None) -> dict:
    from faster_whisper import decode_audio

    audio = decode_audio(path, sampling_rate=SAMPLE_RATE)
    if len(audio) > MAX_SECONDS * SAMPLE_RATE:
        raise TooLong
    segments, info = model.transcribe(
        audio,
        language=language,
        initial_prompt=prompt or None,
        beam_size=BEAM_SIZE,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    parts = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments
    ]
    return {
        "text": " ".join(part["text"] for part in parts if part["text"]).strip(),
        "language": info.language,
        "duration": round(info.duration, 2),
        "segments": parts,
    }


def _error(status: int, message: str, kind: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": kind}}, status_code=status)


async def transcriptions(request: Request):
    if API_KEY and request.headers.get("authorization") != f"Bearer {API_KEY}":
        return _error(401, "Invalid API key.", "authentication_error")
    if int(request.headers.get("content-length") or 0) > MAX_BYTES + 64 * 1024:
        return _error(413, "File too large.")
    form = await request.form(max_files=1, max_fields=10)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return _error(400, "Missing file.")
    data = await upload.read()
    if not data:
        return _error(400, "Empty file.")
    if len(data) > MAX_BYTES:
        return _error(413, "File too large.")
    language = (form.get("language") or "").strip().lower() or None
    if language and language not in LANGUAGES:
        language = None
    picked = _pick(language)
    if picked is None:
        return _error(503, "The speech model is still loading.", "server_error")
    name, model = picked
    prompt = (form.get("prompt") or "").strip()[:PROMPT_MAX]
    response_format = (form.get("response_format") or "json").strip()

    suffix = os.path.splitext(getattr(upload, "filename", "") or "")[1][:8] or ".audio"
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(data)
        handle.flush()
        started = time.monotonic()
        async with _slots:
            try:
                result = await asyncio.to_thread(_transcribe, model, handle.name, language, prompt)
            except TooLong:
                return _error(413, f"Audio longer than {MAX_SECONDS} seconds.")
            except Exception as error:  # a file PyAV can't decode, mostly
                log.warning("could not transcribe %s bytes: %s", len(data), error)
                return _error(400, "Could not read the audio.")
    log.info(
        "transcribed %.1f s of %s with %s in %.1f s",
        result["duration"],
        result["language"],
        name,
        time.monotonic() - started,
    )
    if response_format == "text":
        return PlainTextResponse(result["text"])
    if response_format == "verbose_json":
        return JSONResponse({**result, "model": name})
    return JSONResponse({"text": result["text"]})


async def health(request: Request):
    statuses = {name: entry["status"] for name, entry in _models.items()}
    default = statuses[DEFAULT_MODEL]
    body = {"status": default, "model": DEFAULT_MODEL, "models": statuses}
    errors = {name: entry["error"] for name, entry in _models.items() if entry["error"]}
    if errors:
        body["errors"] = errors
    # Only the default model decides health: a language model that failed falls back to it.
    return JSONResponse(body, status_code=503 if default == "error" else 200)


@contextlib.asynccontextmanager
async def lifespan(app):
    # Loading (and the first download) takes a while: /health says "loading" meanwhile.
    threading.Thread(target=_load_all, name="load-models", daemon=True).start()
    yield


app = Starlette(
    routes=[
        Route("/v1/audio/transcriptions", transcriptions, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ],
    lifespan=lifespan,
)
