"""Local-network WAV controls. Audio plays on the server, not the browser."""

import argparse
import atexit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import threading

OUTPUT_DEVICE = "plughw:CARD=UACDemoV10,DEV=0"
MUSIC_DIR = Path(__file__).resolve().parents[1] / "music"
PAGE = Path(__file__).with_suffix(".html")


class Player:
    def __init__(self, device):
        self.device = device
        self.lock = threading.Lock()
        self.process = None
        self.current = None
        self.error = None
        self.log = None

    def _stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            if self.log:
                self.log.close()
            self.process = None
        self.current = None

    def stop(self):
        with self.lock:
            self._stop()
            self.error = None

    def play(self, name):
        import tempfile
        with self.lock:
            files = {p.name: p for p in MUSIC_DIR.glob("*.wav") if p.is_file() and not p.is_symlink()}
            if not isinstance(name, str) or name not in files:
                raise ValueError("Choose a WAV file from the list.")
            if not shutil.which("aplay"):
                raise ValueError("aplay not found. On Ubuntu: sudo apt install alsa-utils")
            self._stop()
            self.error = None
            self.log = tempfile.TemporaryFile()
            try:
                self.process = subprocess.Popen(
                    ["aplay", "-D", self.device, str(files[name])],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.log)
            except OSError:
                self.log.close()
                raise
            self.current = name

    def status(self):
        with self.lock:
            if self.process is not None and self.process.poll() is not None:
                if self.process.returncode:
                    self.log.seek(0)
                    self.error = self.log.read(4096).decode("utf-8", errors="replace")
                self._stop()
            return dict(playing=self.current, error=self.error, device=self.device)


def make_handler(player):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, value, content_type="application/json"):
            body = json.dumps(value, ensure_ascii=False).encode() if content_type == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self.respond(200, PAGE.read_bytes().replace(b"__TOKEN__", token.encode()), "text/html")
            elif self.path == "/api/status":
                sources = MUSIC_DIR / "sources.json"
                records = json.loads(sources.read_text(encoding="utf-8")) if sources.exists() else []
                attribution = {item["file"]: item for item in records}
                files = [dict(file=p.name, attribution=attribution.get(p.name))
                         for p in sorted(MUSIC_DIR.glob("*.wav")) if p.is_file() and not p.is_symlink()]
                self.respond(200, dict(player.status(), tracks=files))
            else:
                self.respond(404, dict(error="Not found"))

        def do_POST(self):
            # JSON plus a page-specific token blocks cross-site form requests.
            if self.headers.get("X-Onjan-Token") != token:
                self.respond(403, dict(error="Reload the control page."))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
                if self.path == "/api/play":
                    player.play(data.get("file"))
                elif self.path == "/api/stop":
                    player.stop()
                else:
                    self.respond(404, dict(error="Not found"))
                    return
                self.respond(200, player.status())
            except (ValueError, OSError) as error:
                self.respond(400, dict(error=str(error)))

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5007)
    args = parser.parse_args()
    player = Player(OUTPUT_DEVICE)
    atexit.register(player.stop)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(player))
    print(f"Open http://<raspberry-pi-IP>:{args.port} | Output: {OUTPUT_DEVICE}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        player.stop()


if __name__ == "__main__":
    main()
