"""Download two licensed, unmodified WAV recordings from Wikimedia Commons."""

import json
from pathlib import Path
import shutil
import urllib.parse
import urllib.request
import wave

ROOT = Path(__file__).resolve().parents[1] / "music"
SOURCES = [
    ("bach_aria.wav", "File:Bach, JS - Aria (Goldberg Variations) (Piano Performance by eldüendesüarez).wav"),
    ("bach_gavotte.wav", "File:Bach, JS - Gavotte (French Suite No-5) (Piano Performance by eldüendesüarez).wav"),
]


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(
        url, headers={"User-Agent": "ONJAN-local-music-test/1.0"}), timeout=60)


def main():
    ROOT.mkdir(exist_ok=True)
    records = []
    for filename, title in SOURCES:
        params = urllib.parse.urlencode(dict(action="query", format="json", titles=title,
                                            prop="imageinfo", iiprop="url|extmetadata"))
        with fetch("https://commons.wikimedia.org/w/api.php?" + params) as response:
            page = next(iter(json.load(response)["query"]["pages"].values()))
        info = page["imageinfo"][0]
        metadata = info["extmetadata"]
        if metadata["LicenseShortName"]["value"] != "CC BY-SA 4.0":
            raise ValueError("License changed; review the source page before downloading.")
        path = ROOT / filename
        if not path.exists():
            temporary = path.with_suffix(".part")
            try:
                with fetch(info["url"]) as response, temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
                with wave.open(str(temporary), "rb") as audio:
                    if audio.getnframes() == 0:
                        raise ValueError("Empty WAV")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        records.append(dict(file=filename, title=title.removeprefix("File:"),
                            performer="eldüendesüarez", composer="Johann Sebastian Bach",
                            license="CC BY-SA 4.0", license_url=metadata["LicenseUrl"]["value"],
                            source=info["descriptionurl"], download=info["url"], changes="None"))
        print(f"Ready: {path}")
    (ROOT / "sources.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Attribution saved in music/sources.json")


if __name__ == "__main__":
    main()
