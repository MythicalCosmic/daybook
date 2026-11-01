"""Speech to text (apps.ai.speech): the OpenAI-compatible service against a mock transport, the
fake service and what happens without one. No database, no network."""

import email.parser
import email.policy
import json
import logging

import httpx2
import pytest

from apps.ai import speech
from apps.ai.speech import PROMPT_LIMIT, AudioUnreadable, SpeechError, Transcript

AUDIO = b"OggS\x00\x02" + b"\x00" * 64
UZ_TEXT = "Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor."


@pytest.fixture
def service(settings):
    """A configured speech service; `service.answer(...)` sets what it replies, and
    `service.requests` holds what it got."""
    settings.AI_SPEECH_URL = "http://stt:8000/v1/"
    settings.AI_SPEECH_API_KEY = ""
    settings.AI_SPEECH_MODEL = "large-v3"
    settings.AI_SPEECH_TIMEOUT = 60
    settings.AI_FAKE = False
    return FakeService()


class FakeService:
    def __init__(self):
        self.requests: list[httpx2.Request] = []
        self.reply = httpx2.Response(
            200, json={"text": UZ_TEXT, "language": "uzbek", "duration": 4.2, "segments": []}
        )
        self.error: Exception | None = None

    def answer(self, status=200, **kwargs) -> None:
        self.reply = httpx2.Response(status, **kwargs)

    def fail(self, error: Exception) -> None:
        self.error = error

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture(autouse=True)
def mock_transport(monkeypatch, request):
    """Every HTTP client the module builds talks to the test's FakeService (when there is one);
    without one, building a client fails the test."""
    fake = request.getfixturevalue("service") if "service" in request.fixturenames else None

    def client() -> httpx2.Client:
        if fake is None:
            raise AssertionError("No HTTP request was expected.")
        return httpx2.Client(transport=httpx2.MockTransport(fake.handle))

    monkeypatch.setattr(speech, "_client", client)


def transcribe(**overrides) -> Transcript:
    kwargs = {
        "filename": "voice.ogg",
        "content_type": "audio/ogg",
        "language": "uz",
        "prompt": "Demo Dorixona, Alisher Valiyev, Farmatsevt",
    } | overrides
    return speech.transcribe(AUDIO, **kwargs)


def form(request: httpx2.Request) -> tuple[dict[str, str], dict[str, tuple[str, str, bytes]]]:
    """The multipart fields and files of `request`."""
    body = request.read()
    head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(head + body)
    fields, files = {}, {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        if part.get_filename():
            files[name] = (part.get_filename(), part.get_content_type(), payload)
        else:
            fields[name] = payload.decode()
    return fields, files


# Which provider -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "fake", "provider", "status"),
    [
        ("http://stt:8000/v1", False, "openai_compatible", "ready"),
        ("https://api.openai.com/v1", True, "openai_compatible", "ready"),  # a URL wins
        ("", True, "fake", "fake"),
        ("", False, "none", "not_configured"),
    ],
)
def test_the_provider_follows_the_settings(settings, url, fake, provider, status):
    settings.AI_SPEECH_URL = url
    settings.AI_FAKE = fake

    assert speech.provider() == provider
    assert speech.status() == status


def test_without_a_service_nothing_is_transcribed(settings):
    settings.AI_SPEECH_URL = ""
    settings.AI_FAKE = False

    with pytest.raises(SpeechError) as raised:
        transcribe()

    assert raised.value.code == "speech_unavailable"
    assert not isinstance(raised.value, AudioUnreadable)


def test_the_real_client_is_httpx2(monkeypatch):
    monkeypatch.undo()  # the module's own _client, not the mock

    client = speech._client()

    assert isinstance(client, httpx2.Client)
    client.close()


# The OpenAI-compatible service ----------------------------------------------------------------


def test_the_audio_and_the_hints_are_posted(service):
    result = transcribe()

    [request] = service.requests
    assert request.method == "POST"
    assert str(request.url) == "http://stt:8000/v1/audio/transcriptions"
    fields, files = form(request)
    assert fields == {
        "model": "large-v3",
        "response_format": "verbose_json",
        "language": "uz",
        "prompt": "Demo Dorixona, Alisher Valiyev, Farmatsevt",
    }
    assert files == {"file": ("voice.ogg", "audio/ogg", AUDIO)}
    assert "authorization" not in request.headers  # the local service needs no key
    assert request.extensions["timeout"]["read"] == 60
    assert result == Transcript(text=UZ_TEXT, language="uz", duration=4.2)


def test_the_key_and_the_model_come_from_the_settings(service, settings):
    settings.AI_SPEECH_URL = "https://api.groq.com/openai/v1"
    settings.AI_SPEECH_API_KEY = "gsk-test"
    settings.AI_SPEECH_MODEL = "whisper-large-v3"
    settings.AI_SPEECH_TIMEOUT = 12.5

    transcribe()

    [request] = service.requests
    assert str(request.url) == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer gsk-test"
    assert form(request)[0]["model"] == "whisper-large-v3"
    assert request.extensions["timeout"] == {
        "connect": 12.5,
        "read": 12.5,
        "write": 12.5,
        "pool": 12.5,
    }


@pytest.mark.parametrize("language", [None, "", "de", "uzbek"])
def test_an_unknown_language_is_not_sent(service, language):
    transcribe(language=language)

    assert "language" not in form(service.requests[0])[0]


def test_an_empty_prompt_is_not_sent(service):
    transcribe(prompt="   ")

    assert "prompt" not in form(service.requests[0])[0]


def test_the_prompt_is_cut_on_a_word_boundary(service):
    words = [f"so‘z{index}" for index in range(300)]
    prompt = " ".join(words)

    transcribe(prompt=prompt)

    sent = form(service.requests[0])[0]["prompt"]
    assert len(sent) <= PROMPT_LIMIT
    assert prompt.startswith(sent)
    assert sent.split()[-1] in words  # a whole word, never half of one


@pytest.mark.parametrize(
    ("answered", "code"),
    [
        ("uzbek", "uz"),
        ("Russian", "ru"),
        ("english", "en"),
        ("uz", "uz"),
        ("RU", "ru"),
        ("uz-UZ", "uz"),
        ("ru_RU", "ru"),
        ("kazakh", "kk"),
        ("klingon", ""),
        ("", ""),
        (None, ""),
        (12, ""),
    ],
)
def test_the_language_heard_is_a_code(service, answered, code):
    service.answer(json={"text": "Salom", "language": answered})

    assert transcribe().language == code


@pytest.mark.parametrize(
    ("duration", "seconds"), [(4.2, 4.2), (3, 3.0), ("7.5", 7.5), (None, None), ("x", None)]
)
def test_the_duration_is_read_when_there_is_one(service, duration, seconds):
    service.answer(json={"text": "Salom", "duration": duration})

    assert transcribe().duration == seconds


def test_nothing_heard_is_an_empty_text(service):
    service.answer(json={"text": "  \n ", "language": "uzbek", "duration": 1.0})

    assert transcribe() == Transcript(text="", language="uz", duration=1.0)


@pytest.mark.parametrize(
    "error",
    [
        httpx2.ReadTimeout("slow"),
        httpx2.ConnectTimeout("slow"),
        httpx2.ConnectError("refused"),
        httpx2.RemoteProtocolError("dropped"),
    ],
)
def test_a_slow_or_unreachable_service_is_unavailable(service, error):
    service.fail(error)

    with pytest.raises(SpeechError) as raised:
        transcribe()

    assert raised.value.code == "speech_unavailable"
    assert not isinstance(raised.value, AudioUnreadable)


@pytest.mark.parametrize("status", [400, 413, 415, 422])
def test_a_file_the_service_cannot_read_is_unreadable(service, status):
    service.answer(status, json={"error": {"message": "Invalid file format."}})

    with pytest.raises(AudioUnreadable) as raised:
        transcribe()

    assert raised.value.code == "audio_unreadable"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 502])
def test_other_failures_mean_the_service_is_unavailable(service, status):
    service.answer(status, json={"error": {"message": "nope"}})

    with pytest.raises(SpeechError) as raised:
        transcribe()

    assert raised.value.code == "speech_unavailable"
    assert not isinstance(raised.value, AudioUnreadable | speech.SpeechBusy)


def test_a_service_still_loading_its_models_is_busy(service):
    """deploy/stt answers 503 {"error": …} while its models load: the job tries again later,
    and gives up as speech_unavailable."""
    service.answer(503, json={"error": {"message": "Model is loading"}})

    with pytest.raises(speech.SpeechBusy) as raised:
        transcribe()

    assert raised.value.code == "speech_unavailable"


def test_unknown_keys_in_the_answer_are_ignored(service):
    service.answer(json={"text": "Kassani sana", "language": "uz", "model": "uzbek-ft"})

    assert transcribe().text == "Kassani sana"


@pytest.mark.parametrize(
    "reply",
    [
        {"text": "<html><body>502 Bad Gateway</body></html>"},
        {"content": b"\xff\xfe not json"},
        {"json": ["Alisher"]},
        {"json": {"language": "uzbek"}},
        {"json": {"text": None}},
        {"json": {"text": 42}},
    ],
)
def test_an_answer_that_makes_no_sense_means_unavailable(service, reply):
    service.answer(200, **reply)

    with pytest.raises(SpeechError) as raised:
        transcribe()

    assert raised.value.code == "speech_unavailable"


def test_the_audio_and_the_transcript_never_reach_the_logs(service, caplog):
    secret = "Alisher, seyf kodi 4417, uni hech kimga aytma."
    service.answer(json={"text": secret, "language": "uzbek"})

    with caplog.at_level(logging.DEBUG, logger="apps.ai.speech"):
        transcribe()
        service.answer(415, text=secret)
        with pytest.raises(AudioUnreadable):
            transcribe()

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert logged  # status, latency and size are logged...
    assert secret not in logged  # ...the words are not
    assert "4417" not in logged
    assert "OggS" not in logged


# The vocabulary hint --------------------------------------------------------------------------


def test_the_vocabulary_names_the_people_and_the_company_once():
    people = [
        ("Alisher Valiyev", "Farmatsevt"),
        ("Madina Saidova", "Katta farmatsevt"),
        ("Nigora Azimova", "Farmatsevt"),
        ("Alisher Valiyev", "farmatsevt"),
    ]

    text = speech.vocabulary("Demo Dorixona", people, "uz")

    items = text.split(", ")
    assert items[:5] == [
        "Alisher Valiyev",
        "Farmatsevt",
        "Madina Saidova",
        "Katta farmatsevt",
        "Nigora Azimova",
    ]
    assert "Demo Dorixona" in items
    assert items.count("Alisher Valiyev") == 1
    assert [item.lower() for item in items].count("farmatsevt") == 1
    assert {"muzlatgich", "kassa", "dori", "sklad", "retsept"} <= set(items)
    assert len(text) <= PROMPT_LIMIT


@pytest.mark.parametrize(
    ("language", "expected", "foreign"),
    [
        ("uz", {"muzlatgich", "kassa", "sklad"}, {"холодильник", "fridge"}),
        ("ru", {"холодильник", "касса", "склад", "рецепт"}, {"muzlatgich", "fridge"}),
        ("en", {"fridge", "cash register", "stock"}, {"muzlatgich", "холодильник"}),
        ("de", {"muzlatgich", "kassa"}, {"холодильник", "fridge"}),
    ],
)
def test_the_vocabulary_words_are_in_the_speakers_language_only(language, expected, foreign):
    items = set(speech.vocabulary("Demo Dorixona", [], language).split(", "))

    assert expected <= items
    assert not foreign & items


def test_the_vocabulary_has_no_label():
    """A label ("Ismlar: …") leaked into a Russian transcript as its first word."""
    text = speech.vocabulary("Demo Dorixona", [("Alisher Valiyev", "Farmatsevt")], "ru")

    assert ":" not in text
    assert text.startswith("Alisher Valiyev, Farmatsevt, Demo Dorixona, ")


def test_the_vocabulary_never_cuts_a_name():
    people = [(f"Shahzoda Abdurahmonova{index}", f"Farmatsevt {index}") for index in range(60)]

    text = speech.vocabulary("Demo Dorixona", people)

    assert len(text) <= PROMPT_LIMIT
    whole = {part for person in people for part in person}
    assert all(item in whole for item in text.split(", "))  # only whole names and positions
    assert "muzlatgich" not in text  # the people come first; the words wait for room


def test_an_odd_name_longer_than_the_hint_is_cut_on_a_word():
    name = " ".join(["Dorixona"] * 100)

    text = speech.vocabulary("", [(name, "")])

    assert len(text) <= PROMPT_LIMIT
    assert set(text.split()) == {"Dorixona"}


def test_an_empty_vocabulary_is_only_the_pharmacy_words():
    text = speech.vocabulary("", [])

    assert text.startswith("muzlatgich, harorat, kassa")
    assert len(text) <= PROMPT_LIMIT


# The fake service -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "names", "expected"),
    [
        (
            "uz",
            ["Alisher", "Madina"],
            "Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor. "
            "Madina, bugun kechqurun kassani sanab qo‘y.",
        ),
        (
            "uz",
            ["Alisher"],
            "Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor.",
        ),
        ("uz", [], "Ertaga soat 10 gacha muzlatgich haroratini tekshirish, rasm bilan."),
        (
            "ru",
            ["Alisher", "Madina"],
            "Алишер, завтра до 10 часов проверь температуру в холодильнике и пришли фото. "
            "Мадина, сегодня вечером пересчитай кассу.",
        ),
        (
            "ru",
            ["Jasur"],
            "Жасур, завтра до 10 часов проверь температуру в холодильнике и пришли фото.",
        ),
        ("ru", [], "Завтра до 10 часов проверить температуру в холодильнике, с фото."),
        (
            "en",
            ["Alisher", "Madina"],
            "Alisher, check the fridge temperature by 10 tomorrow and send a photo. "
            "Madina, count the cash this evening.",
        ),
        (
            "en",
            ["Alisher"],
            "Alisher, check the fridge temperature by 10 tomorrow and send a photo.",
        ),
        ("en", [], "Check the fridge temperature by 10 tomorrow, with a photo."),
        (
            "de",  # anything else is Uzbek, as the bots speak it
            ["Alisher", "Madina", "Nigora"],  # only the first two
            "Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor. "
            "Madina, bugun kechqurun kassani sanab qo‘y.",
        ),
    ],
)
def test_the_fake_instruction(language, names, expected):
    assert speech.fake_instruction(language, names) == expected


@pytest.mark.parametrize(
    ("latin", "cyrillic"),
    [
        ("Alisher", "Алишер"),
        ("Bekzod", "Бекзод"),
        ("Dilnoza", "Дилноза"),
        ("Shahzod", "Шахзод"),
        ("Xurshid", "Хуршид"),
        ("Yulduz", "Юлдуз"),
        ("O‘tkir", "Уткир"),
        ("G‘ayrat", "Гайрат"),
        ("Qodir", "Кодир"),
        ("Elmurod", "Элмурод"),
        ("Chori", "Чори"),
    ],
)
def test_names_are_written_in_cyrillic_for_russian(latin, cyrillic):
    assert speech._to_cyrillic(latin) == cyrillic


def test_the_fake_service_hears_the_canned_instruction(settings):
    settings.AI_SPEECH_URL = ""
    settings.AI_FAKE = True

    result = transcribe(language="ru", names=["Alisher", "Madina"], seconds=14)

    assert result == Transcript(
        text=speech.fake_instruction("ru", ["Alisher", "Madina"]), language="ru", duration=14
    )


def test_the_fake_service_speaks_uzbek_without_a_known_language(settings):
    settings.AI_SPEECH_URL = ""
    settings.AI_FAKE = True

    result = transcribe(language=None, names=["Alisher"])

    assert result.language == "uz"
    assert result.text.startswith("Alisher, ertaga")
    assert result.duration is None


def test_the_fake_is_never_used_once_a_service_is_set(service, settings):
    settings.AI_FAKE = True
    service.answer(json={"text": "Haqiqiy matn", "language": "uz"})

    result = transcribe(names=["Alisher", "Madina"])

    assert result.text == "Haqiqiy matn"
    assert len(service.requests) == 1


def test_the_answer_is_json_the_service_wrote(service):
    """A service that streams its JSON with a charset still reads."""
    body = json.dumps({"text": "Kassani sanash", "language": "uz"}, ensure_ascii=False)
    service.answer(
        content=body.encode(), headers={"content-type": "application/json; charset=utf-8"}
    )

    assert transcribe().text == "Kassani sanash"
