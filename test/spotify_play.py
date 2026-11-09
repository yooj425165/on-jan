"""Search for a track and play it on a Spotify Connect device."""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


def track_uri(value):
    if value.startswith("spotify:track:"):
        track_id = value.removeprefix("spotify:track:")
    else:
        url = urlparse(value)
        if url.scheme != "https" or url.netloc != "open.spotify.com":
            raise ValueError("Use a Spotify track URI or https://open.spotify.com/track/... URL.")
        match = re.fullmatch(r"/(?:intl-[a-zA-Z-]+/)?track/([A-Za-z0-9]{22})/?", url.path)
        if not match:
            raise ValueError("The URL must point to a single Spotify track.")
        track_id = match.group(1)
    if not re.fullmatch(r"[A-Za-z0-9]{22}", track_id):
        raise ValueError("Invalid Spotify track ID.")
    return f"spotify:track:{track_id}"


def select_device(devices, requested):
    available = [device for device in devices if device.get("id") and not device.get("is_restricted")]
    if requested:
        matches = [device for device in available if device["id"] == requested]
        if not matches:
            matches = [device for device in available if device["name"].casefold() == requested.casefold()]
    else:
        matches = [device for device in available if device.get("is_active")]
        if not matches and len(available) == 1:
            matches = available
    if len(matches) != 1:
        raise ValueError("Open Spotify, run --devices, then select a device with --device ID.")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--query", help="Song title and artist; plays the first search result")
    source.add_argument("--uri", help="Spotify track URI or track URL")
    source.add_argument("--devices", action="store_true", help="List Spotify Connect devices")
    parser.add_argument("--device", help="Exact device name or device ID")
    args = parser.parse_args()
    if not (args.query or args.uri or args.devices):
        parser.error("Specify --query, --uri, or --devices.")

    try:
        uri = track_uri(args.uri) if args.uri else None
    except ValueError as error:
        parser.error(str(error))

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        print("Install dependencies: python -m pip install -r test/requirements-spotify.txt", file=sys.stderr)
        return 1

    missing = [name for name in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET") if not os.environ.get(name)]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        cache_dir = Path.home() / ".cache" / "onjan"
        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                redirect_uri=os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
                scope="user-read-playback-state user-modify-playback-state",
                cache_path=str(cache_dir / "spotify-token.json"),
            ),
            requests_timeout=15,
        )
        devices = client.devices().get("devices", [])
        if args.devices:
            if not devices:
                print("No devices found. Open the Spotify app and sign in with the same account.")
            for device in devices:
                print(f"{device['name']} | id={device.get('id')} | "
                      f"active={device.get('is_active')} | restricted={device.get('is_restricted')}")
            return 0

        device = select_device(devices, args.device)
        if args.query:
            results = client.search(q=args.query, type="track", limit=1, market="from_token")
            tracks = results.get("tracks", {}).get("items", [])
            if not tracks:
                raise ValueError("No matching tracks found. Try a song title and artist.")
            track = tracks[0]
            uri = track["uri"]
            artists = ", ".join(artist["name"] for artist in track["artists"])
            print(f"Selected: {track['name']} - {artists}")
        client.start_playback(device_id=device["id"], uris=[uri])
        print(f"Playback requested on {device['name']}: {uri}")
        return 0
    except spotipy.SpotifyException as error:
        hints = {
            401: "Authentication failed. Check your Spotify app settings and sign in again.",
            403: "Check Spotify Premium, app user access, and device playback restrictions.",
            404: "Device unavailable. Open Spotify and check --devices again.",
            429: "Spotify rate limit reached. Wait before retrying.",
        }
        print(f"Spotify API error ({error.http_status}): "
              f"{hints.get(error.http_status, 'The playback request failed.')}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
