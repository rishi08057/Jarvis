from __future__ import annotations

import unittest
from unittest.mock import patch

from ui import ChatResponse, ChatSession, ConversationTurn, TerminalChatApp


class FakeLLMManager:
    def __init__(self, *, stream_chunks: list[str] | None = None, response_text: str | None = None, error: str | None = None) -> None:
        self.stream_chunks = list(stream_chunks or [])
        self.response_text = response_text
        self.last_error = error
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, system: str | None = None, model: str | None = None, options=None, timeout=None):
        _ = prompt
        _ = (system, model, options, timeout)
        self.prompts.append(prompt)
        return self.response_text

    def stream_generate(self, prompt: str, *, system: str | None = None, model: str | None = None, options=None, timeout=None):
        _ = prompt
        _ = (system, model, options, timeout)
        self.prompts.append(prompt)
        for chunk in self.stream_chunks:
            yield chunk


class FakeConsole:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = list(inputs)
        self.printed: list[object] = []
        self.cleared = 0

    def input(self, _prompt: str) -> str:
        if not self.inputs:
            raise EOFError
        return self.inputs.pop(0)

    def print(self, *values, **_kwargs) -> None:
        if len(values) == 1:
            self.printed.append(values[0])
        else:
            self.printed.append(values)

    def clear(self) -> None:
        self.cleared += 1


class ChatSessionTests(unittest.TestCase):
    def test_stream_response_measures_each_request_independently(self) -> None:
        llm = FakeLLMManager(stream_chunks=["hello"])
        session = ChatSession(llm=llm)

        with patch("ui.session.perf_counter", side_effect=[10.0, 10.25, 20.0, 20.5]):
            first = session.stream_response("one")
            second = session.stream_response("two")

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(first.elapsed_seconds, 0.25)
        self.assertEqual(second.elapsed_seconds, 0.5)

    def test_generate_response_measures_each_request_independently(self) -> None:
        llm = FakeLLMManager(response_text="hello")
        session = ChatSession(llm=llm)

        with patch("ui.session.perf_counter", side_effect=[30.0, 30.4]):
            response = session.generate_response("hi")

        self.assertTrue(response.success)
        self.assertAlmostEqual(response.elapsed_seconds, 0.4, places=2)

    def test_stream_response_updates_history_and_tracks_timing(self) -> None:
        llm = FakeLLMManager(stream_chunks=["hel", "lo"])
        session = ChatSession(llm=llm)

        chunks: list[str] = []
        response = session.stream_response("hello?", on_chunk=chunks.append)

        self.assertTrue(response.success)
        self.assertEqual(response.message, "hello")
        self.assertEqual(chunks, ["hel", "lo"])
        self.assertEqual(session.history, [
            ConversationTurn(role="user", content="hello?"),
            ConversationTurn(role="assistant", content="hello"),
        ])
        self.assertGreaterEqual(response.elapsed_seconds, 0.0)

    def test_build_prompt_includes_history(self) -> None:
        llm = FakeLLMManager(stream_chunks=["ok"])
        session = ChatSession(llm=llm)
        session.history.extend([
            ConversationTurn(role="user", content="First"),
            ConversationTurn(role="assistant", content="Second"),
        ])

        prompt = session.build_prompt("Third")

        self.assertIn("User: First", prompt)
        self.assertIn("Assistant: Second", prompt)
        self.assertTrue(prompt.strip().endswith("Assistant:"))

    def test_clear_removes_history(self) -> None:
        llm = FakeLLMManager(stream_chunks=["ok"])
        session = ChatSession(llm=llm)
        session.history.append(ConversationTurn(role="user", content="Hello"))

        session.clear()

        self.assertEqual(session.history, [])


class TerminalChatAppTests(unittest.TestCase):
    def test_clear_and_exit_commands(self) -> None:
        llm = FakeLLMManager(stream_chunks=["unused"])
        session = ChatSession(llm=llm)
        session.history.append(ConversationTurn(role="user", content="Keep?"))
        console = FakeConsole(["clear", "exit"])
        app = TerminalChatApp(session=session, assistant_name="Jarvis", console=console)

        exit_code = app.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(session.history, [])
        self.assertEqual(console.cleared, 1)

    def test_single_message_mode_returns_response(self) -> None:
        llm = FakeLLMManager(stream_chunks=["hello"])
        session = ChatSession(llm=llm)

        response = session.stream_response("Hi")

        self.assertTrue(response.success)
        self.assertIsInstance(response, ChatResponse)
        self.assertEqual(llm.prompts[0].splitlines()[-2], "User: Hi")

    def test_streamed_response_is_rendered_once(self) -> None:
        class FakeController:
            def __init__(self) -> None:
                self.session = ChatSession(llm=FakeLLMManager())

            def handle(self, message: str, *, on_chunk=None, timeout=None):
                _ = (message, timeout)
                if on_chunk is not None:
                    on_chunk("controller-response")
                return ChatResponse(message="controller-response", elapsed_seconds=0.12, success=True)

        console = FakeConsole(["analyze repository", "exit"])
        app = TerminalChatApp(session=ChatSession(llm=FakeLLMManager()), controller=FakeController(), console=console)

        with patch.dict("sys.modules", {"rich": None}):
            exit_code = app.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(console.printed.count("controller-response"), 1)


if __name__ == "__main__":
    unittest.main()