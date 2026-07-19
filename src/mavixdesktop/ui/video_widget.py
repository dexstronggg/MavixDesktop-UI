"""Render numpy ndarray (BGR24) frames in QLabel via QImage/QPixmap."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

if TYPE_CHECKING:
    import numpy as np


class VideoWidget(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet('background-color: black;')
        self.setText('no video')

    def show_frame(self, img: np.ndarray) -> None:
        if img is None:
            return
        if img.ndim != 3 or img.shape[2] != 3:
            return
        height, width, _ = img.shape
        bytes_per_line = img.strides[0]
        qimg = QImage(img.data, width, height, bytes_per_line, QImage.Format.Format_BGR888)
        pix = QPixmap.fromImage(qimg)
        target = self.size()
        scaled = pix.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.setText('')

    def clear_frame(self) -> None:
        self.setPixmap(QPixmap())
        self.setText('no video')
