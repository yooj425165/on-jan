"""PCA9685 channels 0/1. No automatic positioning or power detection."""
import threading
import time


class Servos:
    roles = {0: "motor_1", 1: "motor_2"}

    def __init__(self, i2c, config):
        self.i2c, self.c = i2c, config
        self.lock = threading.Lock()
        self.angles = {0: None, 1: None}
        self.ready = False
        self.stopping = threading.Event()

    def _write(self, reg, value):
        self.i2c.bus.write_byte_data(0x40, reg, value)

    def disable(self):
        with self.i2c.lock:
            self._write(0xFD, 0x10)  # ALL_LED_OFF full-off
        self.ready = False

    def probe(self):
        with self.i2c.lock:
            mode = self.i2c.bus.read_byte_data(0x40, 0x00)
            if not self.ready:
                self.disable()
        return {"address": "0x40", "mode": mode, "pwm_enabled": self.ready,
                "locked": not (self.c.servo_enabled and self.c.servo_power_confirmed)}

    def _enable(self):
        if not (self.c.servo_enabled and self.c.servo_power_confirmed):
            raise PermissionError("서보 잠금: 외부 전원 확인과 명시적 활성화가 모두 필요합니다.")
        if self.stopping.is_set():
            raise RuntimeError("서보 종료 중")
        if not self.ready:
            with self.i2c.lock:
                self.disable()
                self._write(0x00, 0x10)
                self._write(0xFE, 121)  # nominal 25MHz / 4096 / 50Hz - 1
                self._write(0x00, 0x20)
                time.sleep(0.005)
                for channel in range(16):
                    self._write(0x09 + 4 * channel, 0x10)
                # ALL_LED writes broadcast to every channel. Clear full-off
                # only for the selected channel in _angle().
                self.ready = True

    def _pulse_bytes(self, angle):
        c = self.c
        pulse = c.servo_min_us + (angle / c.servo_travel_deg) * (c.servo_max_us - c.servo_min_us)
        ticks = round(pulse * 4096 / 20000)
        return [0, 0, ticks & 255, ticks >> 8]

    def _angle(self, channel, angle):
        with self.i2c.lock:
            self.i2c.bus.write_i2c_block_data(0x40, 0x06 + channel * 4,
                                           self._pulse_bytes(angle))
        self.angles[channel] = angle

    def tilt_cycle(self, stop):
        home, tilted = (180, 180), (100, 50)
        if not all(self.c.servo_min_angle <= a <= self.c.servo_max_angle for a in (*home, *tilted)):
            raise ValueError('동작 각도가 설정 범위를 벗어납니다.')

        def pair(angles):
            if stop.is_set():
                raise RuntimeError('동작 중단')
            # Adjacent channel registers, one auto-increment I2C transaction.
            with self.i2c.lock:
                self.i2c.bus.write_i2c_block_data(0x40, 0x06,
                    self._pulse_bytes(angles[0]) + self._pulse_bytes(angles[1]))
            self.angles.update(enumerate(angles))

        def wait(seconds):
            if stop.wait(max(0, seconds)):
                raise RuntimeError('동작 중단')

        def ramp(start, end):
            t0 = time.monotonic()
            for step in range(1, 201):
                wait(t0 + step * .02 - time.monotonic())
                u = step / 200
                progress = u*u*(3 - 2*u)
                pair(tuple(a + (b-a)*progress for a, b in zip(start, end)))

        with self.lock:
            try:
                self._enable()
                pair(home)
                wait(.6)
                ramp(home, tilted)
                wait(3)
                ramp(tilted, home)
                wait(.6)
            finally:
                self.disable()

    def move(self, channel, angle, duration=1.0):
        c = self.c
        if channel not in self.roles or not c.servo_min_angle <= angle <= c.servo_max_angle:
            raise ValueError("서보 채널 또는 각도 범위 오류")
        if not 0 <= duration <= 10:
            raise ValueError("이동 시간은 0~10초")
        with self.lock:
            self._enable()
            start = self.angles[channel]
            if start is None:  # No position feedback: first command cannot be smoothed.
                self._angle(channel, angle)
                return
            steps = max(1, round(duration / 0.02))
            for step in range(1, steps + 1):
                if self.stopping.is_set():
                    return
                self._angle(channel, start + (angle - start) * step / steps)
                self.stopping.wait(duration / steps)

    def motor_1(self, angle, duration=1):
        self.move(0, angle, duration)

    def motor_2(self, angle, duration=1):
        self.move(1, angle, duration)

    def home(self):
        for channel in self.roles:
            self.move(channel, self.c.servo_initial_angle)

    def close(self):
        self.stopping.set()
        with self.lock:
            self.disable()
