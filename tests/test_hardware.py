import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from onjan.config import Config
from onjan.sensors import filtered_mean
from onjan.servo import Servos
from onjan.service import HardwareService
from onjan.web import create_app
from onjan.weight import Weight


class HardwareTests(unittest.TestCase):
    def test_weight_requires_measured_calibration_and_new_tare(self):
        sensor = Mock(lock=threading.RLock())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            weight = Weight(sensor, path, 5)
            sensor.average.return_value = 1000
            self.assertIsNone(weight.read()["g"])
            with self.assertRaises(ValueError):
                weight.calibrate(100)
            weight.tare()
            sensor.average.return_value = 51000
            weight.calibrate(100)
            self.assertEqual(weight.read()["g"], 100)
            sensor.average.return_value = 41000
            self.assertEqual(weight.read()["delta_g"], -20)
            restored = Weight(sensor, path, 5)
            self.assertEqual(restored.factor, 500)
            self.assertIsNone(restored.read()["g"])
            for invalid in (0, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    restored.set_factor(invalid)

    def test_negative_factor_and_outlier_rejection(self):
        self.assertEqual(filtered_mean([100, 100, 100, 101, 99999]), 100.25)
        sensor = Mock(lock=threading.RLock())
        with tempfile.TemporaryDirectory() as directory:
            weight = Weight(sensor, Path(directory) / "c.json", 5)
            sensor.average.return_value = 1000
            weight.tare()
            sensor.average.return_value = -49000
            weight.calibrate(100)
            self.assertEqual(weight.factor, -500)
            self.assertEqual(weight.read()["g"], 100)

    def test_servo_requires_both_flags_before_any_write(self):
        for enabled, powered in ((False, False), (True, False), (False, True)):
            bus = Mock(lock=threading.RLock())
            servo = Servos(bus, Config(servo_enabled=enabled, servo_power_confirmed=powered))
            with self.assertRaises(PermissionError):
                servo.motor_1(90)
            bus.bus.write_byte_data.assert_not_called()
            bus.bus.write_i2c_block_data.assert_not_called()

    def test_probe_only_reads_mode_and_disables_outputs(self):
        bus = Mock(lock=threading.RLock())
        servo = Servos(bus, Config())
        self.assertTrue(servo.probe()["locked"])
        bus.bus.write_byte_data.assert_called_once_with(0x40, 0xFD, 0x10)
        with self.assertRaises(ValueError):
            servo.motor_2(181)

    def test_sensor_failure_does_not_kill_worker(self):
        service = HardwareService(Config())
        count = [0]

        def reader():
            count[0] += 1
            if count[0] == 1:
                raise OSError("disconnected")
            service.stop_event.set()
            return {"lux": 12}

        service.config.intervals["light"] = 0.001
        service._poll("light", reader)
        self.assertTrue(service.snapshot()["sensors"]["light"]["ok"])
        self.assertEqual(count[0], 2)

    def test_web_token_validation_and_no_servo_route(self):
        service = HardwareService(Config())
        client = create_app(service).test_client()
        self.assertEqual(client.get("/api/status").status_code, 200)
        self.assertEqual(client.post("/api/tare", json={}).status_code, 403)
        page = client.get("/").get_data(as_text=True)
        token = page.split('const token = "')[1].split('"')[0]
        headers = {"X-Onjan-Token": token}
        self.assertEqual(client.post("/api/tare", json={}, headers=headers).status_code, 400)
        self.assertEqual(client.post("/api/servo", json={}, headers=headers).status_code, 404)
        self.assertEqual(client.post("/api/play", json=[], headers=headers).status_code, 400)
        self.assertEqual(client.post("/api/play", json={"file":"../bad.wav"}, headers=headers).status_code, 400)


if __name__ == "__main__":
    unittest.main()
