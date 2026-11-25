import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

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
        p = Pour(Path(folder)/'refs.json', sample, Mock(), tick, lambda: tick.now)
        p.cancel = tick
        return p

    def test_drifting_empty_ref_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.setup_pour(d, lambda t: 75+t)
            with self.assertRaisesRegex(ValueError, '안정화'):
                p.save('empty')
            self.assertFalse(p.path.exists())

    def test_flow_and_transient_target(self):
        for rebound in (False, True):
            with self.subTest(rebound=rebound), tempfile.TemporaryDirectory() as d:
                p = self.setup_pour(d, lambda t: 75 if t<10 or (rebound and t>18) else min(95,75+(t-10)*3))
                p.path.write_text('{"empty":75,"full":95}')
                servo = Mock(ready=True, lock=threading.Lock())
                if rebound:
                    with self.assertRaisesRegex(ValueError, '미확인'):
                        p.run(servo)
                else:
                    self.assertTrue(p.run(servo)['flow_detected'])
                servo.disable.assert_called_once()
                self.assertEqual(servo.command_pair.call_args.args[0], (180,180))
