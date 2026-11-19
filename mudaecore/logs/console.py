from mudaecore.i18n import t
import datetime
import os
import sys
import threading
import time
import logging
import tempfile
import re
import json
import hashlib
from contextlib import contextmanager

from mudaecore.config import PROJECT_ROOT
from mudaecore.visual import (
    paint,
    horizontal_gradient,
    color_supported,
    visible_width,
    ANSI,
)
from mudaecore.states.presentation import observe_event, summary
from mudaecore.states.statistics import statistics

LOG_PATH = PROJECT_ROOT / "logs.txt"
DIAGNOSTIC_PATH = PROJECT_ROOT / "diagnostics.jsonl"
_lock = threading.RLock()
_last_status = {}
_last_event = {}
_REPEAT_WINDOW = 10.0
_menu_depth = 0
_pending = None
_preset_width = 24
_secrets = ()
_account_names = {}
_preset_labels = {}
EVENT_COLORS = {
    "INFO": ((100, 133, 214), (158, 174, 245), (197, 184, 243)),
    "ERROR": ((199, 71, 91), (230, 106, 118), (243, 160, 164)),
    "WARN": ((197, 138, 66), (231, 183, 106), (242, 210, 154)),
    "SUCCESS": ((76, 154, 121), (121, 199, 160), (176, 228, 197)),
    "CLAIM": ((137, 99, 197), (178, 141, 224), (214, 174, 219)),
    "RESET": ((126, 117, 198), (171, 161, 229), (214, 204, 245)),
}
EVENT_COLORS["STEAL"] = EVENT_COLORS["CLAIM"]
EVENT_COLORS["CLAIM"] = EVENT_COLORS["SUCCESS"]
EVENT_COLORS["CHECK"] = ((131, 110, 180), (173, 154, 220), (207, 191, 239))
EVENT_COLORS["KAKERA"] = ((184, 148, 75), (219, 185, 110), (239, 216, 167))


def configure_log_context(presets):
    global _preset_width, _secrets
    with _lock:
        _preset_width = 24
        _account_names.clear()
        _preset_labels.clear()
        _preset_labels.update(
            (name, f"P{index:02d}") for index, name in enumerate(presets, 1)
        )
        _secrets = tuple(
            sorted(
                {
                    data.get("token")
                    for data in presets.values()
                    if isinstance(data.get("token"), str) and data.get("token")
                },
                key=len,
                reverse=True,
            )
        )


def account_label(preset_name):
    """Visual alias only; configuration and diagnostic keys remain untouched."""
    with _lock:
        identifier = _preset_labels.setdefault(
            preset_name, f"P{len(_preset_labels) + 1:02d}"
        )
        name = _account_names.get(preset_name)
        limit = _preset_width - 2
        if name is None:
            original = redact(preset_name)
            return original if visible_width(original) <= limit else identifier
        duplicate = (
            sum(
                value.casefold() == name.casefold() for value in _account_names.values()
            )
            > 1
        )
        suffix = f"~{identifier}" if duplicate or visible_width(name) > limit else ""
        return name[: max(0, limit - len(suffix))] + suffix


def redact(text):
    text = ANSI.sub("", str(text))
    for secret in _secrets:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(
        r"(?i)\b(authorization[\x22\x27]?\s*[:=]\s*[\x22\x27]?)(?:(?:Bot|Bearer)\s+)?[^\s,;\x22\x27]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)(\b(?:token|password|secret)[\x22\x27]?\s*[:=]\s*[\x22\x27]?)[^\s,;\x22\x27]+",
        r"\1[REDACTED]",
        text,
    )
    return re.sub(
        r"\b(?:mfa\.[\w-]{20,}|[\w-]{20,30}\.[\w-]{6}\.[\w-]{25,})\b",
        "[REDACTED]",
        text,
    )


def protect_secret(value):
    global _secrets
    with _lock:
        if value:
            _secrets = tuple(sorted(set(_secrets) | {value}, key=len, reverse=True))


def level_label(level):
    label = f"[{level}]"
    return label + " " * max(0, 10 - visible_width(label))


def accented_message(message, enabled):
    parts = re.split(r"(\b\d+(?:[.,]\d+)*\b)", message)
    return "".join(
        paint(part, (195, 184, 225) if index % 2 else (225, 223, 231), enabled)
        for index, part in enumerate(parts)
    )


def terminal_write(text):
    with _lock:
        if _menu_depth:
            _pending.write(text + "\n")
        else:
            print(text, flush=True)


@contextmanager
def menu_session():
    global _menu_depth, _pending
    with _lock:
        if _menu_depth == 0:
            _pending = tempfile.SpooledTemporaryFile(
                max_size=1024 * 1024, mode="w+t", encoding="utf-8"
            )
        _menu_depth += 1
    try:
        yield
    finally:
        with _lock:
            _menu_depth -= 1
            if not _menu_depth:
                _pending.seek(0)
                for line in _pending:
                    print(line, end="")
                sys.stdout.flush()
                _pending.close()
                _pending = None


def color_log(message, preset_name, log_type="INFO"):
    level = log_type.upper()
    compact_ready = (
        getattr(message, "translation_key", None) == "account_ready"
        and preset_name in _account_names
    )
    display_name = account_label(preset_name)
    prefix = f"[{preset_name}] "
    if message.startswith(prefix):
        message = message[len(prefix) :]
    message, preset_name = redact(message), redact(preset_name)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    preset = f"[{preset_name}]"
    preset += " " * max(0, _preset_width - visible_width(preset))
    label = level_label(level)
    line = f"[{timestamp}] {label} {preset} {message}"
    # Keep the original preset and full event in the persistent log.
    preset = f"[{display_name}]"
    names = [account_label(key) for key in _account_names]
    width = min(
        14, max([visible_width(preset)] + [visible_width(name) + 2 for name in names])
    )
    preset += " " * max(0, width - visible_width(preset)) + " "
    if compact_ready:
        message = t("account_ready_compact")
    enabled = color_supported()
    colors = EVENT_COLORS.get(level, EVENT_COLORS["INFO"])
    rendered = (
        paint(f"[{timestamp}]", (153, 151, 164), enabled)
        + " "
        + horizontal_gradient(f"[{level}]", colors, enabled)
        + label[len(level) + 2 :]
        + " "
        + paint(preset, (167, 139, 250), enabled)
        + " "
        + accented_message(message, enabled)
    )
    terminal_write(rendered)
    return line


def write_log_to_file(log_message):
    try:
        with _lock, LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(redact(log_message) + "\n")
    except OSError as exc:
        terminal_write(t("log_file_error", error=exc))


def print_log(message, preset_name, log_type="INFO"):
    with _lock:
        event = getattr(message, "translation_key", None)
        source = (preset_name, threading.get_ident())
        account_name = getattr(message, "account_name", None)
        if event == "account_ready" and isinstance(account_name, str) and account_name:
            # Ignore control characters, and apply the same credential filter as logs.
            _account_names[preset_name] = "".join(
                char for char in redact(account_name) if char.isprintable()
            )
        observe_event(preset_name, event, log_type)
        statistics.observe(preset_name, message)
        previous_event = _last_event.get(source)
        _last_event[source] = event
        if event == "rolls_available" and previous_event == "rolls_parsed":
            return
        details = getattr(message, "diagnostics", {})
        if details:
            try:
                with DIAGNOSTIC_PATH.open("a", encoding="utf-8") as destination:
                    preset_key = hashlib.sha256(
                        str(preset_name).encode("utf-8")
                    ).hexdigest()[:16]
                    destination.write(
                        json.dumps(
                            dict(
                                timestamp=datetime.datetime.now().isoformat(),
                                preset_key=preset_key,
                                worker_id=threading.get_ident(),
                                event=message.translation_key,
                                **details,
                            )
                        )
                        + "\n"
                    )
            except OSError as exc:
                terminal_write(t("log_file_error", error=exc))
        # Suppress repeated status messages only.
        if log_type.upper() in {"INFO", "CHECK"}:
            now = time.monotonic()
            previous = _last_status.get(source)
            key = (log_type.upper(), message)
            if previous and previous[0] == key and now - previous[1] < _REPEAT_WINDOW:
                return
            _last_status[source] = (key, now)
        else:
            _last_status.pop(source, None)
        write_log_to_file(color_log(message, preset_name, log_type))
        if summary.entries:
            report_summary()


def report_summary():
    with _lock:
        counts = summary.snapshot()
        if not counts["selected"] or counts == summary.last_report:
            return
        summary.last_report = counts


class ExternalHandler(logging.Handler):
    def emit(self, record):
        try:
            timestamp = datetime.datetime.fromtimestamp(record.created).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            detail = redact(logging.Formatter().format(record))
            source = f"[external:{record.name}]"
            source += " " * max(0, _preset_width - visible_width(source))
            line = f"[{timestamp}] {level_label(record.levelname)} {source} {detail}"
            with _lock:
                terminal_write(paint(line, (158, 157, 167)))
                write_log_to_file(line)
        except Exception:
            self.handleError(record)


class RepeatedDiagnostics(logging.Filter):
    def __init__(self):
        super().__init__()
        self.previous = {}
        self.lock = threading.Lock()

    def filter(self, record):
        with self.lock:
            if (
                record.levelno >= logging.WARNING
                or record.exc_info
                or record.stack_info
            ):
                self.previous.pop(record.name, None)
                return True
            if (
                (record.name == "discord" or record.name.startswith("discord."))
                and record.levelno <= logging.INFO
                and any(
                    phrase in record.getMessage().lower()
                    for phrase in (
                        "logging in using static token",
                        "found user agent",
                        "found tls fingerprint target",
                    )
                )
            ):
                return False
            key = (record.levelno, record.getMessage())
            now = time.monotonic()
            previous = self.previous.get(record.name)
            if previous and previous[0] == key and now - previous[1] < _REPEAT_WINDOW:
                return False
            self.previous[record.name] = (key, now)
            return True


_external_handler = ExternalHandler()
_external_handler.addFilter(RepeatedDiagnostics())


class ExternalRootFilter(logging.Filter):
    def filter(self, record):
        _external_handler.handle(record)
        return False


_external_filter = ExternalRootFilter()


def configure_external_logging():
    # Route library output through the same writer before worker threads start.
    parent = logging.getLogger("discord")
    parent.addFilter(_external_filter)
    parent.setLevel(logging.INFO)
    for name in list(logging.Logger.manager.loggerDict):
        if not name.startswith("discord."):
            continue
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            if isinstance(handler, logging.StreamHandler):
                logger.removeHandler(handler)
        logger.addHandler(_external_handler)
        logger.propagate = False
