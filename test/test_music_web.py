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


if __name__ == "__main__":
    unittest.main()
