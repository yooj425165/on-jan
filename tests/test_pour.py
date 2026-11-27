import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from onjan_service.runtime import Runtime
from onjan_service.pour import Pour


class Tick:
    def __init__(self):
        self.now = 0

    def is_set(self):
        return False

    def wait(self, seconds):
        self.now += seconds
        return False


class PourTests(unittest.TestCase):
    def setup_pour(self, folder, weight):
        tick = Tick()
        def sample():
            stamp = int(tick.now * 2) / 2
            return stamp, weight(stamp)
        p = Pour(sample, Mock(), tick, lambda: None, lambda: tick.now)
        p.cancel = tick
        return p

    def test_drifting_empty_ref_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.setup_pour(d, lambda t: 75+t)
            servo = Mock()
            with self.assertRaisesRegex(ValueError, '안정화'):
                p.run(servo)
            servo._enable.assert_not_called()

    def test_stable_weight_alone_never_arms(self):
        p = self.setup_pour(None, lambda t: 75)
        p.cup_issue = lambda: '잔 감지 범위 이탈: 14.50cm'
        servo = Mock()
        with self.assertRaisesRegex(ValueError, '잔 감지'):
            p.run(servo)
        servo._enable.assert_not_called()

    def test_cup_removed_during_motion_returns(self):
        p = self.setup_pour(None, lambda t: 75)
        p.cup_issue = lambda: None if p.clock() < 5 else '잔 감지 범위 이탈: 14.50cm (허용 2~13cm)'
        servo = Mock(ready=True, lock=threading.Lock())
        with self.assertRaisesRegex(ValueError, r'모터 명령각 .*중단: 잔 감지 범위 이탈: 14\.50cm'):
            p.run(servo)
        self.assertEqual(servo.command_pair.call_args.args[0], (180,180))
        servo.disable.assert_called_once()

    def test_flow_and_transient_target(self):
        for rebound in (False, True):
            with self.subTest(rebound=rebound), tempfile.TemporaryDirectory() as d:
                p = self.setup_pour(d, lambda t: 75 if t<10 or (rebound and t>20) else min(100,75+(t-10)*3))
                servo = Mock(ready=True, lock=threading.Lock())
                if rebound:
                    with self.assertRaisesRegex(ValueError, '미확인'):
                        p.run(servo)
                else:
                    self.assertTrue(p.run(servo)['flow_detected'])
                servo.disable.assert_called_once()
                self.assertEqual(servo.command_pair.call_args.args[0], (180,180))

    def test_absolute_target_includes_cup(self):
        p = self.setup_pour(None, lambda t: 45 if t<10 else min(87,45+(t-10)*3))
        servo = Mock(ready=True, lock=threading.Lock())
        self.assertEqual(p.run(servo, absolute=True, session_target=lambda g:g+42)['total_g'], 87)
        servo.disable.assert_called_once()

    def test_full_cup_does_not_move(self):
        p = self.setup_pour(None, lambda t: 70)
        servo = Mock(lock=threading.Lock())
        result = p.run(servo, absolute=True, session_target=lambda _: 70)
        self.assertEqual(result['reason'], '이미 목표 도달')
        servo._enable.assert_not_called()

    def test_pickup_after_return_is_not_a_session_error(self):
        servo = Mock(ready=True, lock=threading.Lock())
        p = self.setup_pour(None, lambda t: 0 if servo.disable.called else min(87,45+max(0,t-10)*4))
        p.cup_issue = lambda: '잔 없음' if servo.disable.called else None
        result = p.run(servo, absolute=True, session_target=lambda g:g+42, pickup_check=lambda: servo.disable.called)
        self.assertIsNone(result['total_g'])
        self.assertIn('잔 수거', result['reason'])

    def test_target_survives_refill_and_resets_on_session_end(self):
        r = Runtime('default', auto_fill=True, motor_test=True)
        r.phase = 'ready'
        with patch.object(r.hw.player, 'stop'):
            r.submit('session_start', {})
            self.assertAlmostEqual(r._session_target(37.4), 79.4)
            self.assertAlmostEqual(r._session_target(60), 79.4)
            r.submit('session_stop', {})
            self.assertIsNone(r.full_target)
            r.submit('session_start', {})
            r.pour.cancel.clear()  # normally cleared by _auto_tick before auto_run
            self.assertEqual(r._session_target(40), 82)
