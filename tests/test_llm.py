from __future__ import annotations

import json
import unittest
from urllib.error import URLError

from llm import LLMManager


class FakeResponse:
    def __init__(self, body: bytes | None = None, lines: list[bytes] | None = None) -> None:
        self._body = body or b""
        self._lines = list(lines or [])

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._body

    def __iter__(self):
        return iter(self._lines)


class FakeOllamaOpener:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class LLMManagerTests(unittest.TestCase):
    def test_generate_uses_default_model_and_returns_text(self) -> None:
        response = FakeResponse(body=json.dumps({"response": "hello"}).encode("utf-8"))
        opener = FakeOllamaOpener([response])
        manager = LLMManager(opener=opener, sleeper=lambda _: None)

        result = manager.generate("hi")

        self.assertEqual(result, "hello")
        self.assertIsNone(manager.last_error)
        self.assertEqual(len(opener.requests), 1)
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, "http://localhost:11434/api/generate")
        self.assertEqual(timeout, 30.0)
        self.assertEqual(json.loads(request.data.decode("utf-8"))["model"], "qwen3:8b")

    def test_stream_generate_yields_chunks(self) -> None:
        response = FakeResponse(
            lines=[
                b'{"response":"hel","done":false}\n',
                b'{"response":"lo","done":true}\n',
            ]
        )
        opener = FakeOllamaOpener([response])
        manager = LLMManager(opener=opener, sleeper=lambda _: None)

        chunks = list(manager.stream_generate("hi"))

        self.assertEqual(chunks, ["hel", "lo"])
        self.assertIsNone(manager.last_error)
        self.assertEqual(json.loads(opener.requests[0][0].data.decode("utf-8"))["stream"], True)

    def test_generate_retries_transient_failures(self) -> None:
        response = FakeResponse(body=json.dumps({"response": "retry ok"}).encode("utf-8"))
        opener = FakeOllamaOpener([URLError("temporary"), response])
        manager = LLMManager(opener=opener, sleeper=lambda _: None, max_retries=2)

        result = manager.generate("hi")

        self.assertEqual(result, "retry ok")
        self.assertEqual(len(opener.requests), 2)
        self.assertIsNone(manager.last_error)

    def test_failure_is_graceful(self) -> None:
        generate_opener = FakeOllamaOpener([URLError("down"), URLError("still down")])
        manager = LLMManager(opener=generate_opener, sleeper=lambda _: None, max_retries=2)

        result = manager.generate("hi")
        health_manager = LLMManager(opener=FakeOllamaOpener([URLError("still down")]), sleeper=lambda _: None, max_retries=1)
        health = health_manager.health_check()

        self.assertIsNone(result)
        self.assertFalse(health)
        self.assertIsInstance(manager.last_error, str)
        self.assertIsInstance(health_manager.last_error, str)


if __name__ == "__main__":
    unittest.main()