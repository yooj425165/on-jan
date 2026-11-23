import argparse
import logging
import signal

from onjan.config import Config
from .runtime import Runtime
from .web import create_app


def main(total=False):
    parser = argparse.ArgumentParser(description="ONJAN integrated local service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5008)
    parser.add_argument("--audio-device", default=Config.audio_device)
    parser.add_argument("--no-hardware", action="store_true", help="수동 AI 입력과 WAV 재생만 사용")
    parser.add_argument("--microphone", help="ALSA capture device override")
    parser.add_argument("--confirm-external-power", action="store_true", help="외부 서보 전원 확인 후 수동 시험 허용")
    if total:
        parser.add_argument('--travel', type=int, choices=(180, 360), default=180,
                            help='위치 제어 서보의 실제 범위 (기본 180도)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    runtime = Runtime(args.audio_device, not args.no_hardware, args.microphone,
                      args.confirm_external_power, travel=getattr(args, 'travel', None))

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
