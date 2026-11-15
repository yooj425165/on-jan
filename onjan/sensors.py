"""BH1750, HX711 and HC-SR04P drivers. No fabricated readings on failure."""
import math
import statistics
import threading
import time


def filtered_mean(values):
    """Median/MAD rejection followed by averaging accepted samples."""
    center = statistics.median(values)
    mad = statistics.median(abs(x - center) for x in values)
    kept = [x for x in values if abs(x - center) <= max(1, 3 * mad)]
    return statistics.mean(kept)


class BH1750:
    def __init__(self, i2c):
        self.i2c = i2c

    def read(self):
        from smbus2 import i2c_msg
        for address in (0x23, 0x5C):
            try:
                with self.i2c.lock:
                    self.i2c.bus.write_byte(address, 0x20)  # one-shot high resolution
                time.sleep(0.18)
                with self.i2c.lock:
                    message = i2c_msg.read(address, 2)
                    self.i2c.bus.i2c_rdwr(message)
                high, low = list(message)
                return {"lux": ((high << 8) | low) / 1.2, "address": hex(address)}
            except OSError:
                continue
        raise OSError("BH1750: 0x23/0x5C 응답 없음. I2C/전원/ADDR 배선을 확인하세요.")


class HX711:
    """DMA-timed clocks avoid Linux scheduling holding SCK high >60us.

    pigpiod callbacks carry sampled levels; never perform remote GPIO reads
    inside a clock callback. 25 clocks select channel A, gain 128.
    This process must be the sole pigpio waveform producer.
    """
    def __init__(self, pi, config):
        import pigpio
        self.pi, self.config = pi, config
        self.lock = threading.RLock()
        pi.set_mode(config.dout, pigpio.INPUT)
        pi.set_mode(config.clock, pigpio.OUTPUT)
        pi.write(config.clock, 0)
        self.raw()  # discard first conversion; establishes A/128

    def raw(self):
        import pigpio
        pi, c = self.pi, self.config
        deadline = time.monotonic() + 1.5
        while pi.read(c.dout):
            if time.monotonic() > deadline:
                raise TimeoutError("HX711 DOUT 준비 시간 초과: GPIO5/6 및 전원을 확인하세요.")
            time.sleep(0.002)
        bits, level, done = [], [0], threading.Event()

        def data_edge(gpio, value, tick):
            level[0] = value

        def clock_edge(gpio, value, tick):
            bits.append(level[0])
            if len(bits) == 25:
                done.set()

        data_cb = pi.callback(c.dout, pigpio.EITHER_EDGE, data_edge)
        clock_cb = pi.callback(c.clock, pigpio.FALLING_EDGE, clock_edge)
        wave = None
        try:
            pi.wave_add_new()
            pulses = []
            for _ in range(25):
                pulses.extend([pigpio.pulse(1 << c.clock, 0, 20),
                               pigpio.pulse(0, 1 << c.clock, 20)])
            pi.wave_add_generic(pulses)
            wave = pi.wave_create()
            if wave < 0:
                raise OSError(f"HX711 waveform 생성 실패: {wave}")
            pi.wave_send_once(wave)
            if not done.wait(1):
                raise TimeoutError("HX711 clock callback 시간 초과")
            while pi.wave_tx_busy():
                time.sleep(0.001)
            value = 0
            for bit in bits[:24]:
                value = (value << 1) | bit
            if value in (0x7FFFFF, 0x800000):
                raise ValueError("HX711 포화: 로드셀 연결/과부하 확인")
            return value - (1 << 24) if value & 0x800000 else value
        finally:
            pi.wave_tx_stop()
            if wave is not None and wave >= 0:
                pi.wave_delete(wave)
            pi.write(c.clock, 0)
            data_cb.cancel()
            clock_cb.cancel()

    def average(self, count=5):
        with self.lock:
            return filtered_mean([self.raw() for _ in range(count)])


class Ultrasonic:
    def __init__(self, pi, config):
        import pigpio
        self.pi, self.c = pi, config
        pi.set_mode(config.trig, pigpio.OUTPUT)
        pi.write(config.trig, 0)
        pi.set_mode(config.echo, pigpio.INPUT)

    def read(self):
        import pigpio
        pi, c = self.pi, self.c
        done, ticks = threading.Event(), []

        def edge(gpio, level, tick):
            if level == 1:
                ticks[:] = [tick]
            elif level == 0 and len(ticks) == 1:
                ticks.append(tick)
                done.set()

        if pi.read(c.echo):
            raise ValueError("초음파 ECHO가 측정 전부터 HIGH입니다. 배선을 확인하세요.")
        callback = pi.callback(c.echo, pigpio.EITHER_EDGE, edge)
        try:
            pi.gpio_trigger(c.trig, 10, 1)
            if not done.wait(0.04):
                raise TimeoutError("초음파 ECHO 시간 초과: 물체 위치/전원/배선 확인")
            cm = pigpio.tickDiff(*ticks) * 0.0343 / 2
            # Typical application acceptance bounds; verify the actual module.
            if not math.isfinite(cm) or not 2 <= cm <= 400:
                raise ValueError(f"초음파 측정 허용 범위(2~400cm) 밖: {cm:.1f}")
            return {"cm": round(cm, 2), "near": cm <= c.near_cm}
        finally:
            callback.cancel()
