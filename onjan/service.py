"""Independent polling workers and a JSON-friendly snapshot for UI/AI consumers."""
import copy
import logging
import threading
import time

from .i2c import I2C
from .music import Player, tracks
from .sensors import BH1750, HX711, Ultrasonic
from .servo import Servos
from .weight import Weight

LOG = logging.getLogger(__name__)


class HardwareService:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.threads = []
        self.gpio_stop = threading.Event()
        self.gpio_threads = []
        self.state = {}
        self.i2c = self.pi = self.servos = self.weight = None
        self.player = Player(config.audio_device)
        self.addresses = []
        self.readers = {}

    def error(self, name, error):
        message = str(error)
        with self.lock:
            old = self.state.get(name, {})
            if old.get("error") != message:
                LOG.warning("%s: %s", name, message)
            self.state[name] = {"ok": False, "data": None, "error": message,
                                "updated_at": time.time()}

    def start(self):
        try:
            self.i2c = I2C(self.config.i2c_bus)
            self.addresses = [hex(a) for a in self.i2c.scan()]
            LOG.info("I2C 장치: %s", self.addresses)
            self.readers["light"] = BH1750(self.i2c).read
            self.servos = Servos(self.i2c, self.config)
            self.readers["pca"] = self.servos.probe
        except Exception as exc:
            for name in ("light", "pca"):
                self.error(name, exc)
        for name, reader in self.readers.items():
            thread = threading.Thread(target=self._poll, args=(name, reader), name=name)
            self.threads.append(thread)
            thread.start()
        self.start_gpio()

    def start_gpio(self, offset=None):
        self.gpio_stop.clear()
        readers = {}
        try:
            import pigpio
            self.pi = pigpio.pi()
            if not self.pi.connected:
                raise OSError("pigpiod 연결 실패: sudo systemctl start pigpiod")
        except Exception as exc:
            for name in ("weight", "distance"):
                self.error(name, exc)
        else:
            try:
                sensor = HX711(self.pi, self.config)
                self.weight = Weight(sensor, self.config.calibration_path, self.config.change_g)
                self.weight.offset = offset
                readers["weight"] = self.weight.read
            except Exception as exc:
                self.error("weight", exc)
            try:
                readers["distance"] = Ultrasonic(self.pi, self.config).read
            except Exception as exc:
                self.error("distance", exc)
        for name, reader in readers.items():
            thread = threading.Thread(target=self._poll, args=(name, reader, self.gpio_stop), name=name)
            self.gpio_threads.append(thread)
            thread.start()

    def _poll(self, name, reader, event=None):
        event = event or self.stop_event
        while not event.is_set():
            start = time.monotonic()
            try:
                data = reader()
                with self.lock:
                    self.state[name] = {"ok": True, "data": data, "error": None,
                                        "updated_at": time.time()}
            except Exception as exc:
                self.error(name, exc)
            elapsed = time.monotonic() - start
            event.wait(max(0.05, self.config.intervals[name] - elapsed))

    def snapshot(self):
        with self.lock:
            state = copy.deepcopy(self.state)
        now = time.time()
        for name, item in state.items():
            item["age_s"] = round(now - item["updated_at"], 2)
            item["stale"] = item["age_s"] > max(3, self.config.intervals[name] * 3)
        return {"sensors": state, "i2c_addresses": self.addresses,
                "music": self.player.status(), "tracks": tracks(),
                "microphone": "disabled", "servo_control": "locked",
                "timestamp": now}

    def close(self):
        self.stop_event.set()
        self.stop_gpio()
        for thread in self.threads:
            thread.join()
        for name, cleanup in (
            ("music", self.player.stop),
            ("servo", self.servos.close if self.servos else None),
            ("I2C", self.i2c.close if self.i2c else None),
        ):
            if cleanup:
                try:
                    cleanup()
                except Exception as exc:
                    LOG.warning("%s 종료: %s", name, exc)
    def stop_gpio(self):
        self.gpio_stop.set()
        for thread in self.gpio_threads:
            thread.join()
        self.gpio_threads.clear()
        self.weight = None
        if self.pi:
            if self.pi.connected:
                import pigpio
                for pin in (self.config.clock, self.config.trig):
                    self.pi.write(pin, 0)
                for pin in (self.config.clock, self.config.trig, self.config.dout, self.config.echo):
                    self.pi.set_mode(pin, pigpio.INPUT)
            self.pi.stop()
            self.pi = None
