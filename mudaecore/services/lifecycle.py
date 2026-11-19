from mudaecore.i18n import t
import threading
import time
from mudaecore.services.runtime import run_bot
from mudaecore.logs.console import print_log


def bot_lifecycle_wrapper(preset_name, preset_data):
    while True:
        try:
            run_bot(
                preset_data["token"],
                preset_data["prefix"],
                preset_data["channel_id"],
                preset_data["roll_command"],
                preset_data["min_kakera"],
                preset_data["delay_seconds"],
                preset_data["mudae_prefix"],
                print_log,
                preset_name,
                preset_data.get("key_mode", False),
                preset_data.get("start_delay", 0),
                preset_data.get("snipe_mode", False),
                preset_data.get("snipe_delay", 2),
                preset_data.get("snipe_ignore_min_kakera_reset", False),
                preset_data.get("wishlist", []),
                preset_data.get("series_snipe_mode", False),
                preset_data.get("series_snipe_delay", 3),
                preset_data.get("series_wishlist", []),
                preset_data.get("roll_speed", 0.4),
                preset_data.get("kakera_snipe_mode", False),
                preset_data.get("kakera_snipe_threshold", 0),
                preset_data.get("reactive_snipe_on_own_rolls", True),
                preset_data.get("rolling", True),
                preset_data.get("kakera_reaction_snipe_mode", False),
                preset_data.get("kakera_reaction_snipe_delay", 0.75),
                preset_data.get("kakera_reaction_snipe_targets", []),
                preset_data.get("humanization_enabled", False),
                preset_data.get("humanization_window_minutes", 40),
                preset_data.get("humanization_inactivity_seconds", 5),
                preset_data.get("dk_power_management", False),
                preset_data.get("skip_initial_commands", False),
                preset_data.get("use_slash_rolls", False),
                preset_data.get("only_chaos", False),
                preset_data.get("reactive_snipe_delay", 0),
                preset_data.get("auto_pokeslot", False),
                preset_data.get("pokeslot_interval_minutes", 60),
                preset_data.get("auto_steal", False),
                preset_data.get("steal_delay", 0.5),
                preset_data.get("guild_id", None),
            )
        except Exception as e:
            print_log(t("instance_crash", error=e), preset_name, "ERROR")

        time.sleep(60)


def start_preset_thread(preset_name, preset_data):
    if not preset_data.get("token"):
        return None
    t = threading.Thread(
        target=bot_lifecycle_wrapper, args=(preset_name, preset_data), daemon=True
    )
    t.start()
    return t
