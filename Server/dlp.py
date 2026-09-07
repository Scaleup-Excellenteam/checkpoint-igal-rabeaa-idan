"""
Data Loss Prevention (DLP) inspection engine for TSPO chat.

Scans outgoing message content for known-sensitive patterns before it is
persisted or broadcast. Rules are intentionally simple regexes rather than
a general classifier: the point is a deterministic, auditable first line of
defense, not perfect detection.
"""

from __future__ import annotations

import re
from typing import Tuple

# Rule name -> compiled pattern. Checked in order; the first match wins.
_RULES: list[tuple[str, re.Pattern]] = [
    (
        "tspo_secret",
        re.compile(
            r"secret_sauce|pineapple_protocol|classified_slice|top_secret_recipe",
            re.IGNORECASE,
        ),
    ),
    (
        "plaintext_credential",
        re.compile(r"password\s*=|api_key\s*=|token\s*=", re.IGNORECASE),
    ),
    (
        "credit_card_pii",
        re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"),
    ),
]


def inspect_dlp(content: str) -> Tuple[bool, str, str]:
    """Inspect message content for sensitive data.

    Returns (is_sensitive, rule_name, reason_code). When nothing matches,
    returns (False, "", "").
    """
    if not isinstance(content, str) or not content:
        return False, "", ""

    for rule_name, pattern in _RULES:
        if pattern.search(content):
            return True, rule_name, f"DLP_MATCH_{rule_name.upper()}"

    return False, "", ""
