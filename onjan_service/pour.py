"""Feedback-controlled, bounded bench pour. Units: seconds, grams, degrees."""
from collections import deque
from statistics import median
import threading
import time

DOSE_G = 22.0
CUP_MIN_CM = 7.0
CUP_MAX_CM = 11.0
REFERENCE_TOLERANCE_G = 5.0


class TargetReached(Exception):
    pass


class Pour:
    def __init__(self, sample, report, stop, cup_issue, clock=time.monotonic):
        self.sample, self.report, self.stop, self.clock = sample, report, stop, clock
        self.cup_issue = cup_issue
        self.cancel = threading.Event()

    def check(self):
        if self.cancel.is_set() or self.stop.is_set():
            raise ValueError('정지 요청')

    def stable(self, seconds=8, wait_for_cup=False):
        window = deque(maxlen=7)
        end = self.clock() + seconds
        detail = '측정 표본 부족'
        last = None
        while self.clock() < end:
            self.check()
            issue = self.cup_issue()
            if issue:
                if not wait_for_cup:
                    raise ValueError(issue)
                detail = issue
                window.clear()
                last = None
                self.cancel.wait(.08)
                continue
            stamp, g = self.sample()
            if stamp != last:
                window.append((stamp, g))
                last = stamp
            detail = f'연속 표본 {len(window)}/7개'
            if len(window) == 7 and window[-1][0] - window[0][0] >= 2:
                v = [x for _, x in window]
                detail = f'무게 범위 {max(v)-min(v):.2f}g (허용 2g), 앞뒤 중앙값 차이 {abs(median(v[-3:])-median(v[:3])):.2f}g (허용 0.6g)'
                if max(v)-min(v) <= 2 and abs(median(v[-3:])-median(v[:3])) <= .6:
                    return median(v)
            self.cancel.wait(.08)
        raise ValueError(f'{seconds}초 내 안정화 실패: {detail}')

    def run(self, servo):
        # Session-local zero: do not change HX711 calibration or tare during flow.
        baseline = self.stable(wait_for_cup=True)
        target = baseline + DOSE_G
        limit = self.clock()+90
        angles = (180,180)
        flow = False
        reason = '각도 한계까지 목표 미도달'

        def watch():
            self.check()
            issue = self.cup_issue()
            if issue:
                raise ValueError(issue)
            if self.clock() >= limit:
                raise ValueError('90초 시간 제한')
            stamp, g = self.sample()
            if g < baseline-3:
                raise ValueError(f'시작 대비 {g-baseline:+.2f}g (중단 기준 −3g 미만)')
            # A false early return is preferable to pouring through an overload.
            if g >= target:
                raise TargetReached
            return stamp, g

        def move(to, duration, returning=False):
            nonlocal angles
            start, t0 = angles, self.clock()
            while True:
                if self.stop.is_set():
                    raise ValueError('서버 종료')
                if not returning:
                    watch()
                u = min(1, (self.clock()-t0)/duration)
                k = u*u*(3-2*u)
                angles = tuple(a+(b-a)*k for a,b in zip(start,to))
                servo.command_pair(angles)
                if u >= 1: break
                self.stop.wait(.04)

        def observe():
            # Exclude motion and ring-down; use only new, distinct post-settle samples.
            nonlocal flow
            settled = self.clock()+1
            while self.clock()<settled:
                watch(); self.cancel.wait(.08)
            stamps, values = set(), []
            first_stamp = self.sample()[0]
            end = self.clock()+4
            while self.clock()<end:
                stamp,g=watch()
                if stamp>first_stamp and stamp not in stamps:
                    stamps.add(stamp); values.append(g)
                if len(values)>=5:
                    m=median(values)
                    if any(b < a-2 for a,b in zip(values,values[1:])):
                        raise ValueError(f'연속 표본 무게 감소 {max(a-b for a,b in zip(values,values[1:])):.2f}g (허용 2g)')
                    if median(abs(x-m) for x in values)>2 and not all(a<=b for a,b in zip(values,values[1:])):
                        raise ValueError(f'무게 불안정: 중앙절대편차 {median(abs(x-m) for x in values):.2f}g (허용 2g), 비단조 증가')
                    if m<baseline-2:
                        raise ValueError(f'중앙값이 시작 대비 {m-baseline:+.2f}g (중단 기준 −2g 미만)')
                    rising = median(values[-2:])-median(values[:2]) >= 1.0 and min(values[-3:]) >= baseline+3
                    flow = flow or rising
                    self.report('유입 추정' if flow else '유입 탐색', angles, m-baseline)
                    return rising
                self.cancel.wait(.08)
            raise ValueError(f'4초 내 새 무게 표본 {len(values)}/5개')

        with servo.lock:
            watch()
            try:
                self.check(); servo._enable(); servo.command_pair(angles)
                self.report('시작 위치 · 주입량 영점 설정', angles, 0.0)
                if self.cancel.wait(.6): self.check()
                positions = [(100,50)] + [(100,b) for b in range(40,-1,-10)] + [(a,0) for a in range(90,-1,-10)]
                for index,to in enumerate(positions):
                    self.report('기울이는 중', to, None)
                    move(to, 4 if index==0 else .7)
                    # If weight is already increasing, do not increase the pour rate.
                    while observe():
                        self.report('현재 각도 유지 · 무게 증가 중', angles, None)
                raise ValueError(reason)
            except TargetReached:
                reason='목표선 감지 · 복귀 후 검증'
            except Exception as exc:
                reason = f'모터 명령각 {angles[0]:.1f}° / {angles[1]:.1f}°에서 중단: {exc}'
                raise ValueError(reason) from exc
            finally:
                try:
                    if servo.ready and not self.stop.is_set():
                        self.report(f'복귀 중 · {reason}', angles, None); move((180,180),1.5,True); self.stop.wait(.4)
                except Exception as exc:
                    reason = f'{reason} · 복귀 실패: {exc}'
                    raise RuntimeError(reason) from exc
                finally:
                    try:
                        servo.disable()
                    except Exception as exc:
                        raise RuntimeError(f'{reason} · PWM 해제 실패: {exc}') from exc
        final = self.stable() - baseline
        if final < DOSE_G-REFERENCE_TOLERANCE_G:
            raise ValueError(f'복귀 후 {final:.1f}g: 순간 피크로 종료, 목표 도달 미확인')
        if final > DOSE_G+REFERENCE_TOLERANCE_G:
            raise ValueError(f'복귀 후 {final:.1f}g: 목표 허용 범위 초과')
        self.report('복귀 후 목표 확인', (180,180), final)
        return {'reason':'복귀 후 목표 확인','flow_detected':flow,'added_g':final}
