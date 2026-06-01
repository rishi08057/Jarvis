"""Rich terminal chat interface for Jarvis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agents import AgentController

from .session import ChatSession


@dataclass(slots=True)
class TerminalChatApp:
    """Drive the interactive terminal experience.

    The session layer is kept separate so the same conversation logic can be reused
    by a future web UI without changing the LLM integration.
    """

    session: ChatSession
    controller: AgentController | None = None
    assistant_name: str = "Jarvis"
    console: object | None = None
    input_provider: Callable[[str], str] | None = None
    on_turn: Callable[[str, str | None, float, bool], None] | None = None

    def run(self) -> int:
        console = self.console or self._create_console()
        input_provider = self.input_provider or console.input  # type: ignore[assignment]

        def show_banner() -> None:
            rich_console, _, _, rich_panel, rich_text = self._load_rich_primitives()
            if rich_console is None:
                console.print(f"{self.assistant_name}")
                console.print("Terminal chat powered by Ollama")
                return

            banner = rich_text.Text()
            banner.append(f"{self.assistant_name}\n", style="bold bright_cyan")
            banner.append("Terminal chat powered by Ollama", style="dim")
            console.print(rich_panel.Panel(banner, border_style="bright_cyan"))

        show_banner()
        self._show_help(console)

        while True:
            try:
                user_input = input_provider("[bold cyan]You[/bold cyan] > ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Session closed.[/dim]")
                return 0

            if not user_input:
                continue

            command = user_input.lower()
            if command in {"exit", "quit"}:
                console.print("[dim]Goodbye.[/dim]")
                return 0

            if command == "clear":
                if self.controller is not None:
                    self.controller.clear_history()
                else:
                    self.session.clear()
                if hasattr(console, "clear"):
                    console.clear()  # type: ignore[call-arg]
                show_banner()
                self._show_help(console)
                continue

            self._render_exchange(console, user_input)

    def _render_exchange(self, console: object, message: str) -> None:
        assistant_label = f"{self.assistant_name} >"
        rich_console, rich_live, rich_markdown, rich_panel, rich_text = self._load_rich_primitives()
        streamed_output = False

        if rich_console is None:
            def on_chunk(chunk: str) -> None:
                nonlocal streamed_output
                streamed_output = True
                console.print(chunk, end="")

            console.print(f"{assistant_label}")
            response = self._handle_message(message, on_chunk=on_chunk)
            console.print("")
        else:
            live_text = rich_text.Text()

            def on_chunk(chunk: str) -> None:
                nonlocal streamed_output
                streamed_output = True
                live_text.append(chunk)
                live.update(
                    rich_panel.Panel(
                        rich_console.Group(rich_markdown.Markdown(message), rich_text.Text(str(live_text))),
                        title=assistant_label,
                    )
                )

            with rich_live.Live(console=console, refresh_per_second=30, transient=True) as live:
                response = self._handle_message(message, on_chunk=on_chunk)
                live.update(
                    rich_panel.Panel(
                        rich_console.Group(rich_markdown.Markdown(message), rich_text.Text(str(live_text))),
                        title=assistant_label,
                    )
                )

        if response.success:
            if not streamed_output:
                if rich_console is None:
                    console.print(response.message or "")
                else:
                    console.print(rich_panel.Panel(rich_markdown.Markdown(response.message or ""), title=assistant_label))

            if rich_console is None:
                console.print(f"Response time: {response.elapsed_seconds:.2f}s")
            else:
                console.print(f"[dim]Response time: {response.elapsed_seconds:.2f}s[/dim]")
        else:
            if rich_console is None:
                console.print(f"Response failed: {response.error or 'Unknown error'}")
                console.print(f"Elapsed: {response.elapsed_seconds:.2f}s")
            else:
                console.print(f"[red]Response failed:[/red] {response.error or 'Unknown error'}")
                console.print(f"[dim]Elapsed: {response.elapsed_seconds:.2f}s[/dim]")

        if self.on_turn is not None:
            self.on_turn(message, response.message, response.elapsed_seconds, response.success)

    def _handle_message(self, message: str, *, on_chunk: Callable[[str], None] | None = None):
        if self.controller is not None:
            return self.controller.handle(message, on_chunk=on_chunk)
        return self.session.stream_response(message, on_chunk=on_chunk)

    def _show_help(self, console: object) -> None:
        console.print("[dim]Commands: clear | exit | quit | What tools are available?[/dim]")

    def _create_console(self) -> object:
        rich_console, *_ = self._load_rich_primitives()
        if rich_console is None:
            return self._fallback_console()

        return rich_console.Console()

    def _load_rich_primitives(self):
        try:
            from rich import console as rich_console
            from rich import live as rich_live
            from rich import markdown as rich_markdown
            from rich import panel as rich_panel
            from rich import text as rich_text
        except ImportError:
            return None, None, None, None, None

        return rich_console, rich_live, rich_markdown, rich_panel, rich_text

    def _fallback_console(self) -> object:
        class _Console:
            def input(self, prompt: str) -> str:
                return input(prompt)

            def print(self, *values, **kwargs) -> None:
                end = kwargs.get("end", "\n")
                text = " ".join(str(value) for value in values)
                print(text, end=end)

            def clear(self) -> None:
                print("\033[2J\033[H", end="")

        return _Console()