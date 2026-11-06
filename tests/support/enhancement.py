"""Offline fakes shared by the native Enhancement route tests."""
from pathlib import Path
from types import SimpleNamespace

from scripts.bluestacks_native_runtime import captured_native_frame_from_png


def exit_runtime(payloads):
    class Runtime:
        def __init__(self):
            self.session, self.ordinal = Path("offline-native-exit"), 0
            self.inputs, self.journal = [], []
        def capture(self, label):
            raw = payloads[self.ordinal]
            self.ordinal += 1
            return captured_native_frame_from_png(raw, path=Path(f"exit-{self.ordinal}.png"),
                captured_monotonic=float(self.ordinal))
        def tap(self, before, **kwargs):
            self.inputs.append(kwargs)
        def reconcile(self, key, status, post, reason):
            self.journal.append((key, status, post.sha256))
    runtime = Runtime()
    class Session:
        def observe(self, capture, *, label):
            return capture(label)
        def run_action(self, *, label, capture, authorize, dispatch, recognize, settled_successor, **kwargs):
            before = capture(f"{label}-immediate-before")
            authorize(before)
            dispatch(before)
            after = capture(f"{label}-immediate-post")
            state = recognize(after)
            if state == "unknown" and settled_successor:
                state = recognize(settled_successor())
            return SimpleNamespace(status="completed" if state != "unknown" else "unknown")
    return runtime, Session()


class CategorySession:
    def __init__(self):
        self.input_count = 0
        self.actions = []

    def observe(self, capture, *, label):
        return capture(label)

    def run_action(self, *, label, capture, authorize, dispatch, recognize, settled_successor, **kwargs):
        before = capture(f"{label}-immediate-before")
        authorize(before)
        self.input_count += 1
        dispatch(before)
        after = capture(f"{label}-immediate-post")
        state = recognize(after)
        if state == "unknown" and settled_successor is not None:
            after = settled_successor()
            state = recognize(after)
        self.actions.append({"label": label, "status": "completed" if state != "unknown" else "unknown"})
        return SimpleNamespace(status=self.actions[-1]["status"])
