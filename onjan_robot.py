"""Offline appliance entry point; no HTTP server or browser required."""
import logging
import signal
import threading

from onjan.config import Config
from onjan_service.runtime import Runtime


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    shutdown = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: shutdown.set())
    runtime = Runtime(Config.audio_device, motor_test=True, travel=180, auto_fill=True, offline=True)
    runtime.start()
    try:
        while runtime.phase == 'starting' and not shutdown.wait(.1):
            pass
        if shutdown.is_set():
            return
        runtime.submit('session_start', {})
        logging.info('Offline session started: ambient music and cup detection')
        while not shutdown.wait(.25):
            with runtime.lock:
                if not runtime.session_on or runtime.phase == 'error':
                    raise RuntimeError(runtime.session_note)
    finally:
        runtime.close()


if __name__ == '__main__':
    main()
