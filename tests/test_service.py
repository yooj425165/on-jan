import unittest
from unittest.mock import Mock, patch

from onjan_service.automation import Automation
from onjan_service.runtime import Runtime
from onjan_service.web import create_app


class IntegrationTests(unittest.TestCase):
    def test_one_cycle_requires_removal_and_recovers_from_error(self):
        machine = Automation()
        machine.enable(True)
        for now in (0, 1):
            machine.update(0, now)
        self.assertEqual(machine.state, "waiting")
        for now in (2, 3, 4, 5, 6):
            machine.update(250, now)
        self.assertEqual(machine.cycles, 1)
        machine.update(250, 100)
        self.assertEqual(machine.state, "wait_removal")
        machine.update(None, 101)
        machine.update(250, 102)
        self.assertEqual(machine.state, "wait_removal")
        self.assertFalse(machine.snapshot()["pwm_enabled"])

    def test_invalid_or_stale_sensor_rejected(self):
        with self.assertRaises(ValueError):
            Runtime.valid_data({"sensors": {"weight": {"ok": True, "stale": True}}}, "weight")

    def test_api_returns_job_without_waiting(self):
        runtime = Mock()
        runtime.submit.return_value = "job-1"
        runtime.snapshot.return_value = {"phase": "ready"}
        client = create_app(runtime).test_client()
        page = client.get("/").get_data(as_text=True)
        token = page.split('const token = "')[1].split('"')[0]
        self.assertEqual(client.post('/api/commands/tare', json={}).status_code, 403)
        response = client.post('/api/commands/tare', json={}, headers={"X-Onjan-Token": token})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(client.get('/api/status').status_code, 200)

    def test_manual_prediction_and_play(self):
        runtime = Runtime("default", hardware=False)
        runtime.phase = "manual_only"
        runtime.recommender = Mock()
        runtime.recommender.predict.return_value = {"recommendations": []}
        result = runtime._perform('predict', {"source": "manual", "lux": 50, "weight_g": 250, "distance_cm": 15})
        self.assertEqual(result['input_source'], 'manual')
        self.assertFalse(result['microphone_used_by_model'])
        with patch.object(runtime.hw.player, 'play') as play:
            runtime._perform('play', {'file': 'bach_aria.wav'})
            play.assert_called_once_with('bach_aria.wav')
        runtime.pool.shutdown()


if __name__ == '__main__':
    unittest.main()
