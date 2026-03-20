"""Input sanitizer to detect common prompt injection patterns.

Not a complete defense on its own — works as a first-pass filter against
naive injection attempts before the query reaches the LLM.
"""

import re
from logger import get_logger
log = get_logger(name="core_sanitizer")


_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?",
    r"disregard\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?",
    r"forget\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?",
    r"override\s+(the\s+)?(system|previous|prior)\s+(prompt|instructions?)",
    r"you\s+are\s+now\s+(a|an|the)\b",
    r"new\s+instructions?\s*:",
    r"system\s*prompt\s*:",
    r"act\s+as\s+(a|an|the)\b",
    r"pretend\s+(you\s+are|to\s+be)\b",
    r"roleplay\s+as\b",
    r"jailbreak",
    r"dan\s+mode",
    r"developer\s+mode",
    r"</?(system|context|instruction|prompt)>",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def is_safe_query(query: str) -> tuple[bool, str]:
    """Check if a query appears to be a prompt injection attempt.

    Returns:
        tuple: (is_safe, reason) — is_safe is True if no injection patterns detected.
    """
    for pattern in _COMPILED:
        if pattern.search(query):
            log.warning(f"[sanitizer] Potential injection detected in query: '{query[:120]}'")
            return False, "Query contains disallowed content."
    return True, ""
