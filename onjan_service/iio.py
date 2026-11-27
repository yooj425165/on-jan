"""Integrated GPIO sensors are kernel-owned IIO devices, not DMA clients."""
from pathlib import Path
from collections import deque
from statistics import median
import threading
import time
from .pour import CUP_MAX_CM

from onjan.sensors import filtered_mean
from onjan.service import HardwareService
from onjan.weight import Weight


def device(name, root=Path('/sys/bus/iio/devices')):
    for path in root.glob('iio:device*'):
        if (path / 'name').read_text().strip() == name:
            return path
    raise OSError(f'{name}: IIO 장치 없음. onjan_service/README.md의 커널 설정 확인')


class LoadCell:
    def __init__(self):
        self.lock = threading.RLock()
        self.raw = device('hx711') / 'in_voltage0_raw'

    def average(self, count=5):
        with self.lock:
            return filtered_mean([int(self.raw.read_text()) for _ in range(count)])


class IioHardware(HardwareService):
    track_negative = None
    checking_empty = None
    track_waiting = None
    empty_limit_cm = CUP_MAX_CM

    def empty_platform_distance(self):
        with self.lock:
            d = self.state.get('distance', {})
            return (d.get('ok') and 0 <= time.time()-d['updated_at'] <= 1 and
                    self.empty_limit_cm < d['data']['cm'] <= 400)

    def start_gpio(self, offset=None):
        try:
            self.weight = Weight(LoadCell(), self.config.calibration_path.with_name('iio-calibration.json'),
                                 self.config.change_g, startup_zero=True)
            self.weight.offset = offset
            self.weight.empty_check = self.empty_platform_distance
            self.weight.track_negative = self.track_negative
            self.weight.checking_empty = self.checking_empty
            self.weight.track_waiting = self.track_waiting
        except Exception as exc:
            self.error('weight', exc)
        else:
            self._launch('weight', self.weight.read)
        try:
            path = device('srf04')
        except Exception as exc:
            self.error('distance', exc)
        else:
            recent = deque(maxlen=3)
            def distance():
                # Linux srf04 raw distance is millimetres (scale = 0.001 metres).
                try:
                    raw = int((path / 'in_distance_raw').read_text()) / 10
                    if not 2 <= raw <= 400:
                        raise ValueError('초음파 측정 범위 밖')
                except (ValueError, OSError):
                    recent.clear()
                    raise
                now = time.monotonic()
                while recent and now - recent[0][0] > 1:
                    recent.popleft()
                recent.append((now, time.time(), raw))
                cm = median(v for _, _, v in recent) if len(recent) == 3 else raw
                return {'cm': cm, 'raw_cm': raw, 'near': cm <= self.config.near_cm,
                        'samples': [(stamp, v) for _, stamp, v in recent]}
            self._launch('distance', distance)

    def _launch(self, name, reader):
        thread = threading.Thread(target=self._poll, args=(name, reader, self.gpio_stop), name=name)
        self.gpio_threads.append(thread)
        thread.start()
