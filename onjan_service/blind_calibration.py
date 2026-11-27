"""One-shot SD-requested calibration. Runs without starting the servo runtime."""
import json
import math
import statistics
import struct
import subprocess
import tempfile
import time
import wave

from onjan.config import Config
from .iio import LoadCell


def tone(count):
    with tempfile.NamedTemporaryFile(suffix='.wav') as f:
        with wave.open(f.name, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            beep = b''.join(struct.pack('<h', int(7000*math.sin(i*2*math.pi*700/16000))) for i in range(4800))
            wav.writeframes((beep + bytes(6400))*count)
        subprocess.run(['aplay', '-q', '-D', Config.audio_device, f.name], check=True, timeout=10)


def boot_calibration(root):
    request = root/'calibrate-grams.txt'
    if not request.exists():
        return False
    result = root/'calibration-result.txt'
    try:
        grams = float(request.read_text().strip())
        if not math.isfinite(grams) or grams <= 0:
            raise ValueError('Known positive mass required')
        sensor = LoadCell()
        def samples():
            return [sensor.average(5) for _ in range(7)]
        empty = samples()
        tone(1)
        time.sleep(10)
        loaded = samples()
        tone(2)
        time.sleep(10)
        back = samples()
        zero, full, again = map(statistics.median, (empty, loaded, back))
        delta = full-zero
        if (abs(delta) <= 10*max(1, *(max(s)-min(s) for s in (empty,loaded,back)))
                or abs(again-zero) > .05*abs(delta)):
            raise ValueError('Unstable readings, no clear load step, or empty weight did not return')
        dest = root/'data'/'iio-calibration.json'
        dest.parent.mkdir(exist_ok=True)
        tmp = dest.with_suffix('.tmp')
        tmp.write_text(json.dumps({'counts_per_g': delta/grams}, allow_nan=False))
        tmp.replace(dest)
        result.write_text(f'OK: {grams:g} g; RAW empty/load/empty = {zero}, {full}, {again}\n')
        request.unlink()
        tone(3)
    except Exception as exc:
        result.write_text(f'ERROR: {exc}\n')
        raise
    return True
