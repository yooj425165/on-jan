"""Weight-triggered, one-shot motion preview; no physical PWM output."""
import math


class Automation:
    def __init__(self, threshold=200, release=150, dwell=1, limit=300, max_active=30):
        self.threshold, self.release, self.dwell = threshold, release, dwell
        self.limit, self.max_active = limit, max_active
        self.started = None
        self.reason = None
        self.enabled = False
        self.state = "disabled"
        self.since = None
        self.cycles = 0

    def enable(self, enabled):
        self.enabled = enabled
        # Require removal first, including after errors or calibration.
        self.state = "wait_removal" if enabled else "disabled"
        self.since = None
        self.started = None
        self.reason = None

    def update(self, grams, now, near=None):
        if not self.enabled:
            return
        valid = grams is not None and math.isfinite(grams) and isinstance(near, bool)
        # Once returning, complete the preview even if sensor readings disappear.
        if self.state == "returning":
            if now - self.since >= 1:
                self.state, self.since = "wait_removal", None
                self.cycles += 1
            return
        if self.state in ("moving", "holding"):
            reason = None
            if not valid:
                reason = "sensor_unavailable"
            elif grams > self.limit:
                reason = "weight_limit_exceeded"
            elif not near or grams <= self.release:
                reason = "object_removed"
            elif now - self.started >= self.max_active:
                reason = "active_timeout"
            if reason:
                self.state, self.since, self.reason = "returning", now, reason
            elif self.state == "moving" and now - self.since >= 1:
                self.state, self.since = "holding", now
            return
        if not valid:
            self.state, self.since = "sensor_unavailable", None
            return
        if self.state == "sensor_unavailable":
            self.state = "wait_removal"
        if self.state in ("wait_removal", "waiting"):
            met = grams <= self.release if self.state == "wait_removal" else (
                self.threshold <= grams <= self.limit and near)
            if not met:
                self.since = None
                return
            if self.since is None:
                self.since = now
            if now - self.since >= self.dwell:
                self.state = "waiting" if self.state == "wait_removal" else "moving"
                self.since = now if self.state == "moving" else None
                if self.state == "moving":
                    self.started, self.reason = now, None

    def snapshot(self):
        return {"enabled": self.enabled, "state": self.state, "cycles": self.cycles,
                "mode": "simulation_only", "pwm_enabled": False,
                "threshold_g": self.threshold, "release_g": self.release,
                "dwell_s": self.dwell, "return_above_g": self.limit,
                "max_active_s": self.max_active, "return_reason": self.reason}
