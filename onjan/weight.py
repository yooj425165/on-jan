"""Persist only the measured counts/gram factor; tare each startup."""
import json
import math
import time
from collections import deque
from statistics import median


class Weight:
    def __init__(self, sensor, path, threshold, startup_zero=False):
        self.sensor, self.path, self.threshold = sensor, path, threshold
        self.factor = None
        self.offset = None
        self.previous = None
        self.startup_zero = startup_zero
        self.empty_check = None
        self.track_negative = None
        self.checking_empty = None
        self.track_waiting = None
        self.rezero = False
        self.window = deque()
        if path.exists():
            self.set_factor(json.loads(path.read_text())["counts_per_g"], save=False)

    def set_factor(self, value, save=True):
        value = float(value)
        if not math.isfinite(value) or value == 0:
            raise ValueError("보정 계수는 0이 아닌 유한한 counts/g 값이어야 합니다.")
        if save:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"counts_per_g": value}))
            temporary.replace(self.path)
        self.factor, self.previous = value, None

    def tare(self):
        with self.sensor.lock:
            self.offset = self.sensor.average(15)
            self.previous = None
        return {"offset": self.offset}

    def calibrate(self, grams):
        grams = float(grams)
        if not math.isfinite(grams) or grams <= 0:
            raise ValueError("실제 무게추의 양수 g 값을 입력하세요.")
        with self.sensor.lock:
            if self.offset is None:
                raise ValueError("먼저 빈 플랫폼에서 영점을 조정하세요.")
            self.set_factor((self.sensor.average(15) - self.offset) / grams)
        return {"counts_per_g": self.factor}

    def read(self):
        with self.sensor.lock:
            try:
                raw = self.sensor.average()
            except Exception:
                self.window.clear()
                raise
            if self.startup_zero and self.factor is not None:
                drift = (self.offset is not None and self.track_negative and self.track_negative()
                         and (raw-self.offset)/self.factor <= -.5)
                empty = self.empty_check is None or self.empty_check()
                startup_drift = (self.offset is not None and self.checking_empty and self.checking_empty()
                                 and 5 < (raw-self.offset)/self.factor <= 10)
                if (empty and self.track_waiting and self.track_waiting() and self.offset is not None
                        and (raw-self.offset)/self.factor <= 5):
                    # Check for arrival against the previous zero before following empty drift.
                    self.offset = raw
                    self.previous = None
                    self.window.clear()
                elif (empty and
                        (self.offset is None or drift or startup_drift or
                         (self.rezero and abs((raw-self.offset)/self.factor) <= 5))):
                    self._observe_zero(raw, time.monotonic())
                else:
                    self.window.clear()
            grams = None if self.factor is None or self.offset is None else (raw - self.offset) / self.factor
            delta = None if grams is None or self.previous is None else grams - self.previous
            self.previous = grams
            return {"raw": raw, "g": grams, "delta_g": delta,
                    "changed": delta is not None and abs(delta) >= self.threshold,
                    "counts_per_g": self.factor, "tared": self.offset is not None}

    def _observe_zero(self, raw, now):
        if self.window and now - self.window[-1][0] > 2:
            self.window.clear()
        self.window.append((now, raw))
        while len(self.window) > 1 and self.window[1][0] <= now - 1.5:
            self.window.popleft()
        if len(self.window) < 4 or now - self.window[0][0] < 1.5:
            return
        values = [v for _, v in self.window]
        center = median(values)
        if max(abs(v-center) for v in values) <= .3 * abs(self.factor):
            self.offset = center
            self.rezero = False
            self.previous = None
            self.window.clear()
