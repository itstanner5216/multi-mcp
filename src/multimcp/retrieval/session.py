"""Per-session monotonic tool set management."""

from __future__ import annotations

from .models import RetrievalConfig


class SessionStateManager:
    """Manages per-session active tool sets with monotonic expansion guarantee.

    Once a tool is added to a session, it is never removed for that session's lifetime.
    This prevents hallucination from LLMs that reference previously-seen tools.
    """

    def __init__(self, config: RetrievalConfig) -> None:
        self._config = config
        self._sessions: dict[str, set[str]] = {}

    def get_or_create_session(self, session_id: str) -> set[str]:
        """Initialize a new session with anchor tools, or return existing.

        Returns a copy of the active tool set (callers cannot mutate internal state).
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = set(self._config.anchor_tools)
        return self._sessions[session_id].copy()

    def get_active_tools(self, session_id: str) -> set[str]:
        """Return the set of active tool keys for this session.

        Returns empty set for unknown sessions (safe default).
        """
        session = self._sessions.get(session_id)
        if session is None:
            return set()
        return session.copy()

    def add_tools(self, session_id: str, tool_keys: list[str]) -> list[str]:
        """Add tools to session's active set (monotonic expansion).

        Returns list of newly added keys (empty if all were already present).
        Does nothing for unknown sessions.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return []
        new_keys = [k for k in tool_keys if k not in session]
        session.update(new_keys)
        return new_keys

    def cleanup_session(self, session_id: str) -> None:
        """Remove session state, freeing memory. Safe to call for nonexistent sessions."""
        self._sessions.pop(session_id, None)
