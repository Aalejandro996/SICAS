"""Redacción centralizada de datos sensibles en los logs de SICAS."""
from __future__ import annotations

import logging
import re


_EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)

# Identificadores venezolanos frecuentes: V/E para cédulas y J/G/P/C para RIF.
_ID_RE = re.compile(
    r"\b[VEJGPC]\s*[-:]?\s*(?:\d[.\-/\s]?){6,10}\d(?:\s*-\s*\d)?\b",
    re.IGNORECASE,
)

_BEARER_RE = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)

_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{4,}\b"
)

_SECRET_FIELD_RE = re.compile(
    r"""(?ix)
    (?P<prefix>
        ["']?
        \b(?:password|passwd|pwd|passphrase|token|access_token|
        refresh_token|secret|secret_key|jwt_secret_key|api[_-]?key|
        authorization|client_secret|credential)\b
        ["']?
        \s*[:=]\s*
    )
    (?P<value>
        "(?:\\.|[^"\\])*"
        |
        '(?:\\.|[^'\\])*'
        |
        [^\s,;}\]]+
    )
    """
)


def redact(value: str) -> str:
    """Oculta datos personales y credenciales reconocibles en un mensaje."""
    text = value if isinstance(value, str) else str(value)

    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _JWT_RE.sub("[REDACTED_TOKEN]", text)
    text = _SECRET_FIELD_RE.sub(
        lambda match: f'{match.group("prefix")}"[REDACTED]"',
        text,
    )
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _ID_RE.sub("[REDACTED_ID]", text)
    return text


class RedactingFilter(logging.Filter):
    """Redacta el mensaje y datos de excepción antes de formatear el log."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:
            # Ante un error de redacción, no emitir el mensaje original.
            record.msg = "[log message redaction failed]"
            record.args = ()

        if record.exc_info:
            try:
                record.exc_text = redact(
                    logging.Formatter().formatException(record.exc_info)
                )
            except Exception:
                record.exc_text = "[exception details redacted]"
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)

        if record.stack_info:
            record.stack_info = redact(record.stack_info)

        return True


def install_redaction_filter(app=None, extra_loggers=()) -> None:
    """Instala el filtro en los handlers ya existentes sin duplicarlo."""
    loggers = {logging.getLogger()}

    for item in logging.Logger.manager.loggerDict.values():
        if isinstance(item, logging.Logger):
            loggers.add(item)

    if app is not None:
        # Acceder a app.logger asegura que su handler de Flask quede incluido.
        loggers.add(app.logger)

    for logger in extra_loggers:
        if isinstance(logger, logging.Logger):
            loggers.add(logger)

    for logger in loggers:
        for handler in logger.handlers:
            if not any(
                isinstance(f, RedactingFilter) for f in handler.filters
            ):
                handler.addFilter(RedactingFilter())
