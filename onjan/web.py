"""Run one process only: python -m onjan.web."""
import argparse
import logging
import secrets
import signal
import threading

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from .config import Config
from .service import HardwareService
from .recommendation import Recommendation


def create_app(service):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    token = secrets.token_urlsafe(32)
    control_lock = threading.Lock()
    recommendation = Recommendation()

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    def index():
        return render_template("index.html", token=token)

    @app.get("/api/status")
    def status():
        return jsonify(service.snapshot())

    @app.post("/api/<action>")
    def control(action):
        if request.headers.get("X-Onjan-Token") != token:
            return jsonify(error="페이지를 새로고침하세요."), 403
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify(error="JSON object required"), 400
        if not control_lock.acquire(blocking=False):
            return jsonify(error="다른 명령 처리 중입니다."), 409
        try:
            if action in ("tare", "calibrate", "factor"):
                if service.weight is None:
                    raise ValueError("HX711 초기화 실패. 로그 확인 후 서버를 재시작하세요.")
                if action == "tare":
                    result = service.weight.tare()
                elif action == "calibrate":
                    result = service.weight.calibrate(data.get("grams"))
                else:
                    with service.weight.sensor.lock:
                        service.weight.set_factor(data.get("counts_per_g"))
                    result = {"counts_per_g": service.weight.factor}
            elif action == "predict":
                result = recommendation.predict(data)
            elif action == "play":
                service.player.play(data.get("file"))
                result = service.player.status()
            elif action == "stop":
                service.player.stop()
                result = service.player.status()
            else:
                return jsonify(error="지원하지 않는 명령 (서보 웹 제어 비활성화)"), 404
            return jsonify(result)
        except (ValueError, TypeError, OSError, TimeoutError) as exc:
            logging.getLogger(__name__).warning("%s: %s", action, exc)
            return jsonify(error=str(exc)), 400
        finally:
            control_lock.release()

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5008)
    parser.add_argument("--audio-device", default=Config.audio_device)
    for name, interval in Config().intervals.items():
        parser.add_argument(f"--{name}-interval", type=float, default=interval)
    args = parser.parse_args()
    config = Config(audio_device=args.audio_device)
    for name in config.intervals:
        value = getattr(args, f"{name}_interval")
        if not 0.1 <= value <= 3600:
            parser.error("측정 주기는 0.1~3600초여야 합니다.")
        config.intervals[name] = value
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = HardwareService(config)

    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        service.start()
        create_app(service).run(host=args.host, port=args.port, threaded=False,
                                debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        service.close()


if __name__ == "__main__":
    main()
