"""
Keyword matching utilities for trigger-based server activation.
"""

from typing import List, Any


def extract_keywords_from_message(message: dict) -> str:
    """
    Extract searchable text from a JSON-RPC message.

    Args:
        message: JSON-RPC message dict

    Returns:
        Combined text content from message
    """

    # Extract all string values from the message recursively
    def extract_text(obj: Any) -> List[str]:
        if isinstance(obj, str):
            return [obj]
        elif isinstance(obj, dict):
            texts = []
            for value in obj.values():
                texts.extend(extract_text(value))
            return texts
        elif isinstance(obj, list):
            texts = []
            for item in obj:
                texts.extend(extract_text(item))
            return texts
        else:
            return []

    texts = extract_text(message)
    return " ".join(texts)


def match_triggers(text: str, triggers: List[str]) -> bool:
    """
    Check if any trigger keyword appears in text (case-insensitive).

    Args:
        text: Text to search
        triggers: List of trigger keywords

    Returns:
        True if any trigger matches, False otherwise
    """
    text_lower = text.lower()

    for trigger in triggers:
        if trigger.lower() in text_lower:
            return True

    return False
