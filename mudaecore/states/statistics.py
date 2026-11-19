import datetime
import math
import threading

from mudaecore.i18n import t


class SessionStatistics:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.facts = {}
            self.confirmed = set()

    def observe(self, preset, message):
        data = getattr(message, "statistics", {})
        event = getattr(message, "translation_key", None)
        with self.lock:
            facts = self.facts.setdefault((threading.current_thread(), preset), {})
            if event == "rolls_parsed" and isinstance(data.get("rolls"), int):
                facts["rolls"] = data["rolls"]
            if event == "claim_ready":
                facts.update(available=True, deadline=None)
            elif event in ("claim_cooldown", "snipe_confirmed"):
                facts.update(available=False, deadline=data.get("deadline"))
            if event == "snipe_confirmed" and isinstance(data.get("confirmation"), int):
                self.confirmed.add((preset, data["confirmation"]))
            if event in (
                "connection_lost",
                "connection_restart",
                "client_crash",
                "instance_crash",
            ):
                facts.clear()

    def rows(self, entries, now=None):
        now = now or datetime.datetime.now(datetime.timezone.utc)
        with self.lock:
            facts = [
                self.facts.get((entry["thread"], entry["name"]), {})
                for entry in entries
            ]
            rolls = (
                sum(f["rolls"] for f in facts)
                if facts and all("rolls" in f for f in facts)
                else "--"
            )
            remaining = []
            for fact in facts:
                deadline = fact.get("deadline")
                if fact.get("available"):
                    remaining.append(0)
                elif (
                    isinstance(deadline, datetime.datetime)
                    and deadline.tzinfo is not None
                ):
                    remaining.append(
                        max(0, math.ceil((deadline - now).total_seconds() / 60))
                    )
                else:
                    remaining.append(None)
            if 0 in remaining:
                claim = t("stats_available")
            elif remaining and all(value is not None for value in remaining):
                claim = f"{min(remaining)} min"
            else:
                claim = "--"
            return [
                (t("stats_claims"), str(len(self.confirmed))),
                (t("stats_rolls"), str(rolls)),
                (t("stats_next"), claim),
            ]


statistics = SessionStatistics()
