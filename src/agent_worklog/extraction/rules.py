"""Conservative extraction rules."""

import re

TEST_COMMAND_PATTERNS = (
    re.compile(r"(?:^|\s)pytest(?:\s|$)"),
    re.compile(r"(?:^|\s)ruff(?:\s|$)"),
    re.compile(r"(?:^|\s)pyright(?:\s|$)"),
    re.compile(r"(?:^|\s)npm\s+test(?:\s|$)"),
    re.compile(r"(?:^|\s)pnpm\s+test(?:\s|$)"),
    re.compile(r"(?:^|\s)npm\s+run\s+build(?:\s|$)"),
)

ASSISTANT_COMPLETION_PATTERN = re.compile(
    r"\b(?:implemented|completed|fixed|resolved|finished|done|passed)\b",
    re.IGNORECASE,
)

IGNORED_USER_TEXT = {
    "ok",
    "okay",
    "yes",
    "no",
    "continue",
    "go ahead",
    "looks good",
}

FILE_TOOL_NAMES = {"edit", "write", "patch", "apply_patch", "apply-patch"}
COMMAND_TOOL_NAMES = {"bash", "shell", "terminal", "command", "exec"}


def is_meaningful_user_text(text: str) -> bool:
    normalized = " ".join(text.split()).strip()
    return len(normalized) >= 4 and normalized.lower() not in IGNORED_USER_TEXT


def is_verification_command(command: str) -> bool:
    return any(pattern.search(command) for pattern in TEST_COMMAND_PATTERNS)
