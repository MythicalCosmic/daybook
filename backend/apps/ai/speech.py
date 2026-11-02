"""Speech to text for voice task drafts (docs/ai-contract §1).

Claude takes text and images, not audio, so a voice message is written down by a separate,
pluggable service first, and the text goes on to `apps.ai.drafting`:

- `openai_compatible` (whenever `AI_SPEECH_URL` is set): `POST {AI_SPEECH_URL}/audio/
  transcriptions` with the file as multipart `file` and the fields `model` (`AI_SPEECH_MODEL`),
  `language` (the author's uz, ru or en, always sent when known: the local service picks its
  Uzbek model for "uz"; left out when unknown), `prompt` (a plain comma-separated vocabulary
  hint without a label: the people's names and positions, the company's name, pharmacy words
  in that language; at most 600 characters) and `response_format=verbose_json`;
  `Authorization: Bearer {AI_SPEECH_API_KEY}` only when a key is set; `AI_SPEECH_TIMEOUT`
  seconds (90 by default: a CPU service needs 10-25 s per 10 s of speech). The answer is
  `{"text", "language", "duration", "segments"?}`. One protocol serves the local Whisper service
  (deploy/stt, `http://stt:8000/v1`), OpenAI (`https://api.openai.com/v1`, gpt-4o-transcribe)
  and Groq (`https://api.groq.com/openai/v1`, whisper-large-v3).
- `fake` (`AI_FAKE=true` and no `AI_SPEECH_URL`): a canned instruction in the author's language
  that names two of the author's real people, so drafts look real in development and demos.
- none: `status()` is "not_configured" and voice is unavailable (typed text still works).

OpenAI's own models (`gpt-*`) answer plain JSON only and don't take Uzbek by its code ("Language
code 'uz' is not recognized. Try adding the language name to your prompt", 2026-11-02): they get
`response_format=json`, and for Uzbek the hint starts with the language's name instead of a
`language` field. `AI_SPEECH_MODELS_BY_LANGUAGE` picks a model per language there (Uzbek needs
gpt-4o-transcribe; mini can't write it). When the service fails, `AI_SPEECH_FALLBACK_URL` (the
server's own Whisper) gets the recording instead.

Failures raise `SpeechError` ("speech_unavailable": down, misconfigured, too slow, an answer that
makes no sense), `SpeechBusy` (a 503 while the service loads its models: the job tries again in
a while) or `AudioUnreadable` ("audio_unreadable": the service couldn't read the file); the
draft records the code. Unknown keys of the answer (the local service adds "model") are
ignored. Neither the audio nor the transcript is ever logged.
"""

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass

import httpx2  # the anthropic SDK's HTTP library (1.x); never the `httpx` package
from django.conf import settings

logger = logging.getLogger(__name__)

PROMPT_LIMIT = 600
LANGUAGES = ("uz", "ru", "en")
# What a service answers when the file itself is the problem: unreadable, too big, wrong type.
UNREADABLE_STATUSES = frozenset({400, 413, 415, 422})
# Whisper's verbose_json names the language in full ("uzbek"); other services send the code.
LANGUAGE_NAMES = {
    "uzbek": "uz",
    "russian": "ru",
    "english": "en",
    "kazakh": "kk",
    "tajik": "tg",
    "turkmen": "tk",
    "turkish": "tr",
    "azerbaijani": "az",
    "ukrainian": "uk",
    "korean": "ko",
    "chinese": "zh",
    "arabic": "ar",
    "german": "de",
}
# Words a pharmacy team says that a speech model may not expect, in the speaker's language
# only: words of another language in the hint leak into the transcript (tested on deploy/stt).
PHARMACY_WORDS = {
    "uz": ("muzlatgich", "harorat", "kassa", "dori", "sklad", "retsept", "yaroqlilik muddati"),
    "ru": ("холодильник", "температура", "касса", "склад", "рецепт", "срок годности"),
    "en": ("fridge", "temperature", "cash register", "stock", "prescription", "expiry date"),
}
# The service is starting (loading its models): try again a little later.
BUSY_STATUSES = frozenset({503})
# For a hosted OpenAI model, a language it doesn't know by its code is named at the start of the
# hint instead, in that language.
HOSTED_LANGUAGE_HINTS = {"uz": "O‘zbekcha ovozli xabar."}


class SpeechError(Exception):
    """The speech service can't be used right now (down, misconfigured, too slow, nonsense)."""

    code = "speech_unavailable"


class AudioUnreadable(SpeechError):
    """The service couldn't read the file (HTTP 400, 413, 415 or 422)."""

    code = "audio_unreadable"


class SpeechBusy(SpeechError):
    """The service is starting up (503 while its models load): worth trying again soon."""


@dataclass(frozen=True)
class Transcript:
    text: str  # stripped; "" when nothing was heard
    language: str  # "uz", "ru", "en", another two-letter code, or "" when unknown
    duration: float | None


@dataclass(frozen=True)
class Service:
    """One place a recording can be written down."""

    url: str
    key: str
    model: str
    timeout: float
    name: str  # "main" or "fallback", for the logs


def services(language: str | None) -> list[Service]:
    """Where a recording goes, in order: the configured service with its model for `language`,
    then the fallback when one is set."""
    models = settings.AI_SPEECH_MODELS_BY_LANGUAGE or {}
    found = [
        Service(
            settings.AI_SPEECH_URL,
            settings.AI_SPEECH_API_KEY,
            models.get(language or "", settings.AI_SPEECH_MODEL),
            settings.AI_SPEECH_TIMEOUT,
            "main",
        )
    ]
    fallback = settings.AI_SPEECH_FALLBACK_URL
    if fallback and fallback.rstrip("/") != settings.AI_SPEECH_URL.rstrip("/"):
        found.append(
            Service(
                fallback,
                "",
                settings.AI_SPEECH_FALLBACK_MODEL,
                settings.AI_SPEECH_FALLBACK_TIMEOUT,
                "fallback",
            )
        )
    return found


def provider() -> str:
    """ "openai_compatible", "fake" or "none"."""
    if settings.AI_SPEECH_URL:
        return "openai_compatible"
    if settings.AI_FAKE:
        return "fake"
    return "none"


def status() -> str:
    """ "ready" (a service is set), "fake" (AI_FAKE without one) or "not_configured"."""
    return {"openai_compatible": "ready", "fake": "fake", "none": "not_configured"}[provider()]


def vocabulary(company_name: str, people: Iterable[tuple[str, str]], language: str = "uz") -> str:
    """The `prompt` hint, a plain comma-separated list without any label (a label leaks into the
    transcript): the people's "First Last" names and their positions (each once), the company's
    name, then a few pharmacy words in `language` only; cut between items to PROMPT_LIMIT, so a
    name is never cut."""
    words = PHARMACY_WORDS.get(language, PHARMACY_WORDS["uz"])
    items: list[str] = []
    seen: set[str] = set()
    for item in (*(part for person in people for part in person), company_name, *words):
        item = " ".join((item or "").split())
        if item and item.lower() not in seen:
            seen.add(item.lower())
            items.append(item)
    if not items:
        return ""
    if len(items[0]) > PROMPT_LIMIT:  # an odd name longer than the whole hint
        return _cut(items[0], PROMPT_LIMIT)
    text = items[0]
    for item in items[1:]:
        if len(text) + 2 + len(item) > PROMPT_LIMIT:
            break
        text = f"{text}, {item}"
    return text


def fake_instruction(language: str, names: list[str]) -> str:
    """What the fake service "hears": a fridge check with a photo for the first name and a cash
    count for the second, in `language` (Uzbek unless ru or en); without names, the first task
    for oneself."""
    language = language if language in LANGUAGES else "uz"
    names = [name.strip() for name in names if name and name.strip()][:2]
    if language == "ru":
        names = [_to_cyrillic(name) for name in names]
    first, second, alone = _FAKE[language]
    if not names:
        return alone
    text = first.format(name=names[0])
    if len(names) > 1:
        text += " " + second.format(name=names[1])
    return text


_FAKE = {
    "uz": (
        "{name}, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor.",
        "{name}, bugun kechqurun kassani sanab qo‘y.",
        "Ertaga soat 10 gacha muzlatgich haroratini tekshirish, rasm bilan.",
    ),
    "ru": (
        "{name}, завтра до 10 часов проверь температуру в холодильнике и пришли фото.",
        "{name}, сегодня вечером пересчитай кассу.",
        "Завтра до 10 часов проверить температуру в холодильнике, с фото.",
    ),
    "en": (
        "{name}, check the fridge temperature by 10 tomorrow and send a photo.",
        "{name}, count the cash this evening.",
        "Check the fridge temperature by 10 tomorrow, with a photo.",
    ),
}


def transcribe(
    audio: bytes,
    *,
    filename: str,
    content_type: str,
    language: str | None,
    prompt: str = "",
    names: Iterable[str] = (),
    seconds: float | None = None,
) -> Transcript:
    """Write down what is said in `audio`. `language` is the author's language as a hint;
    `names` are only for the fake service, `seconds` the length the sender reported."""
    match provider():
        case "fake":
            lang = language if language in LANGUAGES else "uz"
            return Transcript(fake_instruction(lang, list(names)), lang, seconds)
        case "none":
            raise SpeechError("No speech service is set up (AI_SPEECH_URL).")
    chain = services(language)
    for service in chain:
        try:
            return _openai_compatible(
                service,
                audio,
                filename=filename,
                content_type=content_type,
                language=language,
                prompt=prompt,
            )
        except SpeechError as exc:
            if service is chain[-1]:
                raise
            logger.warning("Speech service %s failed (%s); trying the next", service.name, exc)
    raise AssertionError("unreachable")  # services() always names one


def _openai_compatible(
    service: Service,
    audio: bytes,
    *,
    filename: str,
    content_type: str,
    language: str | None,
    prompt: str,
) -> Transcript:
    url = service.url.rstrip("/") + "/audio/transcriptions"
    hosted = service.model.startswith("gpt-")
    fields = {"model": service.model, "response_format": "json" if hosted else "verbose_json"}
    hint = ""
    if language in LANGUAGES:
        if hosted and language in HOSTED_LANGUAGE_HINTS:
            hint = HOSTED_LANGUAGE_HINTS[language]
        else:
            fields["language"] = language
    if prompt := _cut(" ".join(f"{hint} {prompt}".split()), PROMPT_LIMIT):
        fields["prompt"] = prompt
    headers = {"Authorization": f"Bearer {service.key}"} if service.key else {}
    started = time.monotonic()
    try:
        with _client() as client:
            response = client.post(
                url,
                data=fields,
                files={"file": (filename, audio, content_type)},
                headers=headers,
                timeout=service.timeout,
            )
    except httpx2.TimeoutException as exc:
        logger.warning("Speech service %s timed out after %s ms", service.name, _since(started))
        raise SpeechError("The speech service took too long.") from exc
    except httpx2.HTTPError as exc:
        logger.warning("Speech service %s unreachable: %s", service.name, type(exc).__name__)
        raise SpeechError("The speech service can't be reached.") from exc
    logger.info(
        "Speech service %s (%s) answered %s in %s ms for %s bytes",
        service.name,
        service.model,
        response.status_code,
        _since(started),
        len(audio),
    )
    if response.status_code in UNREADABLE_STATUSES:
        raise AudioUnreadable(f"The speech service couldn't read the file: {response.status_code}")
    if response.status_code in BUSY_STATUSES:
        raise SpeechBusy("The speech service is starting.")
    if response.status_code != 200:
        raise SpeechError(f"The speech service answered {response.status_code}.")
    try:
        body = response.json()
    except ValueError as exc:
        raise SpeechError("The speech service's answer isn't JSON.") from exc
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        raise SpeechError("The speech service's answer has no text.")
    heard = _language_code(body.get("language"))
    return Transcript(
        text=body["text"].strip(),
        # OpenAI's plain JSON names no language: the one asked for is what was heard.
        language=heard or (language if hosted and language in LANGUAGES else ""),
        duration=_seconds(body.get("duration")),
    )


def _client() -> httpx2.Client:
    """The HTTP client of one transcription (tests give it a mock transport)."""
    return httpx2.Client()


def _language_code(value) -> str:
    """ "uz" for "uzbek", "uz", "UZ" or "uz-UZ"; "" for anything unknown."""
    if not isinstance(value, str):
        return ""
    word = value.strip().lower()
    if word in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[word]
    if len(word) == 2 and word.isalpha():
        return word
    if len(word) > 2 and word[:2].isalpha() and word[2] in "-_":
        return word[:2]
    return ""


def _seconds(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value is not None else None
    except TypeError, ValueError:
        return None


def _since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _cut(text: str, limit: int) -> str:
    """`text` up to `limit` characters, cut after a whole item or word."""
    if len(text) <= limit:
        return text
    head = text[: limit + 1]
    for separator in (", ", " "):
        if (at := head.rfind(separator)) > 0:
            return head[:at].rstrip(" ,")
    return text[:limit]


# Uzbek Latin to Cyrillic as Russian writes Uzbek names (o‘ as a plain u, g‘ as a plain g, q as
# k): good enough for a canned demo sentence.
_APOSTROPHES = "‘’ʻʼ'`"
_PAIRS = {
    "sh": "ш",
    "ch": "ч",
    "yo": "ё",
    "yu": "ю",
    "ya": "я",
    "ye": "е",
    "ts": "ц",
    "kh": "х",
}
_LETTERS = {
    "a": "а",
    "b": "б",
    "c": "к",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "г",
    "h": "х",
    "i": "и",
    "j": "ж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "к",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "х",
    "y": "й",
    "z": "з",
}


def _to_cyrillic(name: str) -> str:
    out: list[str] = []
    index = 0
    lower = name.lower()
    while index < len(name):
        pair = lower[index : index + 2]
        if len(pair) == 2 and pair[0] in "og" and pair[1] in _APOSTROPHES:
            letter, step = ("у" if pair[0] == "o" else "г"), 2  # o‘ and g‘
        elif pair in _PAIRS:
            letter, step = _PAIRS[pair], 2
        elif lower[index] in _APOSTROPHES:
            letter, step = "", 1
        elif lower[index] == "e" and (index == 0 or not lower[index - 1].isalpha()):
            letter, step = "э", 1  # Elmurod: Элмурод
        else:
            letter, step = _LETTERS.get(lower[index], name[index]), 1
        if letter and name[index].isupper():
            letter = letter[0].upper() + letter[1:]
        out.append(letter)
        index += step
    return "".join(out)
