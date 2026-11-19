from collections import OrderedDict
import hashlib
import json
import threading

from mudaecore.constants import CLAIM_EMOJIS
from mudaecore.parsers.characters import (
    has_claim_option,
    is_character_embed,
    parse_kakera_value,
)
from mudaecore.services.eligibility import meets_minimum, reactive_value_target


def inspect_message(message):
    components = getattr(message, "components", ()) or ()
    reactions = getattr(message, "reactions", ()) or ()
    buttons = [button for row in components for button in getattr(row, "children", ())]
    claim_buttons = [
        button
        for button in buttons
        if getattr(getattr(button, "emoji", None), "name", None) in CLAIM_EMOJIS
    ]
    kind = (
        "mixed"
        if components and reactions
        else "components" if components else "reactions" if reactions else "unknown"
    )
    embeds = getattr(message, "embeds", ()) or ()
    embed = embeds[0] if embeds else None
    return {
        "message_type": kind,
        "components_present": bool(components),
        "reactions_present": bool(reactions),
        "claim_button_present": bool(claim_buttons),
        "disabled_claim_button": any(
            getattr(button, "disabled", False) for button in claim_buttons
        ),
        "legacy_claim_option": bool(has_claim_option(message, embed)),
        "character_embed": bool(is_character_embed(embed)),
        "kakera_value": parse_kakera_value(getattr(embed, "description", None)),
    }


def evaluate_selection(
    message, client, route, *, ignore_limit=False, key_only=False, claimed_post=False
):
    """Observe selection eligibility, not action success or current server permissions."""
    routes = {
        "own_reactive",
        "post_roll",
        "external_value",
        "external_wishlist",
        "external_series",
        "auto_steal",
        "rt",
    }
    if route not in routes:
        raise ValueError("Unsupported diagnostic route")
    result = inspect_message(message)
    embed = message.embeds[0] if message.embeds else None
    name = (getattr(getattr(embed, "author", None), "name", "") or "").lower()
    description = getattr(embed, "description", "") or ""
    series = description.splitlines()[0].lower() if description else ""
    wishlist = name in client.wishlist
    series_match = bool(series) and any(
        item in series for item in client.series_wishlist
    )
    value = result["kakera_value"]
    minimum = 0 if ignore_limit else client.min_kakera
    threshold = client.kakera_snipe_threshold
    reason = "below_threshold"
    eligible = False
    if not result["character_embed"]:
        reason = "not_character"
    elif not result["legacy_claim_option"]:
        reason = "no_legacy_claim_option"
    elif route == "own_reactive":
        minimum = client.current_min_kakera_for_roll_claim
        enabled = (
            client.rolling_enabled
            and client.enable_reactive_self_snipe
            and client.is_actively_rolling
            and client.claim_right_available
        )
        eligible = bool(
            enabled
            and (
                wishlist
                or series_match
                or reactive_value_target(
                    value, client.kakera_snipe_mode_active, threshold, minimum
                )
            )
        )
        reason = (
            "route_inactive"
            if not enabled
            else (
                "wishlist_exception"
                if wishlist
                else (
                    "series_exception"
                    if series_match
                    else "value_thresholds" if eligible else reason
                )
            )
        )
    elif route in ("post_roll", "rt"):
        enabled = (
            (key_only or claimed_post) and client.rt_available
            if route == "rt"
            else client.claim_right_available or key_only
        )
        eligible = bool(
            enabled
            and ((wishlist and route == "post_roll") or meets_minimum(value, minimum))
        )
        reason = (
            "route_inactive"
            if not enabled
            else (
                "wishlist_exception"
                if wishlist and route == "post_roll"
                else "roll_minimum" if eligible else reason
            )
        )
    else:
        mode = {
            "external_value": client.kakera_snipe_mode_active,
            "external_wishlist": client.snipe_mode,
            "external_series": client.series_snipe_mode,
            "auto_steal": client.auto_steal_enabled,
        }[route]
        enabled = mode and not client.is_actively_rolling
        target = (
            meets_minimum(value, threshold)
            if route == "external_value"
            else (
                wishlist
                if route == "external_wishlist"
                else (
                    series_match
                    if route == "external_series"
                    else wishlist or series_match
                )
            )
        )
        eligible = bool(enabled and target)
        reason = (
            "route_inactive"
            if not enabled
            else (
                "target_not_matched"
                if not target
                else (
                    "external_value_threshold"
                    if route == "external_value"
                    else "wishlist_exception" if wishlist else "series_exception"
                )
            )
        )
    result.update(
        route=route,
        eligible=eligible,
        reason=reason,
        min_kakera=client.min_kakera,
        effective_minimum=minimum,
        snipe_threshold=threshold,
        scope="selection_only",
        action="not_observed",
    )
    return result


class DiagnosticRecorder:
    """Write sanitized snapshots only when explicitly invoked locally."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.previous = OrderedDict()
        self.sequence = 0

    def record(self, message, client, route, **context):
        snapshot = evaluate_selection(message, client, route, **context)
        message_key = hashlib.sha256(str(message.id).encode("utf-8")).hexdigest()[:16]
        preset_key = hashlib.sha256(
            str(client.preset_name).encode("utf-8")
        ).hexdigest()[:16]
        key = (preset_key, message_key, route)
        with self.lock:
            if self.previous.get(key) == snapshot:
                return False
            self.sequence += 1
            entry = dict(
                snapshot,
                message_key=message_key,
                preset_key=preset_key,
                sequence=self.sequence,
            )
            with open(self.path, "a", encoding="utf-8") as destination:
                destination.write(json.dumps(entry, sort_keys=True) + "\n")
            self.previous[key] = snapshot
            self.previous.move_to_end(key)
            while len(self.previous) > 2048:
                self.previous.popitem(last=False)
            return True
