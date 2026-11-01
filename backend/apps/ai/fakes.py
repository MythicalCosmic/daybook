"""A scripted stand-in for the Anthropic client, for tests (docs/PLAN-OWNER.md §8.9).

    fake = FakeAnthropic()
    fake.script(fake.json({"drafts": [...], "questions": []}))
    monkeypatch.setattr("apps.ai.client.get_client", lambda: fake)
    ...
    [request] = fake.requests            # every request exactly as the SDK would send it

Responses are real SDK types (`BetaMessage.model_validate`), so the code under test reads
them as it reads Anthropic's. A scripted exception is raised instead of answering.
"""

import itertools
import json

import anthropic
import httpx2
from anthropic.types.beta import BetaMessage

DEFAULT_MODEL = "claude-opus-5-5"
_ids = itertools.count(1)


class _Messages:
    def __init__(self, fake: FakeAnthropic):
        self._fake = fake

    def create(self, **request):
        return self._fake._answer(request)


class _Beta:
    def __init__(self, fake: FakeAnthropic):
        self.messages = _Messages(fake)


class FakeAnthropic:
    def __init__(self):
        self.requests: list[dict] = []
        self._script: list = []
        self.beta = _Beta(self)
        self.messages = _Messages(self)

    def script(self, *answers) -> FakeAnthropic:
        """Queue answers (BetaMessage or exceptions), used in order, one per request."""
        self._script.extend(answers)
        return self

    def _answer(self, request: dict):
        self.requests.append(request)
        if not self._script:
            raise AssertionError("FakeAnthropic got a request nobody scripted.")
        answer = self._script.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    # Builders ----------------------------------------------------------------------------------

    @staticmethod
    def message(
        content: list[dict],
        *,
        stop_reason: str = "end_turn",
        model: str = DEFAULT_MODEL,
        input_tokens: int = 1200,
        output_tokens: int = 300,
        cache_read: int = 0,
        iterations: list[dict] | None = None,
        stop_details: dict | None = None,
    ) -> BetaMessage:
        number = next(_ids)
        message = BetaMessage.model_validate(
            {
                "id": f"msg_fake_{number}",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "stop_details": stop_details,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": 0,
                    "iterations": iterations,
                },
            }
        )
        message._request_id = f"req_fake_{number}"
        return message

    @classmethod
    def json(cls, data, **kwargs) -> BetaMessage:
        """A structured answer: a thinking block (empty, as with display omitted) and the JSON."""
        thinking = {"type": "thinking", "thinking": "", "signature": "sig"}
        text = {"type": "text", "text": json.dumps(data, ensure_ascii=False)}
        return cls.message([thinking, text], **kwargs)

    @classmethod
    def text(cls, text: str, **kwargs) -> BetaMessage:
        return cls.message([{"type": "text", "text": text}], **kwargs)

    @classmethod
    def refusal(cls, category: str | None = "cyber", **kwargs) -> BetaMessage:
        details = {"type": "refusal", "category": category, "explanation": None}
        return cls.message([], stop_reason="refusal", stop_details=details, **kwargs)

    @classmethod
    def truncated(cls, **kwargs) -> BetaMessage:
        partial = [{"type": "text", "text": '{"drafts": [{"ti'}]
        return cls.message(partial, stop_reason="max_tokens", **kwargs)

    @staticmethod
    def status_error(status: int = 529) -> anthropic.APIStatusError:
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx2.Response(status, request=request, json={"type": "error"})
        error = {500: anthropic.InternalServerError, 429: anthropic.RateLimitError}.get(
            status, anthropic.APIStatusError
        )
        return error("fake error", response=response, body=None)

    @staticmethod
    def connection_error() -> anthropic.APIConnectionError:
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        return anthropic.APITimeoutError(request=request)
