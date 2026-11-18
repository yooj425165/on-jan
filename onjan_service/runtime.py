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
from onjan.recommendation import Recommendation
from onjan.service import HardwareService
from .automation import Automation
from .microphone import capture

LOG = logging.getLogger(__name__)


class Runtime:
    def __init__(self, audio_device, hardware=True, microphone=None):
        self.hw = HardwareService(Config(audio_device=audio_device))
        self.hardware = hardware
        self.microphone = (microphone or "plughw:CARD=sndrpigooglevoi,DEV=0") if hardware else None
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="onjan-command")
        self.recommender = Recommendation()
        self.automation = Automation()
        self.phase = "starting"
        self.job = None
        self.prediction = None
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
                    self.automation.update(grams, time.monotonic(), near)
        except Exception:
            LOG.exception("Runtime failed")
            self.phase = "error"

    def snapshot(self):
        result = self.hw.snapshot()
        with self.lock:
            result.update(phase=self.phase, job=copy.deepcopy(self.job),
                          prediction=copy.deepcopy(self.prediction),
                          automation=self.automation.snapshot(), microphone=copy.deepcopy(self.mic))
        return result

    def submit(self, action, data):
        allowed = {"predict", "ambient", "play", "stop", "tare", "calibrate", "automation", "capture"}
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
        if action == "ambient":
            from onjan.ambient_demo import predict
            from onjan.ai_demo import TARGETS

            sound = self._perform("capture", {})
            if data.get("lux") is None:
                lux = self.valid_data(self.hw.snapshot(), "light")["lux"]
                source = "BH1750"
            else:
                lux, source = float(data["lux"]), "manual"
            scores, inputs = predict(lux, sound["rms_dbfs"])
            result = self.recommender.rank(scores, TARGETS)
            result.update(inputs=inputs, input_source=f"{source}+INMP441", created_at=time.time(),
                          model_source="synthetic_ambient_v1", microphone_used_by_model=True)
            record = {"timestamp": result['created_at'], "lux": lux, "lux_source": source,
                      **sound, "model_inputs": inputs, "recommended": result['recommendations']}
            with (ROOT / 'data' / 'ambient-features.jsonl').open('a', encoding='utf8') as log:
                log.write(json.dumps(record, ensure_ascii=False) + '\n')
            with self.lock:
                self.prediction = result
            return result
        if action == "predict":
            source = data.get("source", "manual")
            if source == "sensors":
                snapshot = self.hw.snapshot()
                data = {"lux": self.valid_data(snapshot, "light")["lux"],
                        "weight_g": self.valid_data(snapshot, "weight")["g"],
                        "distance_cm": self.valid_data(snapshot, "distance")["cm"]}
            elif source != "manual":
                raise ValueError("입력 출처는 manual 또는 sensors")
            result = self.recommender.predict(data)
            result["input_source"] = source
            result["inputs"] = data
            result["created_at"] = time.time()
            result["microphone_used_by_model"] = False
            with self.lock:
                self.prediction = result
            return result
        if action == "play":
            self.hw.player.play(data.get("file"))
            return self.hw.player.status()
        if action == "stop":
            self.hw.player.stop()
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
        unit = "onjan-pigpio.service"
        if subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", unit]).returncode:
            raise ValueError("온잔 전용 pigpiod 서비스가 필요합니다. onjan_service/README.md 설정을 확인하세요.")
        ctl = ["sudo", "-n", "/usr/bin/systemctl"]
        before = self.hw.snapshot()['sensors']
        offset = self.hw.weight.offset if self.hw.weight else None
        stopped = False
        try:
            self.hw.stop_gpio()
            for name in ('weight', 'distance'):
                self.hw.error(name, '마이크 측정으로 일시 정지')
            subprocess.run([*ctl, "stop", unit], check=True, timeout=20)
            stopped = True
            if subprocess.run(['pgrep', '-x', 'pigpiod']).returncode != 1:
                raise ValueError('다른 pigpiod가 실행 중입니다. 녹음을 건너뜁니다.')
            sound = capture(self.microphone)
            entry = {'measured_at': time.time(), 'before_capture': before, 'microphone': sound}
            with (ROOT / 'data' / 'measurement-rounds.jsonl').open('a', encoding='utf8') as out:
                out.write(json.dumps(entry, ensure_ascii=False) + '\n')
            return sound
        finally:
            # Even a failed stop request may have reached systemd (e.g. timeout).
            if stopped or subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", unit]).returncode:
                subprocess.run([*ctl, "start", unit], check=True, timeout=20)
                for _ in range(30):
                    import socket
                    try:
                        with socket.create_connection(('127.0.0.1', 8888), timeout=.2):
                            break
                    except OSError:
                        time.sleep(.1)
            self.hw.start_gpio(offset)

    def close(self):
        self.stop.set()
        self.worker.join()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.hw.close()
