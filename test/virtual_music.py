"""Generate a short synthetic melody without external packages or accounts."""

import argparse
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import wave


SAMPLE_RATE = 22050
PRESETS = {
    "calm": (80, [60, 64, 67, 71, 67, 64, 62, 60]),
    "energetic": (150, [60, 67, 64, 72, 69, 67, 74, 72]),
}


def create_music(path, mood, seconds):
    bpm, notes = PRESETS[mood]
    beat = 60 / bpm
    frames = bytearray()
    total = int(SAMPLE_RATE * seconds)
    for index in range(total):
        time = index / SAMPLE_RATE
        note = notes[int(time / beat) % len(notes)]
        frequency = 440 * 2 ** ((note - 69) / 12)
        position = time % beat
        # Short attack/release envelopes prevent clicks between notes.
        envelope = max(0, min(1, position / 0.02, (beat - position) / 0.08))
        fade = min(1, time / 0.1, (seconds - time) / 0.3)
        tone = math.sin(2 * math.pi * frequency * position)
        tone += 0.2 * math.sin(4 * math.pi * frequency * position)
        sample = int(32767 * 0.2 * tone * envelope * fade)
        frames.extend(struct.pack("<h", sample))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(frames)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mood", choices=PRESETS, default="calm")
    parser.add_argument("--seconds", type=float, default=12)
    parser.add_argument("--output", type=Path, help="WAV destination; defaults to the system temporary directory")
    parser.add_argument("--play", action="store_true", help="Play using afplay (macOS) or aplay (Linux)")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 120:
        parser.error("--seconds must be between 1 and 120.")

    path = args.output or Path(tempfile.gettempdir()) / "onjan-music" / f"{args.mood}.wav"
    try:
        create_music(path, args.mood, args.seconds)
        print(f"Synthetic melody saved: {path.resolve()}")
        print(f"Mood: {args.mood} | Duration: {args.seconds:g}s")
        if args.play:
            player = shutil.which("afplay" if sys.platform == "darwin" else "aplay")
            if not player:
                print("No supported player found. Open the WAV file with an audio player.", file=sys.stderr)
                return 1
            subprocess.run([player, str(path.resolve())], check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Audio test failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
