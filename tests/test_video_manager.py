"""VideoManager: frames are delivered on arrival, newest wins over queued ones."""
from __future__ import annotations

import sys

import pytest

from mavixdesktop.ui.managers.video import VideoManager


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def manager(qapp):
    shown: list = []
    vm = VideoManager(on_frame=shown.append)
    vm._track_ids = ['t0', 't1']
    return vm, shown


def _pump(qapp):
    qapp.processEvents()


def test_get_frame_returns_new_frame_once(manager):
    vm, _ = manager
    vm._publish('t0', 'кадр-1')
    assert vm.get_frame(0) == 'кадр-1'
    assert vm.get_frame(0) is None


def test_get_frame_returns_newest_when_ui_lagged(manager):
    vm, _ = manager
    vm._publish('t0', 'старый')
    vm._publish('t0', 'свежий')
    assert vm.get_frame(0) == 'свежий'
    assert vm._coalesced == 1


def test_delivers_on_arrival(qapp, manager):
    vm, shown = manager
    vm.start()
    vm._publish('t0', 'кадр')
    _pump(qapp)
    assert shown == ['кадр']


def test_newest_wins_when_ui_is_busy(qapp, manager):
    vm, shown = manager
    vm.start()
    vm._publish('t0', 'первый')
    vm._publish('t0', 'второй')
    vm._publish('t0', 'третий')
    _pump(qapp)
    assert shown == ['третий']
    assert vm._coalesced == 2


def test_nothing_delivered_while_stopped(qapp, manager):
    vm, shown = manager
    vm.stop()
    vm._publish('t0', 'кадр')
    _pump(qapp)
    assert shown == []


def test_start_shows_pending_frame(qapp, manager):
    vm, shown = manager
    vm.stop()
    vm._publish('t0', 'ждал')
    vm.start()
    _pump(qapp)
    assert shown == ['ждал']


def test_inactive_camera_frames_are_not_shown(qapp, manager):
    vm, shown = manager
    vm.start()
    vm._publish('t1', 'вторая камера')
    _pump(qapp)
    assert shown == []


def test_switching_camera_shows_its_pending_frame(qapp, manager):
    vm, shown = manager
    vm.start()
    vm._publish('t1', 'вторая камера')
    _pump(qapp)
    vm.shift_cam(1)
    _pump(qapp)
    assert shown == ['вторая камера']
    assert vm.cam_index == 1


def test_counters_reset_after_logging(qapp, manager):
    vm, _ = manager
    vm.start()
    vm._publish('t0', 'кадр')
    _pump(qapp)
    assert (vm._decoded, vm._rendered) == (1, 1)
    vm._log_stats()
    assert (vm._decoded, vm._rendered, vm._coalesced) == (0, 0, 0)
