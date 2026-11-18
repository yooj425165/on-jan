import argparse
import logging
import signal

from onjan.config import Config
from .runtime import Runtime
from .web import create_app


def main():
    parser = argparse.ArgumentParser(description="ONJAN integrated local service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5008)
    parser.add_argument("--audio-device", default=Config.audio_device)
    parser.add_argument("--no-hardware", action="store_true", help="수동 AI 입력과 WAV 재생만 사용")
    parser.add_argument("--microphone", help="ALSA capture device override")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    runtime = Runtime(args.audio_device, not args.no_hardware, args.microphone)

    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    runtime.start()
    try:
        create_app(runtime).run(host=args.host, port=args.port, threaded=True,
                                debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
