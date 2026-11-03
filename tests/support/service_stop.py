"""Virtual stop event with a controllable clock for service tests."""


class VirtualStop:
    def __init__(self, now):
        self.now = now
        self.stopped = False
        self.waits = []
        self.on_wait = None

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        if self.stopped:
            return True
        self.waits.append(seconds)
        self.now += seconds
        if self.on_wait:
            self.on_wait()
        return self.stopped
