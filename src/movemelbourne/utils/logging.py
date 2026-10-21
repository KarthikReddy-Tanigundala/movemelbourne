"""Structured logging with secret redaction.

Every handler gets a filter that replaces registered secret values (the API key, the HF token)
with ``***`` in the rendered message and in exception text, so a key can never reach a log file,
a GitHub Actions log or an error message, even if a library puts it in a URL.
"""

from __future__ import annotations

import logging
import os
import re
import sys

_SECRETS: set[str] = set()
_QUERY_KEY = re.compile(r"(subscription-key=)[^&\s'\"]+", re.IGNORECASE)


def register_secret(value: str | None) -> None:
    """Add a value that must never appear in logs. Short values are ignored to avoid noise."""
    if value and len(value) >= 8:
        _SECRETS.add(value)


def redact(text: str) -> str:
    """Return ``text`` with every registered secret and any key-bearing query param masked."""
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    return _QUERY_KEY.sub(r"\1***", text)


class RedactingFilter(logging.Filter):
    """Logging filter that renders the record, redacts it and freezes the result."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = redact(record.getMessage())
        if record.exc_info:
            formatter = logging.Formatter()
            message = f"{message}\n{redact(formatter.formatException(record.exc_info))}"
            record.exc_info = None
            record.exc_text = None
        record.msg, record.args = message, None
        return True


def setup_logging(level: str | int | None = None) -> None:
    """Configure root logging once: ISO timestamps, level, logger name, redacted message."""
    register_secret(os.getenv("TVOD_API_KEY"))
    register_secret(os.getenv("HF_TOKEN"))
    root = logging.getLogger()
    if any(isinstance(f, RedactingFilter) for h in root.handlers for f in h.filters):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    )
    handler.addFilter(RedactingFilter())
    root.handlers = [handler]
    root.setLevel(level or os.getenv("LOG_LEVEL", "INFO"))
    # urllib3 logs full request URLs at DEBUG; keep it quiet regardless of root level.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
