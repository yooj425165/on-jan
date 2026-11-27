import unittest
from unittest.mock import Mock, patch

from onjan_service.automation import Automation
from onjan_service.runtime import Runtime
from onjan_service.web import create_app


class IntegrationTests(unittest.TestCase):
    def test_capture_failure_never_restarts_sensors(self):
        runtime = Runtime('default')
        runtime.hw = Mock()
        runtime.hw.snapshot.return_value = {'sensors': {}}
        with patch('onjan_service.runtime.subprocess.run', return_value=Mock(returncode=1)) as run, \
                patch('onjan_service.runtime.capture', side_effect=ValueError('silent')):
            with self.assertRaisesRegex(ValueError, 'silent'):
                runtime._capture_round()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ['pgrep', '-x', 'pigpiod'])
        runtime.hw.stop_gpio.assert_not_called()
        runtime.hw.start_gpio.assert_not_called()

    def test_one_cycle_requires_removal_and_recovers_from_error(self):
        machine = Automation()
        machine.enable(True)
        for now in (0, 1):
            machine.update(0, now, False)
        self.assertEqual(machine.state, "waiting")
        for now in (2, 3, 4):
            machine.update(250, now, True)
        self.assertEqual(machine.state, "holding")
        machine.update(301, 5, True)
        self.assertEqual(machine.state, "returning")
        machine.update(301, 6, True)
        self.assertEqual(machine.cycles, 1)
        machine.update(250, 100, True)
        self.assertEqual(machine.state, "wait_removal")
        machine.update(None, 101)
        machine.update(250, 102, True)
        self.assertEqual(machine.state, "wait_removal")
        self.assertFalse(machine.snapshot()["pwm_enabled"])

    def test_motion_requires_both_conditions_and_strict_limit(self):
        machine = Automation()
        machine.enable(True)
        machine.update(0, 0, False)
        machine.update(0, 1, False)
        machine.update(250, 2, False)
        machine.update(250, 4, False)
        self.assertEqual(machine.state, "waiting")
        machine.update(301, 5, True)
        machine.update(301, 7, True)
        self.assertEqual(machine.state, "waiting")
        machine.update(200, 8, True)
        machine.update(200, 9, True)
        machine.update(300, 10, True)
        self.assertEqual(machine.state, "holding")
        machine.update(300.1, 11, True)
        self.assertEqual(machine.reason, "weight_limit_exceeded")

    def test_sensor_loss_and_timeout_return(self):
        for grams, near, now, reason in [(None, True, 4, "sensor_unavailable"),
                                         (250, False, 4, "object_removed"),
                                         (250, True, 33, "active_timeout")]:
            machine = Automation()
            machine.enable(True)
            for weight, time in [(0, 0), (0, 1), (250, 2), (250, 3)]:
                machine.update(weight, time, True)
            machine.update(grams, now, near)
            self.assertEqual(machine.state, "returning")
            self.assertEqual(machine.reason, reason)

    def test_invalid_or_stale_sensor_rejected(self):
        with self.assertRaises(ValueError):
            Runtime.valid_data({"sensors": {"weight": {"ok": True, "stale": True}}}, "weight")

    def test_api_returns_job_without_waiting(self):
        runtime = Mock()
        runtime.travel = None
        runtime.submit.return_value = "job-1"
        runtime.snapshot.return_value = {"phase": "ready"}
        client = create_app(runtime).test_client()
        page = client.get("/").get_data(as_text=True)
        token = page.split('const token = "')[1].split('"')[0]
        self.assertEqual(client.post('/api/commands/tare', json={}).status_code, 403)
        response = client.post('/api/commands/tare', json={}, headers={"X-Onjan-Token": token})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(client.get('/api/status').status_code, 200)

    def test_manual_playlist_and_stop(self):
        runtime = Runtime('default', hardware=False)
        mood = next(iter(runtime.catalog['lists']))
        with patch.object(runtime.hw.player, 'play') as play:
            result = runtime._perform('choose', {'mood': mood})
            play.assert_called_once_with(result['tracks'][0])
            self.assertEqual(runtime.queue, result['tracks'][1:])
            runtime._perform('stop', {})
            self.assertFalse(runtime.queue)

    def test_sensor_quadrants(self):
        runtime = Runtime('default')
        runtime._capture_round = Mock()
        for i, (lux, rms) in enumerate([(149,-46),(149,-45),(150,-46),(150,-45)]):
            runtime._capture_round.return_value = {'rms_dbfs': rms}
            runtime.hw.state['light'] = {'data': {'lux': lux}, 'ok': True, 'updated_at': __import__('time').time()}
            with patch.object(runtime.hw.player, 'play'):
                result = runtime._perform('measure', {})
                self.assertEqual(result['mood'], runtime.catalog['quadrants'][i])

    def test_session_fallback_avoids_previous_and_stop_blocks_replay(self):
        runtime = Runtime('default')
        runtime.session_on = True
        tracks = runtime.catalog['lists'][runtime.catalog['quadrants'][0]][:2]
        runtime.previous_track = tracks[0]
        with patch.object(runtime.session_cancel, 'wait', return_value=False), \
                patch('onjan_service.runtime.capture', side_effect=ValueError('silent')), \
                patch.object(runtime.hw, 'snapshot', return_value={'tracks': tracks}), \
                patch.object(runtime.hw.player, 'play') as play:
            runtime._music_round()
            play.assert_called_once_with(tracks[1])
            runtime.submit('session_stop', {})
            runtime._music_round()
            self.assertEqual(play.call_count, 1)

    def test_offline_playback_error_does_not_cancel_pour(self):
        r = Runtime('default', offline=True, auto_fill=True, motor_test=True)
        r.session_on = True
        r.job = {'action': 'auto_run', 'status': 'running'}
        with patch.object(r.hw.player, 'status', return_value={'error': 'ALSA disconnected'}) as status:
            r._music_tick()
            r._music_tick()
        status.assert_called_once()
        self.assertTrue(r.session_on)
        self.assertFalse(r.pour.cancel.is_set())


if __name__ == '__main__':
    unittest.main()
