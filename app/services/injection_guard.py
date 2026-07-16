"""Injection Guard service for PitchLens.

Pattern-based scanner that detects prompt injection attempts in user input.
Scans for:
- Role-override instructions
- System-prompt extraction attempts
- Delimiter escape sequences
- Instruction-override commands

Security properties:
- Returns generic error without revealing which rule triggered
- Logs attempts with timestamp, user ID, first 500 chars of input
- Latency budget: <200ms (uses compiled regex patterns)
- Fail-closed: any internal error results in rejection
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

# Security audit logger
security_logger = logging.getLogger("pitchlens.security.injection_guard")

# Maximum input length to log for security auditing
_MAX_LOG_INPUT_LENGTH = 500

# Latency budget in seconds
_LATENCY_BUDGET_SECONDS = 0.200


@dataclass
class ScanResult:
    """Result of an injection guard scan.

    Attributes:
        allowed: True if input is safe, False if injection detected or error occurred.
        error: Generic error message when input is blocked. Never reveals which rule triggered.
    """

    allowed: bool
    error: Optional[str] = None


# Compiled regex patterns for performance (<200ms latency budget).
# Each pattern category detects a different class of prompt injection.

# Role-override: attempts to change the AI's role or persona
_ROLE_OVERRIDE_PATTERNS = re.compile(
    r"(?:"
    r"you\s+are\s+now\b"
    r"|ignore\s+(?:all\s+)?previous\s+instructions"
    r"|ignore\s+(?:all\s+)?prior\s+instructions"
    r"|ignore\s+(?:all\s+)?above\s+instructions"
    r"|act\s+as\s+(?:if\s+you\s+are\s+)?(?:a\s+|an\s+)?"
    r"|pretend\s+(?:you\s+are|to\s+be)"
    r"|from\s+now\s+on\s+you\s+are"
    r"|you\s+must\s+now"
    r"|your\s+new\s+role\s+is"
    r"|switch\s+to\s+(?:a\s+|an\s+)?(?:new\s+)?(?:role|mode|persona)"
    r")",
    re.IGNORECASE,
)

# System-prompt extraction: attempts to reveal system instructions
_SYSTEM_PROMPT_EXTRACTION_PATTERNS = re.compile(
    r"(?:"
    r"repeat\s+your\s+(?:system\s+)?instructions"
    r"|show\s+(?:me\s+)?your\s+(?:system\s+)?prompt"
    r"|display\s+your\s+(?:system\s+)?(?:prompt|instructions)"
    r"|what\s+(?:are|is)\s+your\s+(?:system\s+)?(?:prompt|instructions)"
    r"|output\s+your\s+(?:system\s+)?(?:prompt|instructions)"
    r"|reveal\s+your\s+(?:system\s+)?(?:prompt|instructions)"
    r"|print\s+your\s+(?:system\s+)?(?:prompt|instructions)"
    r"|tell\s+me\s+your\s+(?:system\s+)?(?:prompt|instructions)"
    r"|dump\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions)"
    r"|echo\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions)"
    r")",
    re.IGNORECASE,
)

# Delimiter escapes: attempts to break out of context using formatting delimiters
_DELIMITER_ESCAPE_PATTERNS = re.compile(
    r"(?:"
    r"```\s*(?:system|instruction|prompt)"
    r"|---\s*(?:system|instruction|new\s+prompt)"
    r"|###\s*(?:system|instruction|new\s+prompt|override)"
    r"|\[\s*(?:system|INST|SYS)\s*\]"
    r"|<\|(?:im_start|system|end)\|>"
    r"|<<\s*(?:SYS|sys)\s*>>"
    r")",
    re.IGNORECASE,
)

# Instruction-override: direct commands to disregard or replace instructions
_INSTRUCTION_OVERRIDE_PATTERNS = re.compile(
    r"(?:"
    r"disregard\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|context|rules)"
    r"|override\s+(?:all\s+)?(?:previous|prior|above|earlier)?\s*(?:instructions|context|rules|settings)"
    r"|new\s+instructions?\s*[:\-]"
    r"|forget\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|context|rules)"
    r"|reset\s+(?:your\s+)?(?:instructions|context|rules)"
    r"|do\s+not\s+follow\s+(?:your\s+)?(?:previous|prior|original)\s+(?:instructions|rules)"
    r"|bypass\s+(?:your\s+)?(?:instructions|rules|restrictions|guidelines)"
    r"|jailbreak"
    r")",
    re.IGNORECASE,
)

# All pattern categories for iteration
_ALL_PATTERNS = [
    _ROLE_OVERRIDE_PATTERNS,
    _SYSTEM_PROMPT_EXTRACTION_PATTERNS,
    _DELIMITER_ESCAPE_PATTERNS,
    _INSTRUCTION_OVERRIDE_PATTERNS,
]


def scan(text: str, user_id: Optional[str] = None) -> ScanResult:
    """Scan input text for prompt injection patterns.

    Args:
        text: The user input text to scan.
        user_id: Optional user identifier for audit logging.

    Returns:
        ScanResult with allowed=True if safe, allowed=False with generic error if
        injection detected or an internal error occurred (fail-closed).
    """
    try:
        start_time = time.monotonic()

        # Check each pattern category
        for pattern in _ALL_PATTERNS:
            if pattern.search(text):
                # Log the attempt without revealing which pattern matched
                _log_injection_attempt(text, user_id)
                return ScanResult(
                    allowed=False,
                    error="Security violation: request blocked.",
                )

        # Check latency budget
        elapsed = time.monotonic() - start_time
        if elapsed > _LATENCY_BUDGET_SECONDS:
            security_logger.warning(
                "Injection guard scan exceeded latency budget: %.3fs (user_id=%s)",
                elapsed,
                user_id or "unknown",
            )

        return ScanResult(allowed=True)

    except Exception as exc:
        # Fail-closed: any internal error results in rejection
        security_logger.error(
            "Injection guard internal error (user_id=%s): %s",
            user_id or "unknown",
            str(exc),
        )
        return ScanResult(
            allowed=False,
            error="Service unavailable: request cannot be processed.",
        )


def _log_injection_attempt(text: str, user_id: Optional[str]) -> None:
    """Log a detected injection attempt for security auditing.

    Logs timestamp (via logger), user ID, and first 500 chars of input.
    """
    truncated_input = text[:_MAX_LOG_INPUT_LENGTH]
    security_logger.warning(
        "Prompt injection attempt detected | user_id=%s | input=%s",
        user_id or "unknown",
        truncated_input,
    )
