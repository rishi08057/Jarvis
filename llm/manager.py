"""Ollama client and manager helpers for Jarvis."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _default_headers() -> dict[str, str]:
    return {"Content-Type": "application/json"}


@dataclass(slots=True)
class LLMManager:
    """Manage Ollama requests with retries and graceful failure handling."""

    endpoint: str = "http://localhost:11434"
    model: str = "qwen3:8b"
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 0.25
    opener: Callable[..., Any] = urlopen
    sleeper: Callable[[float], None] = time.sleep
    last_error: str | None = field(default=None, init=False)

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        options: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> str | None:
        """Generate a single completion and return the generated text."""

        payload = self._build_payload(prompt, system=system, model=model, options=options, stream=False)
        response = self._request_json("/api/generate", payload, timeout=timeout)
        if response is None:
            return None

        generated_text = response.get("response")
        if isinstance(generated_text, str):
            self.last_error = None
            return generated_text

        self.last_error = "Ollama response did not include generated text."
        return None

    def stream_generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        options: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Iterator[str]:
        """Yield streamed completion chunks from Ollama."""

        payload = self._build_payload(prompt, system=system, model=model, options=options, stream=True)
        try:
            response = self._open_json_stream("/api/generate", payload, timeout=timeout)
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.last_error = str(exc)
            return

        if response is None:
            return

        try:
            for chunk in response:
                if not chunk:
                    continue
                text = chunk.get("response")
                if isinstance(text, str) and text:
                    yield text
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.last_error = str(exc)

    def health_check(self, timeout: float | None = None) -> bool:
        """Return True when the Ollama service responds successfully."""

        request = Request(
            f"{self.endpoint.rstrip('/')}/api/tags",
            headers=_default_headers(),
            method="GET",
        )
        response = self._perform_request(request, timeout=timeout)
        if response is None:
            return False

        self.last_error = None
        return True

    def _build_payload(
        self,
        prompt: str,
        *,
        system: str | None,
        model: str | None,
        options: Mapping[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": stream,
        }
        if system is not None:
            payload["system"] = system
        if options:
            payload["options"] = dict(options)
        return payload

    def _request_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        timeout: float | None,
    ) -> dict[str, Any] | None:
        request = self._build_request(path, payload)
        response = self._perform_request(request, timeout=timeout)
        if response is None:
            return None

        try:
            raw = response.read()
            if isinstance(raw, bytes):
                decoded = raw.decode("utf-8")
            else:
                decoded = str(raw)
            payload_data = json.loads(decoded)
        except Exception as exc:
            self.last_error = f"Failed to parse Ollama response: {exc}"
            return None

        self.last_error = None
        return payload_data

    def _open_json_stream(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        timeout: float | None,
    ) -> Iterator[dict[str, Any]] | None:
        request = self._build_request(path, payload)
        response = self._perform_request(request, timeout=timeout)
        if response is None:
            return None

        def iterator() -> Iterator[dict[str, Any]]:
            with response:
                for raw_line in response:
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError as exc:
                        self.last_error = f"Failed to parse streamed Ollama chunk: {exc}"
                        return

        self.last_error = None
        return iterator()

    def _build_request(self, path: str, payload: Mapping[str, Any]) -> Request:
        body = json.dumps(payload).encode("utf-8")
        return Request(
            f"{self.endpoint.rstrip('/')}{path}",
            data=body,
            headers=_default_headers(),
            method="POST",
        )

    def _perform_request(self, request: Request, *, timeout: float | None) -> Any | None:
        timeout_value = self.timeout if timeout is None else timeout
        attempts = max(1, self.max_retries)

        for attempt in range(1, attempts + 1):
            try:
                response = self.opener(request, timeout=timeout_value)
                return response
            except HTTPError as exc:
                self.last_error = f"HTTP {exc.code}: {exc.reason}"
                if exc.code < 500 or attempt == attempts:
                    return None
            except (URLError, TimeoutError, OSError) as exc:
                self.last_error = str(exc)
                if attempt == attempts:
                    return None

            self.sleeper(self.retry_delay * attempt)

        return None