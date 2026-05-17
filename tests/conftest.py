"""pytest-wide setup for MavixDesktop tests."""
import os

# Ensure module-level Settings() initialisation doesn't fail when the
# project .env is missing required vars (it isn't required — every field
# has a default — but we set safe values just in case).
os.environ.setdefault('SIGNAL_URL', 'http://localhost:8000')

# Run pygame and Qt with dummy/offscreen drivers so tests don't need a display.
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
