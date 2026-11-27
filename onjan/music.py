"""Reuse the existing WAV player and its ALSA device selection."""
import importlib.util

from .config import ROOT

# Python may have a standard-library package named "test"; load by exact path.
_spec = importlib.util.spec_from_file_location("onjan_legacy_music", ROOT / "test" / "music_web.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
MUSIC_DIR = _module.MUSIC_DIR
MOOD_FOLDERS = {'고요함':'calm', '아늑함':'cozy', '사색적':'reflective',
                '산뜻함':'refreshing', '활기참':'lively'}


def mood_files():
    root = ROOT / 'music2'
    files = {}
    for folder in MOOD_FOLDERS.values():
        directory = root / folder
        if root.is_symlink() or directory.is_symlink() or not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.suffix.lower() == '.wav' and not path.is_symlink() and path.is_file():
                files[f'{folder}/{path.name}'] = path
    return files


class Player(_module.Player):
    def track_files(self):
        return {**super().track_files(), **mood_files()}


def tracks():
    return sorted([p.name for p in MUSIC_DIR.glob('*.wav') if p.is_file() and not p.is_symlink()] + list(mood_files()))
