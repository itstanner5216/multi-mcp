"""Per-session tool set management with bounded demotion support."""

from __future__ import annotations

from .models import RetrievalConfig


class SessionStateManager:
    """Manages per-session active tool sets with bounded demotion.

    Tools are added to a session via promote() or add_tools() (monotonic expansion).
    Tools may be removed via demote() with hysteresis safety constraints:
    - Tools used in the current turn are never demoted.
    - At most max_per_turn tools are demoted per call (SESSION-03).

    This design prevents hallucination from LLMs referencing recently-seen tools
    while allowing the active set to shrink when tools are no longer relevant.
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

    def promote(self, session_id: str, tool_keys: list[str]) -> list[str]:
        """Add tools to active set at turn boundary. Returns newly promoted keys.

        Does nothing for unknown sessions. Never re-adds already-active tools.
        Callers should use this instead of add_tools() when promoting based on
        ranking signals (SESSION-02).
        """
        session = self._sessions.get(session_id)
        if session is None:
            return []
        new_keys = [k for k in tool_keys if k not in session]
        session.update(new_keys)
        return new_keys

    def demote(
        self,
        session_id: str,
        tool_keys: list[str],
        used_this_turn: set[str],
        max_per_turn: int = 3,
    ) -> list[str]:
        """Remove tools from active set with hysteresis safety constraints.

        Never demotes tools used this turn (used_this_turn).
        Demotes at most max_per_turn tools per call (SESSION-03).
        Returns list of actually demoted tool keys.
        Does nothing for unknown sessions.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return []
        safe_to_demote = [
            k for k in tool_keys if k in session and k not in used_this_turn
        ]
        demoted = safe_to_demote[:max_per_turn]
        session -= set(demoted)
        return demoted

    def cleanup_session(self, session_id: str) -> None:
        """Remove session state, freeing memory. Safe to call for nonexistent sessions."""
        self._sessions.pop(session_id, None)
