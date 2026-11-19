import copy
import json
import math
import os
from pathlib import Path
import re
import tempfile

import inquirer
from mudaecore.config import PROJECT_ROOT
from mudaecore.i18n import t
from mudaecore.visual import clear_terminal, OptionLabel
from mudaecore.states.preset_defaults import new_profile

REQUIRED = {
    "token",
    "prefix",
    "channel_id",
    "roll_command",
    "min_kakera",
    "delay_seconds",
    "mudae_prefix",
}
GENERAL = {"prefix", "mudae_prefix", "roll_command", "channel_id", "guild_id"}
CHARACTERS = {
    "min_kakera",
    "wishlist",
    "series_wishlist",
    "snipe_mode",
    "series_snipe_mode",
}
SENSITIVE = {"token", "password", "secret", "authorization"}
BOOLEAN_FIELDS = {
    "rolling",
    "snipe_mode",
    "series_snipe_mode",
    "kakera_snipe_mode",
    "kakera_reaction_snipe_mode",
    "only_chaos",
    "auto_pokeslot",
    "auto_steal",
    "use_slash_rolls",
    "dk_power_management",
    "snipe_ignore_min_kakera_reset",
    "key_mode",
    "reactive_snipe_on_own_rolls",
    "humanization_enabled",
    "skip_initial_commands",
    "snipe_requires_claim_available",
}
LIST_FIELDS = {"wishlist", "series_wishlist", "kakera_reaction_snipe_targets"}
NUMBER_FIELDS = {
    "min_kakera",
    "kakera_snipe_threshold",
    "delay_seconds",
    "roll_speed",
    "start_delay",
    "snipe_delay",
    "series_snipe_delay",
    "steal_delay",
    "reactive_snipe_delay",
    "kakera_reaction_snipe_delay",
    "pokeslot_interval_minutes",
    "humanization_window_minutes",
    "humanization_inactivity_seconds",
}


def hidden(key):
    return key.startswith("_comment_") or any(word in key.lower() for word in SENSITIVE)


def valid_name(name):
    return (
        isinstance(name, str)
        and bool(name.strip())
        and name == name.strip()
        and all(c.isprintable() for c in name)
    )


def parse_value(key, text, current):
    if key == "guild_id" and text.strip().lower() == "null":
        return None
    if key in ("channel_id", "guild_id") or type(current) is int:
        if not re.fullmatch(r"[0-9]+", text.strip()):
            raise ValueError
        value = int(text)
        if key in ("channel_id", "guild_id") and value >= 2**64:
            raise ValueError
        if key == "pokeslot_interval_minutes" and value <= 0:
            raise ValueError
        return value
    if type(current) is float:
        value = float(text)
        if (
            not math.isfinite(value)
            or value < 0
            or (key == "pokeslot_interval_minutes" and value == 0)
        ):
            raise ValueError
        return value
    if (
        not isinstance(text, str)
        or not text.strip()
        or not all(c.isprintable() for c in text)
    ):
        raise ValueError
    if key == "roll_command" and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", text):
        raise ValueError
    return text


def validate(data):
    if not isinstance(data, dict) or not data:
        raise ValueError
    for name, profile in data.items():
        if (
            not valid_name(name)
            or not isinstance(profile, dict)
            or not REQUIRED <= profile.keys()
        ):
            raise ValueError
        for key, value in profile.items():
            if key in BOOLEAN_FIELDS and type(value) is not bool:
                raise ValueError
            if key in LIST_FIELDS and not isinstance(value, list):
                raise ValueError
            if key in NUMBER_FIELDS and (
                type(value) not in (int, float) or not math.isfinite(value) or value < 0
            ):
                raise ValueError
            if (
                key in ("channel_id", "guild_id")
                and not (key == "guild_id" and value is None)
                and type(value) is not int
            ):
                raise ValueError
            if key in ("prefix", "mudae_prefix", "roll_command") and not isinstance(
                value, str
            ):
                raise ValueError
            if key == "token":
                if not isinstance(value, str):
                    raise ValueError
            elif hidden(key):
                continue
            elif isinstance(value, list):
                if not all(isinstance(item, str) and item.strip() for item in value):
                    raise ValueError
            elif isinstance(value, bool):
                continue
            elif value is None and key == "guild_id":
                continue
            else:
                parse_value(key, str(value), value)
    json.dumps(data, allow_nan=False)


def clone_profile(template):
    profile = copy.deepcopy(template)
    for key in profile:
        if any(word in key.lower() for word in SENSITIVE):
            profile[key] = ""
        elif key.endswith("_id"):
            profile[key] = None if profile[key] is None else 0
        elif isinstance(profile[key], list):
            profile[key] = []
    return profile


def atomic_save(path, data, expected):
    """Reject stale edits and atomically replace the file without permanent backups."""
    validate(data)
    path = Path(path)
    original = path.read_bytes()
    if original != expected:
        raise ValueError
    validate(json.loads(original))
    payload = (
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".presets-", suffix=".tmp", delete=False
        ) as output:
            temp = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if path.read_bytes() != original:
            raise ValueError
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def item_count(count):
    return t("cfg_one_item") if count == 1 else t("cfg_count", count=count)


class Editor:
    def __init__(self, prompt):
        self.prompt = prompt
        self.focus = {}
        self.context_help = {}
        self.preset_name = ""
        self.text_default = ""
        self.list_key = "wishlist"

    def choose(self, title, choices):
        clear_terminal()
        question = inquirer.List(
            "value", message=title, choices=choices, default=self.focus.get(title)
        )
        question.configuration = True
        question.context_help = self.context_help
        question.option_rows = {
            value: (label.label, label.value)
            for label, value in choices
            if isinstance(label, OptionLabel)
        }
        answer = self.prompt([question])
        value = answer["value"] if answer else None
        if value is not None:
            self.focus[title] = value
        return value

    def text(self, title):
        clear_terminal()
        question = inquirer.Text("value", message=title, default=self.text_default)
        question.configuration = True
        answer = self.prompt([question])
        self.text_default = ""
        return answer["value"] if answer else None

    def integration_credentials(self, profile):
        while True:
            action = self.choose(
                t("cfg_credentials_title") + "\n" + t("cfg_credentials_policy"),
                [
                    (t("cfg_credentials_enter"), "enter"),
                    (t("cfg_credentials_skip"), "skip"),
                    (t("cfg_back"), None),
                ],
            )
            if action is None:
                return False
            if action == "skip":
                profile["token"] = ""
                return True
            clear_terminal()
            question = inquirer.Password(
                "value", message=t("cfg_credentials_enter"), echo="*"
            )
            question.configuration = True
            answer = self.prompt([question])
            value = answer.get("value") if answer else None
            if value is None:
                return False
            if (
                not value
                or value == "PUT_YOUR_TOKEN"
                or any(c.isspace() or not c.isprintable() for c in value)
            ):
                self.notice("cfg_credentials_invalid")
                continue
            from mudaecore.logs.console import protect_secret

            protect_secret(value)
            profile["token"] = value
            return True

    def label(self, key):
        from mudaecore.i18n import _catalogs

        return (
            t("field_" + key)
            if "field_" + key in _catalogs["en"]
            else key.replace("_", " ").capitalize()
        )

    def description(self, key):
        from mudaecore.i18n import _catalogs

        return (
            t("help_" + key)
            if "help_" + key in _catalogs["en"]
            else t("cfg_help_unknown")
        )

    def summary(self, key, value):
        if key.endswith("_id"):
            return (
                t("cfg_unset") if value is None or value == 0 else t("cfg_configured")
            )
        if isinstance(value, bool):
            return t("cfg_enabled") if value else t("cfg_disabled")
        if isinstance(value, list):
            return item_count(len(value))
        return str(value)

    def confirm(self, title):
        return self.choose(title, [(t("cfg_yes"), True), (t("cfg_no"), False)]) is True

    def notice(self, key):
        self.choose(t(key), [(t("cfg_back"), "back")])

    def edit_list(self, values):
        while True:
            choice = self.choose(
                self.preset_name
                + "\n"
                + self.label(self.list_key)
                + " · "
                + item_count(len(values)),
                [(f"{i + 1}. {v}", i) for i, v in enumerate(values)]
                + [
                    (t("cfg_add"), "add"),
                    (t("cfg_clear"), "clear"),
                    (t("cfg_back"), None),
                ],
            )
            if choice is None:
                return
            if choice == "clear":
                if self.confirm(t("cfg_confirm_clear")):
                    values.clear()
            elif choice == "add":
                while True:
                    value = self.text(t("cfg_entry"))
                    if value is None:
                        break
                    if (
                        not value.strip()
                        or value in values
                        or not all(c.isprintable() for c in value)
                    ):
                        self.notice("cfg_invalid")
                        continue
                    if self.confirm(t("cfg_confirm_value", value=value)):
                        values.append(value)
                    if not self.confirm(
                        t("cfg_added") if value in values else t("cfg_another")
                    ):
                        break
            else:
                action = self.choose(
                    values[choice],
                    [
                        (t("cfg_edit"), "edit"),
                        (t("cfg_remove"), "remove"),
                        (t("cfg_back"), None),
                    ],
                )
                if action == "remove":
                    if self.confirm(t("cfg_confirm_clear")):
                        values.pop(choice)
                elif action == "edit":
                    self.text_default = values[choice]
                    value = self.text(t("cfg_current", value=values[choice]))
                    if value is None:
                        continue
                    if (
                        not value.strip()
                        or (value in values and value != values[choice])
                        or not all(c.isprintable() for c in value)
                    ):
                        self.notice("cfg_invalid")
                    elif self.confirm(t("cfg_confirm_value", value=value)):
                        values[choice] = value

    def edit_value(self, profile, key):
        current = profile[key]
        if key == "snipe_requires_claim_available":
            self.notice("cfg_unused")
        if isinstance(current, list):
            self.list_key = key
            self.edit_list(current)
            return
        display = (
            t("cfg_enabled")
            if current is True
            else t("cfg_disabled") if current is False else str(current)
        )
        title = (
            self.preset_name
            + "\n"
            + self.label(key)
            + "\n"
            + t("cfg_current", value=display)
            + "\n"
            + self.description(key)
        )
        if isinstance(current, bool):
            value = self.choose(
                title,
                [
                    (t("cfg_enabled"), True),
                    (t("cfg_disabled"), False),
                    (t("cfg_keep"), None),
                ],
            )
            if value is not None:
                profile[key] = value
            return
        if key == "roll_command":
            value = self.choose(
                title,
                [
                    ("wa", "wa"),
                    ("ha", "ha"),
                    (t("cfg_custom"), "custom"),
                    (t("cfg_keep"), None),
                ],
            )
            if value is None:
                return
            if value == "custom":
                self.notice("cfg_custom_warning")
                value = self.text(title)
        else:
            self.text_default = str(current) if current is not None else "null"
            value = self.text(title)
        if value is None:
            return
        try:
            value = parse_value(key, value, current)
        except (ValueError, TypeError):
            self.notice("cfg_invalid")
            return
        if self.confirm(t("cfg_confirm_value", value=value)):
            profile[key] = value

    def edit_profile(self, data, name):
        category = None
        while True:
            self.preset_name = name
            if category is None:
                self.context_help = {}
                category = self.choose(
                    name,
                    [
                        (t("cfg_" + k), k)
                        for k in (
                            "general",
                            "characters",
                            "kakera",
                            "features",
                            "advanced",
                        )
                    ]
                    + [(t("cfg_back"), None)],
                )
            if category is None:
                return
            profile = data[name]
            label_width = max(
                (len(self.label(k)) for k in profile if not hidden(k)), default=0
            )
            groups = {
                k: []
                for k in ("general", "characters", "kakera", "features", "advanced")
            }
            for key, value in profile.items():
                if hidden(key):
                    continue
                group = (
                    "general"
                    if key in GENERAL
                    else (
                        "characters"
                        if key in CHARACTERS
                        else (
                            "kakera"
                            if "kakera" in key or key == "only_chaos"
                            else (
                                "features"
                                if isinstance(value, bool)
                                or key == "pokeslot_interval_minutes"
                                else "advanced"
                            )
                        )
                    )
                )
                groups[group].append(
                    (OptionLabel(self.label(key), self.summary(key, value)), key)
                )
            choices = groups[category] + [(t("cfg_back"), None)]
            if category == "general":
                choices.insert(0, (t("cfg_name"), "__name__"))
            self.context_help = {
                key: self.description(key)
                for _, key in choices
                if key and key != "__name__"
            }
            key = self.choose(name + "\n" + t("cfg_" + category), choices)
            self.context_help = {}
            if key == "__name__":
                self.text_default = name
                new = self.text(t("cfg_name"))
                if new is None:
                    continue
                if not valid_name(new) or (new != name and new in data):
                    self.notice("cfg_invalid")
                elif new != name and self.confirm(t("cfg_confirm_value", value=new)):
                    pairs = [(new if k == name else k, v) for k, v in data.items()]
                    data.clear()
                    data.update(pairs)
                    name = new
            elif key is not None:
                self.edit_value(profile, key)
            else:
                category = None

    def create_profile(self, draft, persist=None):
        profile = new_profile()
        name = ""
        step = 1
        returning = False
        stages = {
            2: (
                "general",
                ["prefix", "mudae_prefix", "roll_command", "channel_id", "guild_id"],
            ),
            3: (
                "characters",
                [
                    "min_kakera",
                    "snipe_mode",
                    "wishlist",
                    "series_snipe_mode",
                    "series_wishlist",
                ],
            ),
            4: (
                "essentials",
                [
                    "kakera_snipe_threshold",
                    "kakera_snipe_mode",
                    "kakera_reaction_snipe_mode",
                    "auto_steal",
                    "auto_pokeslot",
                ],
            ),
        }
        while True:
            title = t("cfg_create") + "\n" + t("cfg_step", step=step)
            self.preset_name = name
            if step == 1:
                self.text_default = name
                entered = self.text(title + "\n" + t("cfg_name"))
                if entered is None:
                    if self.confirm(t("cfg_cancel_creation")):
                        return
                    continue
                if not valid_name(entered) or entered in draft:
                    self.notice("cfg_invalid")
                    continue
                name = entered
                step = 5 if returning else 2
            elif step < 5:
                category, keys = stages[step]
                self.context_help = {k: self.description(k) for k in keys}
                choices = [
                    (OptionLabel(self.label(k), self.summary(k, profile[k])), k)
                    for k in keys
                ]
                choices += [
                    (t("cfg_next_stage"), "next"),
                    (t("cfg_previous_stage"), "back"),
                    (t("cfg_cancel_creation"), "cancel"),
                ]
                heading = title + "\n" + name + "\n" + t("cfg_" + category)
                if step == 2:
                    heading += "\n" + t("cfg_credentials_unset")
                selected = self.choose(heading, choices)
                self.context_help = {}
                if selected == "next":
                    step = 5 if returning else step + 1
                elif selected == "back" or selected is None:
                    step = 5 if returning else step - 1
                elif selected == "cancel":
                    if self.confirm(t("cfg_cancel_creation")):
                        return
                else:
                    self.edit_value(profile, selected)
            else:
                review_keys = [
                    "roll_command",
                    "min_kakera",
                    "kakera_snipe_threshold",
                    "wishlist",
                    "series_wishlist",
                    "snipe_mode",
                    "kakera_snipe_mode",
                    "kakera_reaction_snipe_mode",
                    "auto_steal",
                    "auto_pokeslot",
                ]
                summary = [name] + [
                    self.label(k) + ": " + self.summary(k, profile[k])
                    for k in review_keys
                ]
                summary += [t("cfg_general_reviewed"), t("cfg_credentials_unset")]
                choices = [
                    (t("cfg_create_confirm"), "create"),
                    (t("cfg_modify_section"), "modify"),
                    (t("cfg_cancel_creation"), "cancel"),
                ]
                self.context_help = {}
                selected = self.choose(title + "\n" + "\n".join(summary), choices)
                if selected == "create":
                    try:
                        validate({name: profile})
                    except (ValueError, TypeError):
                        for field in profile:
                            probe = new_profile()
                            probe[field] = profile[field]
                            try:
                                validate({name: probe})
                            except (ValueError, TypeError):
                                self.choose(
                                    t("cfg_field_error", field=self.label(field)),
                                    [(t("cfg_edit"), True)],
                                )
                                self.edit_value(profile, field)
                                break
                        continue
                    if persist is not None and not persist(name, profile):
                        continue
                    draft[name] = profile
                    return name
                if selected == "modify":
                    section = self.choose(
                        t("cfg_modify_section"),
                        [(t("cfg_name"), 1)]
                        + [
                            (t("cfg_" + category), n)
                            for n, (category, _) in stages.items()
                        ]
                        + [(t("cfg_back"), None)],
                    )
                    if section is not None:
                        step, returning = section, True
                elif selected is None or selected == "cancel":
                    if self.confirm(t("cfg_cancel_creation")):
                        return


def configuration_menu(presets, prompt, path=None):
    path = Path(path) if path is not None else PROJECT_ROOT / "presets.json"
    editor = Editor(prompt)
    try:
        expected = path.read_bytes()
        draft = copy.deepcopy(json.loads(expected))
        validate(draft)

        def persist_created(name, profile):
            nonlocal expected, presets
            if not editor.integration_credentials(profile):
                return False
            candidate = copy.deepcopy(draft)
            if name in candidate:
                editor.notice("cfg_invalid")
                return False
            candidate[name] = profile
            try:
                atomic_save(path, candidate, expected)
            except OSError:
                editor.notice("cfg_write_failed")
                return False
            except ValueError:
                editor.notice("cfg_save_error")
                return False
            expected = path.read_bytes()
            presets = copy.deepcopy(candidate)
            return True

        while True:
            choice = editor.choose(
                t("cfg_title"),
                [(name, ("preset", name)) for name in draft]
                + [(t("cfg_create"), "new"), (t("cfg_back"), None)],
            )
            if choice is None:
                if draft == json.loads(expected):
                    return presets
                action = editor.choose(
                    t("cfg_pending"),
                    [
                        (t("cfg_save"), "save"),
                        (t("cfg_discard"), "discard"),
                        (t("cfg_continue"), "edit"),
                    ],
                )
                if action == "save":
                    try:
                        atomic_save(path, draft, expected)
                    except (ValueError, OSError):
                        editor.notice("cfg_save_error")
                        continue
                    editor.notice("cfg_saved")
                    return draft
                if action == "discard":
                    return presets
            elif choice == "new":
                created = editor.create_profile(draft, persist_created)
                if created is not None:
                    status = (
                        t("cfg_credentials_stored")
                        if draft[created].get("token")
                        else t("cfg_credentials_unset")
                    )
                    destination = editor.choose(
                        t("cfg_created", name=created) + "\n" + status,
                        [
                            (t("cfg_return_configuration"), "configuration"),
                            (t("cfg_return_main"), "main"),
                        ],
                    )
                    editor.focus.pop(t("cfg_title"), None)
                    if destination == "main" or destination is None:
                        return presets
            else:
                editor.edit_profile(draft, choice[1])
    except EOFError:
        return presets
    except (OSError, ValueError, TypeError):
        editor.notice("cfg_save_error")
        return presets
