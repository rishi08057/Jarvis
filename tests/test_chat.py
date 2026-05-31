from __future__ import annotations

import unittest

from ui.session import ChatResponse, ChatSession, ConversationTurn
from ui.terminal import TerminalChatApp


class FakeLLMManager:
    def __init__(self, *, stream_chunks: list[str] | None = None, response_text: str | None = None, error: str | None = None) -> None:
        self.stream_chunks = list(stream_chunks or [])
        self.response_text = response_text
        self.last_error = error
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, system: str | None = None, model: str | None = None, options=None, timeout=None):
        self.prompts.append(prompt)
        return self.response_text

    def stream_generate(self, prompt: str, *, system: str | None = None, model: str | None = None, options=None, timeout=None):
        self.prompts.append(prompt)
        for chunk in self.stream_chunks:
            yield chunk


class FakeConsole:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = list(inputs)
        self.printed: list[object] = []
        self.cleared = 0

    def input(self, prompt: str) -> str:
        if not self.inputs:
            raise EOFError
        return self.inputs.pop(0)

    def print(self, *values, **kwargs) -> None:
        if len(values) == 1:
            self.printed.append(values[0])
        else:
            self.printed.append(values)

    def clear(self) -> None:
        self.cleared += 1


class ChatSessionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()