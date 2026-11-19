from mudaecore.i18n import t
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_presets(path=None):
    path = Path(path) if path is not None else PROJECT_ROOT / "presets.json"
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(t("config_read_error", filename=path.name, error=exc)) from exc
