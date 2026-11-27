"""Feedback-controlled, bounded bench pour. Units: seconds, grams, degrees."""
from collections import deque
from statistics import median
import threading
import time

DOSE_G = 25.0
CUP_MIN_CM = 2.0
CUP_MAX_CM = 13.0
SESSION_FILL_G = 42.0
REFERENCE_TOLERANCE_G = 5.0


class TargetReached(Exception):
    pass


class WaitForCup(Exception):
    """Detection lost before the first motor command."""


class Pour:
    def __init__(self, sample, report, stop, cup_issue, clock=time.monotonic):
        self.sample, self.report, self.stop, self.clock = sample, report, stop, clock
        self.cup_issue = cup_issue
        self.cancel = threading.Event()

    def check(self):
        if self.cancel.is_set() or self.stop.is_set():
            raise ValueError('정지 요청')

    def stable(self, seconds=8, wait_for_cup=False, auto_start=False, pickup_check=None):
        span_limit, drift_limit = (2.0, .8) if auto_start else (2.0, .6)
        window = deque(maxlen=7)
        end = self.clock() + seconds if seconds is not None else float('inf')
        detail = '측정 표본 부족'
        last = None
        while self.clock() < end:
            self.check()
            if pickup_check is not None and pickup_check() and abs(self.sample()[1]) <= 5:
                return None
            issue = self.cup_issue()
            if issue:
                if auto_start:
                    raise WaitForCup(issue)
                if not wait_for_cup:
                    raise ValueError(issue)
                detail = issue
                window.clear()
                last = None
                self.cancel.wait(.08)
                continue
            stamp, g = self.sample()
            if auto_start and g <= 5:
                raise WaitForCup('하중 5g 초과 대기')
            fresh = stamp != last
            if fresh:
                window.append((stamp, g))
                last = stamp
            detail = f'연속 표본 {len(window)}/7개'
            if len(window) == 7 and window[-1][0] - window[0][0] >= 2:
                v = [x for _, x in window]
                span, drift = max(v)-min(v), abs(median(v[-3:])-median(v[:3]))
                detail = f'무게 범위 {span:.2f}/{span_limit:g}g, 앞뒤 중앙값 차이 {drift:.2f}/{drift_limit:g}g'
                if span <= span_limit and drift <= drift_limit:
                    return median(v)
            if auto_start and fresh:
                self.report('잔 안정화 대기 · ' + detail, None, g)
            self.cancel.wait(.08)
        raise ValueError(f'{seconds}초 내 안정화 실패: {detail}')

    def run(self, servo, absolute=False, pickup_check=None, session_target=None):
        # Session-local zero: do not change HX711 calibration or tare during flow.
        baseline = self.stable(seconds=None, auto_start=True) if absolute else self.stable(wait_for_cup=True)
        target = None if absolute else baseline + DOSE_G
        origin = 0 if absolute else baseline
        limit = self.clock()+90
        angles = (180,180)
        flow = False
        reason = '각도 한계까지 목표 미도달'
        trend = deque(maxlen=3)

        def watch(before_motion=False):
            self.check()
            issue = self.cup_issue()
            if issue:
                if absolute and before_motion:
                    raise WaitForCup(issue)
                raise ValueError(issue)
            if self.clock() >= limit:
                raise ValueError('90초 시간 제한')
            stamp, g = self.sample()
            # A false early return is preferable to pouring through an overload.
            if g >= target:
                raise TargetReached('목표선 감지')
            if not trend or stamp > trend[-1][0]:
                trend.append((stamp, g))
            if len(trend) >= 2:
                drop = (trend[-2][1] + trend[-1][1]) / 2 - baseline
                if drop <= -5:
                    raise ValueError(f'최근 2개 평균: 시작 대비 {drop:+.2f}g (중단 기준 −5g 이하)')
            if not absolute and len(trend) == 3 and g >= target-4:
                (t0, a), (_, b), (t1, c) = trend
                if a < b < c and .3 <= t1-t0 <= 3 and g + (c-a)/(t1-t0)*1.5 >= target:
                    raise TargetReached(f'잔류 유입 예상 · {g-baseline:.1f}g에서 선복귀')
            return stamp, g

        def rapid_flow():
            if len(trend) < 2:
                return False
            (t0, g0), (t1, g1) = list(trend)[-2:]
            return g1-g0 >= 1 and g1-g0 >= 2*(t1-t0)

        def move(to, duration, returning=False, pause_on_flow=False):
            nonlocal angles
            start, t0 = angles, self.clock()
            while True:
                if self.stop.is_set():
                    raise ValueError('서버 종료')
                if not returning:
                    watch()
                    if pause_on_flow and rapid_flow():
                        return
                u = min(1, (self.clock()-t0)/duration)
                k = u*u*(3-2*u)
                angles = tuple(a+(b-a)*k for a,b in zip(start,to))
                servo.command_pair(angles)
                if u >= 1: break
                self.stop.wait(.04)

        def observe(quick=False):
            # Exclude motion and ring-down; use only new, distinct post-settle samples.
            nonlocal flow
            settled = self.clock()+(.25 if quick else 1)
            while self.clock()<settled:
                watch(); self.cancel.wait(.08)
            stamps, values = set(), []
            first_stamp = self.sample()[0]
            end = self.clock()+4
            while self.clock()<end:
                stamp,g=watch()
                if stamp>first_stamp and stamp not in stamps:
                    stamps.add(stamp); values.append(g)
                if quick and len(values)==2 and all(abs(v-baseline)<=1 for v in values) and abs(values[1]-values[0])<=.3:
                    return False
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
                    self.report('유입 추정' if flow else '유입 탐색', angles, m-origin)
                    return rising
                self.cancel.wait(.08)
            raise ValueError(f'4초 내 새 무게 표본 {len(values)}/5개')

        with servo.lock:
            if absolute:
                self.check()
                issue = self.cup_issue()
                if issue:
                    raise WaitForCup(issue)
                target = session_target(baseline)
                if baseline >= target:
                    self.report('이미 목표 도달 · 주입 생략', None, baseline)
                    return {'reason':'이미 목표 도달', 'total_g':baseline}
            try:
                watch(before_motion=True)
            except TargetReached as exc:
                raise ValueError('구동 전 이미 목표 도달') from exc
            try:
                self.check(); servo._enable(); servo.command_pair(angles)
                self.report('시작 위치 · 총무게 감시' if absolute else '시작 위치 · 주입량 영점 설정', angles, baseline-origin)
                if self.cancel.wait(.6): self.check()
                if absolute:
                    move((100,70), 2.7)
                    while True:
                        stamp, g = watch()
                        if rapid_flow():
                            flow = True
                            self.report('급격한 무게 증가 · 현재 각도 유지', angles, g)
                        if flow:
                            held = deque(maxlen=3)
                            while len(held)<3 or max(held)-min(held)>.5:
                                self.cancel.wait(.08)
                                fresh, g = watch()
                                if fresh != stamp:
                                    held.append(g)
                                    stamp = fresh
                        a,b = angles
                        if a == b == 0:
                            break
                        step = 5 if flow else 1
                        to = (a,max(0,b-step)) if b else (max(0,a-step),0)
                        if flow:
                            self.report('저속 5도 이동', to, g)
                            move(to, 1.0, pause_on_flow=True)
                        else:
                            angles = to
                            servo.command_pair(angles)
                            next_step = self.clock() + .3
                            while self.clock() < next_step:
                                watch()
                                if rapid_flow():
                                    break
                                self.cancel.wait(max(0, min(.04, next_step-self.clock())))
                else:
                    positions = [(100,b) for b in range(80,-1,-5)] + [(a,0) for a in range(95,-1,-5)]
                    for index,to in enumerate(positions):
                        self.report('기울이는 중', to, None)
                        move(to, 3.0 if index==0 else .16)
                        while observe(quick=index>0 and not flow):
                            self.report('현재 각도 유지 · 무게 증가 중', angles, None)
                raise ValueError(reason)
            except TargetReached as exc:
                reason=f'{exc} · 복귀 후 검증'
            except Exception as exc:
                reason = f'모터 명령각 {angles[0]:.1f}° / {angles[1]:.1f}°에서 중단: {exc}'
                error = ValueError if isinstance(exc, ValueError) else RuntimeError
                raise error(reason) from exc
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
        final = self.stable(wait_for_cup=bool(absolute and pickup_check),
                            pickup_check=pickup_check if absolute else None)
        if final is None:
            reason = '복귀 후 잔 수거 · 최종 무게 미확인'
            self.report(reason, (180,180), None)
            return {'reason':reason, 'flow_detected':flow, 'total_g':None}
        final -= origin
        if final < target-origin-REFERENCE_TOLERANCE_G:
            raise ValueError(f'복귀 후 {final:.1f}g: 순간 피크로 종료, 목표 도달 미확인')
        if final > target-origin+REFERENCE_TOLERANCE_G:
            raise ValueError(f'복귀 후 {final:.1f}g: 목표 허용 범위 초과')
        self.report('복귀 후 목표 확인', (180,180), final)
        return {'reason':'복귀 후 목표 확인','flow_detected':flow,('total_g' if absolute else 'added_g'):final}
