"""Own hardware lifecycle, async commands, and coherent application state."""
import copy
import json
import logging
import random
from statistics import median
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from onjan.config import Config, ROOT
import math
from .iio import IioHardware
from .automation import Automation
from .pour import CUP_MIN_CM, CUP_MAX_CM, DOSE_G, Pour, WaitForCup
from .microphone import capture

LOG = logging.getLogger(__name__)
AUTO_DISTANCE_CM = 16.0


class Runtime:
    def __init__(self, audio_device, hardware=True, microphone=None, motor_test=False, travel=None, auto_fill=False, cup_leds=False):
        if travel not in (None, 180, 360):
            raise ValueError('travel: 180 또는 360')
        self.travel = travel
        self.motor_test = hardware and motor_test
        if auto_fill and not self.motor_test:
            raise ValueError('자동 주입에는 외부 전원 확인이 필요합니다.')
        self.auto_phase = '빈 받침대 확인' if auto_fill else None
        self.hw = IioHardware(Config(audio_device=audio_device, servo_enabled=self.motor_test,
                                     servo_power_confirmed=self.motor_test, servo_travel_deg=travel or 180,
                                     servo_max_angle=travel or 180))
        self.hardware = hardware
        self.hw.config.intervals['light'] = .25
        self.session_on = False
        self.session_note = '시작 대기'
        self.session_cancel = threading.Event()
        self.previous_track = None
        self.load_since = None
        if auto_fill:
            self.hw.track_waiting = lambda: self.auto_phase == '잔 대기' and self.load_since is None
            self.hw.empty_limit_cm = AUTO_DISTANCE_CM
            self.hw.track_negative = lambda: self.auto_phase in ('잔 대기', '빈 받침대 확인', '잔 제거 대기') and self.load_since is None
        self.microphone = (microphone or "plughw:CARD=sndrpigooglevoi,DEV=0") if hardware else None
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="onjan-command")
        self.catalog = json.loads((ROOT / 'music' / 'playlists.json').read_text())
        self.queue = []
        self.automation = Automation()
        self.phase = "starting"
        self.job = None
        self.pour_state = {'dose_g': DOSE_G}
        self.pour = Pour(self._weight_sample, self._pour_report, self.stop, self._cup_issue)
        self.selection = None
        self.mic = {"status": "disabled" if not self.microphone else "waiting", "data": None}
        self.worker = threading.Thread(target=self._run, name="onjan-runtime")
        self.cup_ready = False
        self.lights = None
        if cup_leds:
            from .cup_led import CupLights
            self.lights = CupLights()

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
                    self._auto_tick()
                    self._music_tick()
                    self.cup_ready = bool(self.session_on and self.auto_phase == '잔 대기' and self.load_since is None
                                          and not (self.job and self.job['status'] == 'running')
                                          and grams is not None and abs(grams) <= 5
                                          and snapshot['sensors']['weight']['age_s'] <= 2
                                          and snapshot['sensors'].get('pca', {}).get('ok')
                                          and not snapshot['sensors']['pca']['stale']
                                          and self.hw.empty_platform_distance())
                    if self.lights:
                        self.lights.show(self.cup_ready)
        except Exception:
            LOG.exception("Runtime failed")
            self.phase = "error"
            with self.lock:
                self._end_session('시스템 오류')
        finally:
            self.cup_ready = False
            if self.lights:
                self.lights.close()

    def snapshot(self):
        result = self.hw.snapshot()
        with self.lock:
            result.update(phase=self.phase, job=copy.deepcopy(self.job),
                          pour=copy.deepcopy(self.pour_state),
                          auto_fill=self.auto_phase,
                          session={'on': self.session_on, 'note': self.session_note},
                          cup_ready=self.cup_ready,
                          servo_control='manual_test' if self.motor_test else 'locked',
                          selection=copy.deepcopy(self.selection), moods=list(self.catalog["lists"]),
                          automation=self.automation.snapshot(), microphone=copy.deepcopy(self.mic))
        return result

    def submit(self, action, data):
        allowed = {"measure", "choose", "play", "stop", "tare", "calibrate", "automation", "capture", "servo_probe", "servo_pulse", "servo_cycle"}
        allowed.update(('pour_run','pour_cancel','session_start','session_stop'))
        if action not in allowed:
            raise ValueError("지원하지 않는 명령")
        with self.lock:
            if action == 'session_stop':
                self._end_session('사용자 종료')
                return uuid.uuid4().hex
            if self.phase == 'error':
                raise ValueError('시스템 오류: 서버를 재시작하세요.')
            if self.session_on and action not in ('pour_cancel',):
                raise ValueError('시스템 실행 중: 수동 작업 전 시스템을 종료하세요.')
            if action == 'pour_cancel':
                if not self.job or self.job['action'] not in ('pour_run','auto_run') or self.job['status'] != 'running':
                    raise ValueError('진행 중인 로테이션 없음')
                self.pour.cancel.set()
                return self.job['id']
            if self.auto_phase and action in ('pour_run','servo_pulse','servo_cycle','tare','calibrate'):
                raise ValueError('자동 주입 활성 상태: 수동 작업은 --auto-fill 없이 실행하세요.')
            if self.stop.is_set() or self.phase == "starting":
                raise ValueError("초기화 또는 종료 중입니다.")
            if self.job and self.job["status"] == "running":
                raise ValueError("이전 명령 처리 중입니다. 완료 후 다시 요청하세요.")
            job_id = uuid.uuid4().hex
            if action == 'session_start':
                if not self.hardware:
                    raise ValueError('하드웨어 모드가 필요합니다.')
                self.queue.clear()
                self.hw.player.stop()
                self.session_cancel.clear()
                self.session_on = True
                self.session_note = '다음 곡 측정 대기'
                return job_id
            if action.startswith('pour_'):
                self.pour.cancel.clear()
            self.job = {"id": job_id, "action": action, "status": "running", "error": None}
            self.pool.submit(self._command, action, data)
            return job_id

    def _auto_tick(self):
        if not self.session_on or not self.auto_phase or self.stop.is_set() or (self.job and self.job['status']=='running'):
            return
        try:
            stamp, g = self._weight_sample()
        except ValueError:
            self.load_since = None
            return
        w = self.hw.weight
        if self.auto_phase == '잔 제거 대기':
            if self.hw.empty_platform_distance() and abs(g) <= 5:
                with w.sensor.lock:
                    w.window.clear()
                    w.rezero = True
                self.auto_phase = '빈 받침대 확인'
        elif self.auto_phase == '빈 받침대 확인':
            if not w.rezero and abs(g) <= 5 and self.hw.empty_platform_distance():
                self.auto_phase = '잔 대기'
        elif self.auto_phase == '잔 대기':
            if g <= 5:
                self.load_since = None
                return
            if self.load_since is None:
                self.load_since = stamp
            if self._cup_issue() is not None:
                return
            self.auto_phase = '잔 안정화 / 자동 주입'
            self.pour.cancel.clear()
            self.job = dict(id=uuid.uuid4().hex, action='auto_run', status='running', error=None)
            self.pool.submit(self._command, 'auto_run', {})

    def _command(self, action, data):
        next_phase = '잔 제거 대기'
        try:
            result = self._perform(action, data)
            outcome = dict(status='done', result=result)
        except WaitForCup as exc:
            next_phase = '잔 대기'
            outcome = dict(status='done', result={'waiting': str(exc)})
        except Exception as exc:
            LOG.exception("Command %s failed", action)
            outcome = dict(status='error', error=str(exc))
        with self.lock:
            if action in ('music_round','auto_run') and self.session_on and outcome['status']=='error':
                self._end_session(outcome['error'])
            if action == 'auto_run':
                self.auto_phase = next_phase
                self.load_since = None
            self.job.update(**outcome)

    def _end_session(self, reason):
        self.session_on = False
        self.session_note = reason
        self.session_cancel.set()
        self.pour.cancel.set()
        self.queue.clear()
        self.hw.player.stop()
        self.cup_ready = False

    def _music_tick(self):
        if not self.session_on:
            return
        status = self.hw.player.status()
        if status['error']:
            self._end_session('재생 오류: ' + status['error'])
        elif not status['playing'] and not (self.job and self.job['status']=='running'):
            self.session_note = '모터 정지 · 잔향 대기 / 환경 측정'
            self.job = dict(id=uuid.uuid4().hex, action='music_round', status='running', error=None)
            self.pool.submit(self._command, 'music_round', {})

    def _music_round(self):
        if self.session_cancel.wait(1):
            return
        try:
            sound = capture(self.microphone, seconds=3)
            rms = sound['rms_dbfs']
            start = time.time()
            deadline = time.monotonic()+1
            samples = {}
            while time.monotonic() < deadline:
                if self.session_cancel.wait(.05):
                    return
                with self.hw.lock:
                    light = self.hw.state.get('light', {})
                    if light.get('ok') and light['updated_at'] >= start:
                        samples[light['updated_at']] = light['data']['lux']
            if len(samples)<2 or not all(math.isfinite(x) and x>=0 for x in samples.values()) or not math.isfinite(rms) or rms>0:
                raise ValueError('조도 표본 부족 또는 센서값 오류')
            lux = median(samples.values())
            mood = self.catalog['quadrants'][2*int(lux>=self.catalog['bright_lux']) + int(rms>=self.catalog['active_dbfs'])]
            reason = f'{lux:.1f} lux · {rms:.1f} dBFS'
        except (OSError, ValueError, RuntimeError, ImportError) as exc:
            LOG.warning('환경 측정 실패: %s', exc)
            mood = self.catalog['quadrants'][0]
            reason = f'센서 오류 · 기본 분위기: {exc}'
        files = set(self.hw.snapshot()['tracks'])
        candidates = [f for f in self.catalog['lists'][mood] if f in files]
        if not candidates:
            raise ValueError(f'{mood}: 재생 가능한 WAV 없음')
        track = random.choice([f for f in candidates if f!=self.previous_track] or candidates)
        with self.lock:
            if not self.session_on or self.session_cancel.is_set() or self.stop.is_set():
                return
            self.hw.player.play(track)
            self.previous_track = track
            self.session_note = '재생 중 · '+track
            self.selection = dict(mood=mood, reason=reason, tracks=[track])
            return self.selection.copy()

    def _cup_issue(self):
        with self.hw.lock:
            item = self.hw.state.get('distance', {})
            cm = (item.get('data') or {}).get('cm')
            if not item.get('ok'):
                return '초음파 읽기 실패: ' + (item.get('error') or '측정값 없음')
            age = time.time()-item['updated_at']
            if not 0 <= age <= 1:
                return f'초음파 갱신 지연: {age:.2f}초 (허용 1초)'
            limit = CUP_MAX_CM
            if self.auto_phase:
                recent = [v for stamp, v in item['data'].get('samples', ())
                          if self.load_since is not None and stamp > self.load_since and 0 <= time.time()-stamp <= 1]
                if len(recent) < 3:
                    return f'하중 감지 이후 거리 표본 {len(recent)}/3개'
                cm = sum(recent)/len(recent)
                limit = AUTO_DISTANCE_CM
            if type(cm) not in (int, float) or not math.isfinite(cm):
                return f'초음파 거리값 오류: {cm!r}'
            if not CUP_MIN_CM <= cm <= limit:
                return f'잔 감지 범위 이탈: {cm:.2f}cm (허용 {CUP_MIN_CM:g}~{limit:g}cm)'
            return None

    def _weight_sample(self):
        with self.hw.lock:
            item = self.hw.state.get('weight', {})
            d = item.get('data') or {}
            g = d.get('g')
            if not item.get('ok'):
                raise ValueError('로드셀 읽기 실패: ' + (item.get('error') or '측정값 없음'))
            age = time.time()-item['updated_at']
            if not 0 <= age <= 2:
                raise ValueError(f'로드셀 갱신 지연: {age:.2f}초 (허용 2초)')
            if not d.get('tared') or not d.get('counts_per_g'):
                raise ValueError('로드셀 ' + ('영점 미설정' if not d.get('tared') else '보정 계수 없음'))
            if not isinstance(g, (int,float)) or not math.isfinite(g):
                raise ValueError(f'로드셀 무게값 오류: {g!r}')
            return item['updated_at'], g

    def _pour_report(self, phase, angles, grams):
        with self.lock:
            self.pour_state.update(phase=phase, angles=angles, grams=grams)

    def _perform(self, action, data):
        if action == 'music_round':
            return self._music_round()
        if action in ('pour_run','auto_run'):
            if not self.motor_test or not self.hw.servos:
                raise ValueError('외부 전원 확인 및 PCA9685 연결 필요')
            self.valid_data(self.hw.snapshot(),'pca')
            self._pour_report('빈 잔 안정화 대기', None, None)
            try:
                return self.pour.run(self.hw.servos, absolute=action=='auto_run')
            except WaitForCup as exc:
                self._pour_report('잔 재감지 대기 · ' + str(exc), None, None)
                raise
            except Exception as exc:
                self._pour_report('로테이션 중단 · ' + str(exc), None, None)
                raise
        if action in ('servo_probe', 'servo_pulse', 'servo_cycle'):
            servo = self.hw.servos
            if servo is None:
                raise ValueError('PCA9685 사용 불가: 로직 전원 및 I2C 배선을 확인하세요.')
            if action == 'servo_probe':
                return servo.probe()
            ch, angle = data.get('channel'), data.get('angle')
            if not self.motor_test:
                raise ValueError('외부 전원 미확인: 서보 출력 잠금')
            if action == 'servo_cycle':
                servo.tilt_cycle(self.stop)
                return {'pwm': 'off', 'angles': [180, 180]}
            if type(ch) is not int or ch not in (0, 1):
                raise ValueError('채널 0/1만 허용됩니다.')
            if self.travel is None:
                if type(angle) is not int or angle not in (80, 90, 100):
                    raise ValueError('시험 각도: 80/90/100')
            elif type(angle) not in (float, int) or not 0 <= angle <= self.travel:
                raise ValueError(f'목표 각도는 0~{self.travel}°로 입력하세요.')
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
        with self.lock:
            self._end_session('서버 종료')
        self.worker.join()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.hw.close()
