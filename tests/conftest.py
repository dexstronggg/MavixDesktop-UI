"""pytest-wide setup for MavixDesktop tests."""
import os

os.environ.setdefault('SIGNAL_URL', 'http://localhost:8000')
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
