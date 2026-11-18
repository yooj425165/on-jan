"""Own hardware lifecycle, async commands, and coherent application state."""
import copy
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from onjan.config import Config, ROOT
from onjan.recommendation import Recommendation
from onjan.service import HardwareService
from onjan.sensors import BH1750
from onjan.i2c import I2C
from onjan.servo import Servos
from .automation import Automation
from .microphone import capture

LOG = logging.getLogger(__name__)


class Runtime:
    def __init__(self, audio_device, hardware=True, microphone=None):
        self.hw = HardwareService(Config(audio_device=audio_device))
        self.hardware = hardware
        self.microphone = microphone
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="onjan-command")
        self.recommender = Recommendation()
        self.automation = Automation()
        self.phase = "starting"
        self.job = None
        self.prediction = None
        self.mic = {"status": "disabled" if not microphone else "waiting", "data": None}
        self.worker = threading.Thread(target=self._run, name="onjan-runtime")

    def start(self):
        self.worker.start()

    def _initialize(self):
        if not self.hardware:
            self.phase = "manual_only"
            return
        if not self.microphone:
            self.hw.start()
        else:
            # Avoid pigpio waveform/PCM interference until separately verified.
            # In this explicit mode initialize I2C only, never open pigpio.
            try:
                self.hw.i2c = I2C(1)
                self.hw.addresses = [hex(a) for a in self.hw.i2c.scan()]
                self.hw.servos = Servos(self.hw.i2c, self.hw.config)
                readers = {"light": BH1750(self.hw.i2c).read, "pca": self.hw.servos.probe}
                for name, reader in readers.items():
                    thread = threading.Thread(target=self.hw._poll, args=(name, reader))
                    self.hw.threads.append(thread)
                    thread.start()
            except Exception as exc:
                self.hw.error("light", exc)
                self.hw.error("pca", exc)
            for name in ("weight", "distance"):
                self.hw.error(name, "I2S 격리 모드: pigpio 비활성화. 동시 사용 검증 전입니다.")
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
                result = capture(self.microphone)
            except Exception as exc:
                with self.lock:
                    self.mic = {"status": "error", "data": None, "error": str(exc)}
                raise
            with self.lock:
                self.mic = {"status": "measured", "data": result, "measured_at": time.time()}
            return result

    def close(self):
        self.stop.set()
        self.worker.join()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.hw.close()
