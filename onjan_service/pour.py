"""Feedback-controlled, bounded bench pour. Units: seconds, grams, degrees."""
from collections import deque
import json
import math
from statistics import median
import threading
import time

REFERENCE_TOLERANCE_G = 5.0


class TargetReached(Exception):
    pass


class Pour:
    def __init__(self, path, sample, report, stop, clock=time.monotonic):
        self.path, self.sample, self.report, self.stop, self.clock = path, sample, report, stop, clock
        self.cancel = threading.Event()

    def refs(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def check(self):
        if self.cancel.is_set() or self.stop.is_set():
            raise ValueError('정지 요청')

    def stable(self, seconds=8):
        window = deque(maxlen=7)
        end = self.clock() + seconds
        last = None
        while self.clock() < end:
            self.check()
            stamp, g = self.sample()
            if stamp != last:
                window.append((stamp, g))
                last = stamp
            if len(window) == 7 and window[-1][0] - window[0][0] >= 2:
                v = [x for _, x in window]
                if max(v)-min(v) <= 2 and abs(median(v[-3:])-median(v[:3])) <= .6:
                    return median(v)
            self.cancel.wait(.08)
        raise ValueError('무게 안정화 실패: 진동·드리프트·보정을 확인하세요.')

    def save(self, key):
        refs = self.refs()
        g = self.stable()
        if key == 'empty':
            if g <= 2:
                raise ValueError('빈 플랫폼에서 영점을 잡은 뒤 빈 잔을 올리세요.')
            refs = {'empty': g}
        elif key == 'full' and 'empty' in refs and g >= refs['empty']+10:
            refs['full'] = g
        else:
            raise ValueError('빈 잔을 먼저 저장하고 10g 이상 채워 주세요.')
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(refs, allow_nan=False)); tmp.replace(self.path)
        return refs

    def run(self, servo):
        refs = self.refs()
        empty, target = refs.get('empty'), refs.get('full')
        if not all(isinstance(g, (float,int)) and math.isfinite(g) for g in (empty,target)) or not 2 < empty <= target-10:
            raise ValueError('빈 잔과 목표 잔을 먼저 저장하세요.')
        baseline = self.stable()
        if abs(baseline-empty) > REFERENCE_TOLERANCE_G:
            raise ValueError('시작 무게가 저장한 빈 잔과 다릅니다.')
        limit = self.clock()+90
        angles = (180,180)
        flow = False
        reason = '각도 한계까지 목표 미도달'

        def watch():
            self.check()
            if self.clock() >= limit:
                raise ValueError('90초 시간 제한')
            stamp, g = self.sample()
            if g < baseline-3:
                raise ValueError('컵 제거 또는 하중 감소')
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
                        raise ValueError('무게 반동 또는 하중 감소')
                    if median(abs(x-m) for x in values)>2 and not all(a<=b for a,b in zip(values,values[1:])):
                        raise ValueError('측정 불안정: 추가 기울임 중단')
                    if m<baseline-2:
                        raise ValueError('영점 이동 또는 잔 이탈')
                    rising = median(values[-2:])-median(values[:2]) >= 1.0 and min(values[-3:]) >= baseline+3
                    flow = flow or rising
                    self.report('유입 추정' if flow else '유입 탐색', angles, m)
                    return rising
                self.cancel.wait(.08)
            raise ValueError('새 무게 샘플 부족')

        with servo.lock:
            try:
                self.check(); servo._enable(); servo.command_pair(angles)
                self.report('시작 위치', angles, baseline)
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
            finally:
                try:
                    if servo.ready and not self.stop.is_set():
                        self.report('복귀 중', angles, None); move((180,180),1.5,True); self.stop.wait(.4)
                finally:
                    servo.disable()
        final = self.stable()
        if final < target-REFERENCE_TOLERANCE_G:
            raise ValueError(f'복귀 후 {final:.1f}g: 순간 피크로 종료, 목표 도달 미확인')
        if final > target+REFERENCE_TOLERANCE_G:
            raise ValueError(f'복귀 후 {final:.1f}g: 목표 허용 범위 초과')
        self.report('복귀 후 목표 확인', (180,180), final)
        return {'reason':'복귀 후 목표 확인','flow_detected':flow,'final_g':final}
