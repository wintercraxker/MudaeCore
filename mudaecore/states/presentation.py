import threading
import weakref

_lock = threading.RLock()
_evidence = weakref.WeakKeyDictionary()


def observe_event(preset, event, level):
    if event is None:
        return False
    with _lock:
        worker = threading.current_thread()
        facts = _evidence.setdefault(worker, {}).setdefault(
            preset, {"connected": False, "error": False}
        )
        before = dict(facts)
        if event == "account_ready":
            facts.update(connected=True, error=False)
        elif event in {
            "connection_lost",
            "connection_restart",
            "client_crash",
            "instance_crash",
        }:
            facts["connected"] = False
        if level.upper() == "ERROR":
            facts["error"] = True
        return facts != before


class PresetSummary:
    def __init__(self):
        self.entries = []
        self.last_report = None

    def select(self, names):
        with _lock:
            indices = []
            for name in names:
                indices.append(len(self.entries))
                self.entries.append({"name": name, "thread": None, "attempted": False})
            return indices

    def reset(self):
        from mudaecore.states.statistics import statistics

        statistics.reset()
        with _lock:
            self.entries.clear()
            self.last_report = None

    def attach(self, index, thread):
        with _lock:
            self.entries[index].update(thread=thread, attempted=True)

    def snapshot(self):
        counts = dict(
            selected=len(self.entries),
            started=0,
            ready=0,
            pending=0,
            unknown=0,
            errors=0,
            stopped=0,
        )
        with _lock:
            for entry in self.entries:
                worker = entry["thread"]
                started = worker is not None and isinstance(worker.ident, int)
                if not started:
                    counts["errors" if entry["attempted"] else "pending"] += 1
                    continue
                counts["started"] += 1
                facts = _evidence.get(worker, {}).get(entry["name"], {})
                if facts.get("error"):
                    counts["errors"] += 1
                if not worker.is_alive():
                    counts["stopped"] += 1
                    continue
                if facts.get("error"):
                    continue
                elif facts.get("connected"):
                    # Gateway readiness precedes channel/setup validation.
                    counts["unknown"] += 1
                else:
                    counts["pending"] += 1
        return counts


summary = PresetSummary()
