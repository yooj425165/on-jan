"""Optional ALSA capture. Formats must match the installed I2S driver."""
import math
import subprocess


def capture(device, rate=48000):
    import numpy as np
    # Fixed 2s bounded subprocess. INMP441 left slot, S32_LE stereo container.
    result = subprocess.run(
        ["arecord", "-q", "-D", device, "-t", "raw", "-f", "S32_LE",
         "-c", "2", "-r", str(rate), "-d", "2"],
        capture_output=True, timeout=5, check=False)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace")[:1000])
    if len(result.stdout) != rate * 2 * 2 * 4:
        raise ValueError("마이크 샘플 길이 불일치: ALSA 형식/채널/샘플레이트 확인")
    samples = np.frombuffer(result.stdout, dtype="<i4").reshape(-1, 2)[:, 0].astype(float) / 2**31
    peak = float(np.max(np.abs(samples)))
    if peak == 0:
        raise ValueError("마이크 왼쪽 채널이 무음(모두 0): L/R·배선·드라이버 확인")
    rms = float(np.sqrt(np.mean(samples**2)))
    return {"rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2),
            "peak_dbfs": round(20 * math.log10(peak), 2),
            "clipping_ratio": float(np.mean(np.abs(samples) >= 0.999)),
            "source": "alsa_left_s32le", "device": device,
            "note": "dB SPL 아님. 드라이버의 24비트 정렬과 채널을 실제 녹음으로 검증하세요."}
