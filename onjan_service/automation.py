"""Weight-triggered, one-shot motion preview; no physical PWM output."""
import math


class Automation:
    def __init__(self, threshold=200, release=150, dwell=1):
        self.threshold, self.release, self.dwell = threshold, release, dwell
        self.enabled = False
        self.state = "disabled"
        self.since = None
        self.cycles = 0

    def enable(self, enabled):
        self.enabled = enabled
        # Require removal first, including after errors or calibration.
        self.state = "wait_removal" if enabled else "disabled"
        self.since = None

    def update(self, grams, now):
        if not self.enabled:
            return
        if grams is None or not math.isfinite(grams):
            self.state, self.since = "sensor_unavailable", None
            return
        if self.state == "sensor_unavailable":
            self.state = "wait_removal"
        if self.state in ("wait_removal", "waiting"):
            met = grams <= self.release if self.state == "wait_removal" else grams >= self.threshold
            if not met:
                self.since = None
                return
            if self.since is None:
                self.since = now
            if now - self.since >= self.dwell:
                self.state = "waiting" if self.state == "wait_removal" else "moving"
                self.since = now if self.state == "moving" else None
        elif now - self.since >= 1:
            self.state = {"moving": "holding", "holding": "returning", "returning": "wait_removal"}[self.state]
            if self.state == "wait_removal":
                self.cycles += 1
            self.since = now

    def snapshot(self):
        return {"enabled": self.enabled, "state": self.state, "cycles": self.cycles,
                "mode": "simulation_only", "pwm_enabled": False,
                "threshold_g": self.threshold, "release_g": self.release,
                "dwell_s": self.dwell}
