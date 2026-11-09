import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("music_web", Path(__file__).with_name("music_web.py"))
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "example.wav").write_bytes(b"test")
        self.paths = patch.object(web, "MUSIC_DIR", self.root)
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.player = web.Player("plughw:CARD=UACDemoV10,DEV=0")
        self.addCleanup(self.player.stop)

    @patch.object(web.subprocess, "Popen")
    @patch.object(web.shutil, "which", return_value="/usr/bin/aplay")
    def test_play_stop_and_device(self, which, popen):
        process = popen.return_value
        process.poll.return_value = None
        self.player.play("example.wav")
        self.assertEqual(popen.call_args.args[0], ["aplay", "-D", self.player.device, str(self.root / "example.wav")])
        self.assertEqual(self.player.status()["playing"], "example.wav")
        self.player.stop()
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        self.assertIsNone(self.player.status()["playing"])

    def test_reject_path_traversal(self):
        for name in ("../example.wav", "/etc/passwd", None, []):
            with self.assertRaises(ValueError):
                self.player.play(name)

    @patch.object(web.subprocess, "Popen")
    @patch.object(web.shutil, "which", return_value="/usr/bin/aplay")
    def test_aplay_failure_is_visible(self, which, popen):
        process = popen.return_value
        process.poll.return_value = None
        self.player.play("example.wav")
        self.player.log.write(b"USB device busy")
        process.poll.return_value = 1
        process.returncode = 1
        result = self.player.status()
        self.assertIsNone(result["playing"])
        self.assertIn("USB device busy", result["error"])


class WebTests(unittest.TestCase):
    def setUp(self):
        self.player = web.Player("test-device")
        self.addCleanup(self.player.stop)
        self.client = web.create_app(self.player).test_client()
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        token = page.get_data(as_text=True).split("const token='")[1].split("'")[0]
        self.headers = {"X-Onjan-Token": token}

    def test_status_and_stop(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("tracks", response.json)
        self.assertEqual(response.json["device"], "test-device")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.post("/api/stop", json={}, headers=self.headers).status_code, 200)

    def test_missing_token(self):
        self.assertEqual(self.client.post("/api/stop", json={}).status_code, 403)

    def test_invalid_requests(self):
        for data in ([], {"file": "../outside.wav"}):
            response = self.client.post("/api/play", json=data, headers=self.headers)
            self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/play", data="{", content_type="application/json", headers=self.headers)
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/play", data="x" * 5000, content_type="application/json", headers=self.headers)
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
