"""Own hardware lifecycle, async commands, and coherent application state."""
import copy
import json
import logging
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from onjan.config import Config, ROOT
import math
from .iio import IioHardware
from .automation import Automation
from .microphone import capture

LOG = logging.getLogger(__name__)


class Runtime:
    def __init__(self, audio_device, hardware=True, microphone=None, motor_test=False):
        self.motor_test = hardware and motor_test
        self.hw = IioHardware(Config(audio_device=audio_device, servo_enabled=self.motor_test,
                                     servo_power_confirmed=self.motor_test))
        self.hardware = hardware
        self.microphone = (microphone or "plughw:CARD=sndrpigooglevoi,DEV=0") if hardware else None
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="onjan-command")
        self.catalog = json.loads((ROOT / 'music' / 'playlists.json').read_text())
        self.queue = []
        self.automation = Automation()
        self.phase = "starting"
        self.job = None
        self.selection = None
        self.mic = {"status": "disabled" if not self.microphone else "waiting", "data": None}
        self.worker = threading.Thread(target=self._run, name="onjan-runtime")

    def start(self):
        self.worker.start()

    def _initialize(self):
        if not self.hardware:
            self.phase = "manual_only"
            return
        self.hw.start()
        self.phase = "ready"

    @staticmethod
    def valid_data(snapshot, name):
        item = snapshot["sensors"].get(name, {})
        if not item.get("ok") or item.get("stale"):
            raise ValueError(f"{name}: 유효한 최신 센서값이 없습니다.")
        return item["data"]

    def _run(self):
        try:
            self._initialize()
            while not self.stop.wait(0.1):
                snapshot = self.hw.snapshot()
                try:
                    grams = self.valid_data(snapshot, "weight").get("g")
                except ValueError:
                    grams = None
                try:
                    near = self.valid_data(snapshot, "distance").get("near")
                except ValueError:
                    near = None
                with self.lock:
                    if self.queue:
                        status = self.hw.player.status()
                        if status['error']:
                            self.queue.clear()
                        elif not status['playing']:
                            try:
                                self.hw.player.play(self.queue.pop(0))
                            except (OSError, ValueError) as exc:
                                self.queue.clear()
                                self.selection['error'] = str(exc)
                    self.automation.update(grams, time.monotonic(), near)
        except Exception:
            LOG.exception("Runtime failed")
            self.phase = "error"

    def snapshot(self):
        result = self.hw.snapshot()
        with self.lock:
            result.update(phase=self.phase, job=copy.deepcopy(self.job),
                          servo_control='manual_test' if self.motor_test else 'locked',
                          selection=copy.deepcopy(self.selection), moods=list(self.catalog["lists"]),
                          automation=self.automation.snapshot(), microphone=copy.deepcopy(self.mic))
        return result

    def submit(self, action, data):
        allowed = {"measure", "choose", "play", "stop", "tare", "calibrate", "automation", "capture", "servo_probe", "servo_pulse"}
        if action not in allowed:
            raise ValueError("지원하지 않는 명령")
        with self.lock:
            if self.stop.is_set() or self.phase == "starting":
                raise ValueError("초기화 또는 종료 중입니다.")
            if self.job and self.job["status"] == "running":
                raise ValueError("이전 명령 처리 중입니다. 완료 후 다시 요청하세요.")
            job_id = uuid.uuid4().hex
            self.job = {"id": job_id, "action": action, "status": "running", "error": None}
            self.pool.submit(self._command, action, data)
            return job_id

    def _command(self, action, data):
        try:
            result = self._perform(action, data)
            with self.lock:
                self.job.update(status="done", result=result)
        except Exception as exc:
            LOG.exception("Command %s failed", action)
            with self.lock:
                self.job.update(status="error", error=str(exc))

    def _perform(self, action, data):
        if action in ('servo_probe', 'servo_pulse'):
            servo = self.hw.servos
            if servo is None:
                raise ValueError('PCA9685 사용 불가: 로직 전원 및 I2C 배선을 확인하세요.')
            if action == 'servo_probe':
                return servo.probe()
            ch, angle = data.get('channel'), data.get('angle')
            if not self.motor_test:
                raise ValueError('외부 전원 미확인: 서보 출력 잠금')
            if type(ch) is not int or ch not in (0, 1) or type(angle) is not int or angle not in (80, 90, 100):
                raise ValueError('채널 0/1, 각도 80/90/100만 허용됩니다.')
            try:
                servo.move(ch, angle, duration=0)
                self.stop.wait(.6)
            finally:
                servo.disable()
            return {'channel': ch, 'angle': angle, 'pwm': 'off'}
        if action in ('measure', 'choose'):
            if action == 'measure':
                with self.lock:
                    self.queue.clear()
                    self.hw.player.stop()
                    self.selection = None
                try:
                    sound = self._perform('capture', {})
                    lux = self.valid_data(self.hw.snapshot(), 'light')['lux']
                    rms = sound['rms_dbfs']
                    if not math.isfinite(lux) or lux < 0 or not math.isfinite(rms) or rms > 0:
                        raise ValueError('센서값 범위 오류')
                except Exception as exc:
                    raise ValueError(f'{exc} · 분위기를 직접 선택하세요.') from exc
                bright = lux >= self.catalog['bright_lux']
                loud = rms >= self.catalog['active_dbfs']
                mood = self.catalog['quadrants'][int(bright)*2 + int(loud)]
                reason = f"{lux:.1f} lux ({'밝음' if bright else '어두움'}), {rms:.1f} dBFS ({'활기참' if loud else '조용함'})"
            else:
                mood = data.get('mood')
                reason = '직접 선택'
            if not isinstance(mood, str) or mood not in self.catalog['lists']:
                raise ValueError('알 수 없는 분위기')
            available = set(self.hw.snapshot()['tracks'])
            files = [f for f in self.catalog['lists'][mood] if f in available]
            if not files:
                raise ValueError('목록에 재생 가능한 WAV가 없습니다.')
            with self.lock:
                self.hw.player.play(files[0])
                self.queue = files[1:]
                self.selection = dict(mood=mood, reason=reason, tracks=files)
                return self.selection.copy()
        if action in ('play', 'stop'):
            with self.lock:
                self.queue.clear()
                self.selection = None
                if action == 'stop':
                    self.hw.player.stop()
                else:
                    self.hw.player.play(data.get('file'))
                return self.hw.player.status()
        if action in ("tare", "calibrate"):
            with self.lock:
                self.automation.enable(False)
            if self.hw.weight is None:
                raise ValueError("HX711이 준비되지 않았습니다. 배선/데몬 확인 후 재시작하세요.")
            return self.hw.weight.tare() if action == "tare" else self.hw.weight.calibrate(data.get("grams"))
        if action == "automation":
            enabled = data.get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("enabled는 boolean이어야 합니다.")
            if enabled:
                grams = self.valid_data(self.hw.snapshot(), "weight").get("g")
                if grams is None:
                    raise ValueError("무게 보정 및 영점 조정이 필요합니다.")
                self.valid_data(self.hw.snapshot(), "distance")
            with self.lock:
                self.automation.enable(enabled)
                return self.automation.snapshot()
        if action == "capture":
            if not self.microphone:
                raise ValueError("--microphone ALSA_DEVICE 옵션으로 활성화하세요.")
            if self.hw.player.status()["playing"]:
                raise ValueError("주변 소리 측정 전에 음악을 정지하세요.")
            try:
                result = self._capture_round()
            except Exception as exc:
                with self.lock:
                    self.mic = {"status": "error", "data": None, "error": str(exc)}
                raise
            with self.lock:
                self.mic = {"status": "measured", "data": result, "measured_at": time.time()}
            return result

    def _capture_round(self):
        # Refuse mixed ownership after migration; never change system services here.
        if subprocess.run(['pgrep', '-x', 'pigpiod'], timeout=3).returncode != 1:
            raise ValueError('기존 pigpiod 실행 중: IIO 전환 안내를 확인하세요.')
        before = self.hw.snapshot()['sensors']
        def level(dbfs):
            with self.lock:
                self.mic = {'status': 'recording', 'level_dbfs': dbfs, 'data': None}
        sound = capture(self.microphone, on_level=level)
        entry = {'measured_at': time.time(), 'before_capture': before, 'microphone': sound}
        with (ROOT / 'data' / 'measurement-rounds.jsonl').open('a', encoding='utf8') as out:
            out.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return sound

    def close(self):
        self.stop.set()
        self.worker.join()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.hw.close()
