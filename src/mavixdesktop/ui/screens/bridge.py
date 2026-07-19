from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    login_succeeded = Signal()
    login_failed = Signal(str)

    client_list_updated = Signal(list)
    config_received = Signal(list)
    fc_info_received = Signal(str, str)
    drone_went_offline = Signal(str)
    connect_failed = Signal(str)
    battery_updated = Signal(int, float)

    speed_updated = Signal(float)
