# Copilot Code Review Instructions

These instructions define how GitHub Copilot should review pull requests in this repository.
This is a production-grade Python MCP (Model Context Protocol) proxy server built on `asyncio`,
`anyio`, `Starlette`, `Pydantic`, and `loguru`. Apply the following standards on every review.

---

## Architecture & Design

- This codebase uses an async-first architecture. Flag any blocking I/O calls (e.g., `open()`,
  `requests.get()`, `time.sleep()`) made outside of an executor — suggest `anyio`/`asyncio`
  async equivalents instead.
- All configuration must flow through Pydantic models (`pydantic-settings`). Flag any raw
  `os.environ` or `os.getenv` calls that bypass the settings layer.
- The proxy pattern (aggregating multiple MCP backends into one endpoint) is core to this
  project. Flag any code that tightly couples business logic to a specific backend transport
  (stdio vs SSE) — these should be abstracted.
- Prefer dependency injection over global state. Flag module-level mutable globals.

## Security

- Flag any place where the `--api-key` value could be logged, printed, or exposed in tracebacks.
  API keys must never appear in log output at any level.
- Flag any use of `subprocess` or `shell=True` without explicit input sanitisation.
- Flag any dynamic `eval()`, `exec()`, or `__import__()` usage.
- Flag any file path construction that uses raw string concatenation instead of `pathlib.Path`.
- Ensure all external HTTP calls use `httpx` (the project standard) — flag use of `requests`
  in new code since `requests` is synchronous and not appropriate for this async codebase.

## Code Quality

- All public functions and classes must have docstrings. Flag missing docstrings on anything
  that is not a private helper (`_` prefix).
- Type annotations are required on all function signatures. Flag unannotated parameters or
  return types.
- Pydantic v2 patterns must be used throughout. Flag any Pydantic v1 patterns such as
  `.dict()`, `.parse_obj()`, `validator` decorators — suggest v2 equivalents
  (`.model_dump()`, `.model_validate()`, `@field_validator`).
- Flag bare `except:` or `except Exception:` clauses without logging or re-raising — silent
  swallowing of exceptions is not acceptable in a proxy server.
- Flag any `TODO`, `FIXME`, or `HACK` comments introduced in the PR diff.

## Logging

- This project uses `loguru` exclusively. Flag any use of the stdlib `logging` module in new code.
- Log levels must be appropriate: `DEBUG` for internal state, `INFO` for lifecycle events,
  `WARNING` for recoverable issues, `ERROR` for failures. Flag misuse (e.g., `logger.info`
  for errors).
- Structured context should be bound to loggers using `logger.bind()` — flag unstructured
  f-string log messages that embed multiple variables without binding.

## Performance

- Flag any `asyncio.sleep(0)` or equivalent busy-wait patterns.
- Flag synchronous file I/O inside async functions — suggest `anyio.Path` or
  `asyncio.to_thread` instead.
- Flag large in-memory data structures being passed across async task boundaries without
  consideration for copy cost.

## Testing

- New features or bug fixes must be accompanied by tests in the `tests/` directory.
  Flag PRs that add logic without corresponding test coverage.
- Tests must use `pytest` with `anyio` markers for async tests (`@pytest.mark.anyio`).
  Flag use of `asyncio.run()` inside test functions.

## Dependency Management

- Flag any new dependency added to `main.py` or source files that is not declared in
  `pyproject.toml` and `requirements.txt`.
- Flag pinned dependencies in `pyproject.toml` (e.g., `mcp==1.26.0`) — these should use
  minimum version constraints (`>=`) to remain compatible with Dependabot updates.

---

## Tone & Feedback Style

- Be direct and actionable. Every comment must explain **what** is wrong, **why** it matters
  in the context of this project, and **how** to fix it.
- Prioritise issues by severity: 🔴 blocking (security/correctness) → 🟡 important
  (maintainability/performance) → 🟢 suggestion (style/conventions).
- Do not comment on formatting issues that are handled by a linter/formatter (black, ruff).