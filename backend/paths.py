"""Separate read-only application assets from each user's persistent runtime data."""
import os
from pathlib import Path
import sys

VERSION = '0.3.0'


def resource_root():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def default_data_dir():
    if getattr(sys, 'frozen', False):
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        return base / 'PoloCopyTrade'
    return resource_root() / 'data'


def configure_bundled_browser():
    if getattr(sys, 'frozen', False):
        # Bundle builds install into Playwright's package-local browser directory.
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'
