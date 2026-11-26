"""Optional ALSA capture. Formats must match the installed I2S driver."""
import math
import os
import select
import subprocess
import tempfile
import time


def capture(device, rate=48000, on_level=None):
    import numpy as np
    # Fixed 2s bounded subprocess. INMP441 left slot, S32_LE stereo container.
    cmd = ["arecord", "-q", "-D", device, "-t", "raw", "-f", "S32_LE",
           "-c", "2", "-r", str(rate), "-d", "2"]
    raw = bytearray()
    levels = []
    step = max(1, rate // 10) * 8
    end = step
    with tempfile.TemporaryFile() as errors, subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors) as proc:
        deadline = time.monotonic() + 5
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([proc.stdout], [], [], remaining)[0]:
                    raise TimeoutError('마이크 측정 시간 초과')
                chunk = os.read(proc.stdout.fileno(), step)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) >= end:
                    block = np.frombuffer(raw[end-step:end], dtype='<i4')[::2].astype(float) / 2**31
                    levels.append(round(20 * math.log10(max(float(np.sqrt(np.mean(block**2))), 1e-12)), 1))
                    if on_level:
                        on_level(levels[-1])
                    end += step
            if proc.wait(timeout=max(.01, deadline-time.monotonic())):
                errors.seek(0)
                raise ValueError(errors.read(1000).decode(errors='replace'))
        finally:
            if proc.poll() is None:
                proc.kill()
    if len(raw) != rate * 2 * 2 * 4:
        raise ValueError("마이크 샘플 길이 불일치: ALSA 형식/채널/샘플레이트 확인")
    samples = np.frombuffer(raw, dtype="<i4").reshape(-1, 2)[:, 0].astype(float) / 2**31
    peak = float(np.max(np.abs(samples)))
    if peak == 0:
        raise ValueError("마이크 왼쪽 채널이 무음(모두 0): L/R·배선·드라이버 확인")
    rms = float(np.sqrt(np.mean(samples**2)))
    return {"rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2),
            "levels_dbfs": levels,
            "peak_dbfs": round(20 * math.log10(peak), 2),
            "clipping_ratio": float(np.mean(np.abs(samples) >= 0.999)),
            "source": "alsa_left_s32le", "device": device,
            "note": "dB SPL 아님. 드라이버의 24비트 정렬과 채널을 실제 녹음으로 검증하세요."}
