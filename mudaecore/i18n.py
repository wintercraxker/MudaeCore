"""Shared translations for the current process."""

import json
from pathlib import Path
import threading
from mudaecore.visual import ART_PATH, choose_language, clear_terminal

LOCALES_PATH = Path(__file__).resolve().parent.parent / "locales"
_language = "es"
_lock = threading.RLock()
_warned = set()


def _load_catalog(language):
    with (LOCALES_PATH / f"{language}.json").open(encoding="utf-8") as source:
        return json.load(source)


_catalogs = {"en": _load_catalog("en")}
try:
    _catalogs["es"] = _load_catalog("es")
except (OSError, ValueError):
    _catalogs["es"] = {}


def set_language(language=None):
    global _language
    with _lock:
        _language = language if language in ("es", "en") else "es"


def get_language():
    return _language


class LocalizedText(str):
    def __new__(cls, text, key, diagnostics=None):
        result = super().__new__(cls, text)
        result.translation_key = key
        result.diagnostics = diagnostics or {}
        return result


def t(key, /, **parameters):
    with _lock:
        language = _language
        template = _catalogs[language].get(key)
        if template is None:
            template = _catalogs["en"].get(key, key)
            warning_key = (language, key)
            if warning_key not in _warned:
                _warned.add(warning_key)
                warning = (
                    _catalogs[language].get("translation_missing")
                    or _catalogs["en"]["translation_missing"]
                )
            else:
                warning = None
        else:
            warning = None
    # Log outside the translation lock to avoid lock-order conflicts.
    if warning:
        from mudaecore.logs.console import print_log

        print_log(warning.format(key=key, language=language), "Mudaecore", "WARN")
    diagnostics = {}
    if key == "waiting" and isinstance(parameters.get("minutes"), (int, float)):
        diagnostics["wait_minutes"] = parameters["minutes"]
    if key in ("checking_status", "rolls_parsed"):
        diagnostics["command"] = "$tu"
    if key == "rolls_parsed":
        diagnostics["bonus_command"] = "$us"
    result = LocalizedText(template.format(**parameters), key, diagnostics)
    if key == "account_ready":
        user = parameters.get("user")
        name = getattr(user, "name", None)
        if isinstance(name, str) and name:
            result.account_name = name
    if key == "rolls_parsed":
        result.statistics = {"rolls": parameters["total_rolls"]}
    elif key == "claim_ready":
        result.statistics = {"available": True}
    return result


def select_language():
    clear_terminal()
    selection = choose_language(
        t("language_menu"), t("language_prompt"), t("language_invalid")
    )
    set_language("es" if selection == "1" else "en")
    clear_terminal()


def with_statistics(message, **values):
    """Attach presentation evidence, never serialized to diagnostic files."""
    message.statistics = values
    return message
