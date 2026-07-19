"""State of the current drone connection session."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionState:
    cameras: list = field(default_factory=list)
    cam_index: int = 0
    fc_type: str = 'none'
    fc_name: str = ''
    selected_drone_id: str | None = None

    def reset(self) -> None:
        self.cameras = []
        self.cam_index = 0
        self.fc_type = 'none'
        self.fc_name = ''
        self.selected_drone_id = None
