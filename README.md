# Jarvis

Jarvis is a production-ready Python 3.12 project scaffold for a local AI assistant. It uses a modular layout so the assistant logic, tools, memory, security, logging, and UI layers can evolve independently.

## Structure

- `main.py` is the application entrypoint.
- `config/` loads and validates runtime settings.
- `agents/` defines the agent contract and registry.
- `tools/` defines reusable tool interfaces.
- `memory/` stores local assistant memory on disk.
- `security/` contains input and path safety helpers.
- `logs/` configures application logging.
- `ui/` exposes the command-line interface.
- `tests/` contains validation tests.

## Requirements

- Python 3.12
- `python-dotenv`
- `pytest`

## Quick Start

1. Create and activate a Python 3.12 virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and adjust values as needed.
4. Run the project:

   ```bash
   python main.py --show-config
   ```

## Environment Variables

- `JARVIS_APP_NAME`: Display name for the application.
- `JARVIS_ENVIRONMENT`: Runtime mode such as `development` or `production`.
- `JARVIS_LOG_LEVEL`: Logging level.
- `JARVIS_ASSISTANT_NAME`: Assistant identity shown in the UI.
- `JARVIS_AI_PROVIDER`: Local model provider name.
- `JARVIS_AI_MODEL`: Default model name.
- `JARVIS_AI_ENDPOINT`: Local model endpoint.
- `JARVIS_ENABLE_FILE_LOGGING`: Enable rotating file logs.
- `JARVIS_LOGS_DIR`: Folder for log files.
- `JARVIS_MEMORY_DIR`: Folder for stored assistant memory.

## Design Notes

The scaffold is intentionally small and extensible:

- Settings are centralized in `config/`.
- Logging is isolated in `logs/` so it can be swapped without touching business logic.
- Agent and tool contracts are abstract, which makes it easy to add implementations later.
- Security helpers live separately to keep input and path validation explicit.
- Tool execution always passes through the security middleware for permission checks, approval handling, and audit logging.

## Testing

Run the test suite with:

```bash
python -m pytest
```
