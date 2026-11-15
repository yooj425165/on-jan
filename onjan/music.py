"""Reuse the existing WAV player and its ALSA device selection."""
import importlib.util

from .config import ROOT

# Python may have a standard-library package named "test"; load by exact path.
_spec = importlib.util.spec_from_file_location("onjan_legacy_music", ROOT / "test" / "music_web.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
MUSIC_DIR, Player = _module.MUSIC_DIR, _module.Player


def tracks():
    return sorted(p.name for p in MUSIC_DIR.glob("*.wav")
                  if p.is_file() and not p.is_symlink())
