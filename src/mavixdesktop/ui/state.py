"""Состояние текущей сессии подключения к дрону.

Собирает в одном месте все данные, которые меняются во время работы:
какие камеры есть, какая активна, тип FC, ID выбранного дрона.
"""
from dataclasses import dataclass, field


@dataclass
class SessionState:
    """Изменяемое состояние одной сессии (токен → дрон → полёт).

    Создаётся при запуске App и сбрасывается при disconnect.
    """
    cameras: list = field(default_factory=list)   # конфиг камер от борта
    cam_index: int = 0                             # индекс активной камеры
    fc_type: str = 'none'                          # 'crsf' | 'mavlink' | 'none'
    fc_name: str = ''                              # имя FC-устройства
    selected_drone_id: str | None = None           # ID дрона к которому подключены

    def reset(self):
        """Сбросить состояние при отключении от дрона."""
        self.cameras = []
        self.cam_index = 0
        self.fc_type = 'none'
        self.fc_name = ''
        self.selected_drone_id = None
