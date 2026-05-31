from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    """Шина событий: развязывает WebRTC/signalling-слой и страницы UI.

    Все асинхронные события (новые дроны, конфиг, FC, спидтест) проходят
    через этот объект, чтобы страницы не знали, кто их эмитирует.
    """

    #### Аутентификация ####################################################################
    login_succeeded = Signal()               # успешный логин / refresh
    login_failed = Signal(str)               # причина (текст для пользователя)

    #### WebRTC / signalling ###############################################################
    client_list_updated = Signal(list)       # новый список дронов
    config_received = Signal(list)           # конфиг камер получен от борта
    fc_info_received = Signal(str, str)      # fc_type, fc_name
    drone_went_offline = Signal(str)         # дрон не вернулся на связь
    connect_failed = Signal(str)             # сессия не поднялась (нет камер и т.п.)
    battery_updated = Signal(int, float)     # percent, voltage

    #### Peer-to-peer ping #################################################################
    speed_updated = Signal(float)            # rtt_ms (-1 если ещё нет данных)
