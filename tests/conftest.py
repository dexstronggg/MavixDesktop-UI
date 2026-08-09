"""pytest-wide setup for MavixDesktop tests."""

import os
import sys

import pytest

os.environ.setdefault('SIGNAL_URL', 'http://localhost:8000')
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


_exit_status = 0


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    global _exit_status
    _exit_status = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_exit_status)
