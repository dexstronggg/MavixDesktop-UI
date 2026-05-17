"""VideoWidget tests: numpy → QImage → QPixmap conversion under offscreen QPA."""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_initial_state_is_no_video(qapp):
    from mavixdesktop.ui.video_widget import VideoWidget
    w = VideoWidget()
    assert w.text() == 'no video'
    assert w.pixmap().isNull()


def test_show_valid_bgr_frame(qapp):
    from mavixdesktop.ui.video_widget import VideoWidget
    w = VideoWidget()
    w.resize(640, 480)
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    img[:, :, 0] = 255  # blue channel maxed (BGR)
    w.show_frame(img)
    assert not w.pixmap().isNull()
    assert w.text() == ''


def test_show_frame_resizes_to_widget(qapp):
    from mavixdesktop.ui.video_widget import VideoWidget
    w = VideoWidget()
    w.resize(800, 600)
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    w.show_frame(img)
    pix = w.pixmap()
    # Must fit inside the widget while preserving aspect ratio (4:3)
    assert pix.width() <= 800
    assert pix.height() <= 600


def test_show_frame_rejects_none(qapp):
    from mavixdesktop.ui.video_widget import VideoWidget
    w = VideoWidget()
    w.show_frame(None)
    assert w.pixmap().isNull()


def test_show_frame_rejects_wrong_shape(qapp):
    from mavixdesktop.ui.video_widget import VideoWidget
    w = VideoWidget()
    bad = np.zeros((100, 100), dtype=np.uint8)  # grayscale, 2-D
    w.show_frame(bad)
    assert w.pixmap().isNull()


def test_show_frame_rejects_wrong_channels(qapp):
    from mavixdesktop.ui.video_widget import VideoWidget
    w = VideoWidget()
    bad = np.zeros((100, 100, 4), dtype=np.uint8)  # BGRA
    w.show_frame(bad)
    assert w.pixmap().isNull()


def test_clear_frame_restores_no_video(qapp):
    from mavixdesktop.ui.video_widget import VideoWidget
    w = VideoWidget()
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    w.show_frame(img)
    assert w.text() == ''

    w.clear_frame()
    assert w.pixmap().isNull()
    assert w.text() == 'no video'


def test_repeated_frames_update_pixmap(qapp):
    from mavixdesktop.ui.video_widget import VideoWidget
    w = VideoWidget()
    w.resize(320, 240)
    a = np.zeros((120, 160, 3), dtype=np.uint8)
    b = np.full((120, 160, 3), 200, dtype=np.uint8)
    w.show_frame(a)
    pix_a_key = w.pixmap().cacheKey()
    w.show_frame(b)
    pix_b_key = w.pixmap().cacheKey()
    assert pix_a_key != pix_b_key
