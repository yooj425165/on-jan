"""Local-network WAV controls. Audio plays on the server, not the browser."""

import argparse
import atexit
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import threading

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

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


def create_app(player=None):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    player = player if player is not None else Player(OUTPUT_DEVICE)
    app.extensions["music_player"] = player
    token = secrets.token_urlsafe(32)

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    def index():
        return Response(PAGE.read_text(encoding="utf-8").replace("__TOKEN__", token), mimetype="text/html")

    @app.get("/api/status")
    def status():
        sources = MUSIC_DIR / "sources.json"
        records = json.loads(sources.read_text(encoding="utf-8")) if sources.exists() else []
        attribution = {item["file"]: item for item in records}
        files = [dict(file=p.name, attribution=attribution.get(p.name))
                 for p in sorted(MUSIC_DIR.glob("*.wav")) if p.is_file() and not p.is_symlink()]
        return jsonify(dict(player.status(), tracks=files))

    @app.post("/api/play")
    @app.post("/api/stop")
    def control():
        # Require the control page's token before accepting playback changes.
        if request.headers.get("X-Onjan-Token") != token:
            return jsonify(error="Reload the control page."), 403
        if not request.is_json:
            return jsonify(error="Expected application/json"), 400
        try:
            data = request.get_json()
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            if request.path == "/api/play":
                player.play(data.get("file"))
            else:
                player.stop()
            return jsonify(player.status())
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 400

    @app.errorhandler(BadRequest)
    def bad_json(error):
        return jsonify(error="Invalid JSON request"), 400

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(error="Request exceeds 4096 bytes"), 413

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5007)
    args = parser.parse_args()
    player = Player(OUTPUT_DEVICE)
    atexit.register(player.stop)
    app = create_app(player)
    print(f"Open http://<raspberry-pi-IP>:{args.port} | Output: {OUTPUT_DEVICE}", flush=True)
    try:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()


if __name__ == "__main__":
    main()
