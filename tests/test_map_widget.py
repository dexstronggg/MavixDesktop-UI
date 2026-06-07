"""Тесты чистой математики карты (проекция, дистанция, парсинг телеметрии).

Рендер требует дисплея и здесь не проверяется — только пригодные к headless
функции.
"""
from __future__ import annotations

import math

from mavixdesktop.ui.screens.map_widget import (
    TILE_SIZE,
    haversine_m,
    lonlat_to_world_px,
    telemetry_to_args,
)


def test_world_px_center_of_world():
    # (0,0) на зуме 0 — центр единственного тайла 256×256.
    x, y = lonlat_to_world_px(0.0, 0.0, 0)
    assert math.isclose(x, TILE_SIZE / 2, abs_tol=1e-6)
    assert math.isclose(y, TILE_SIZE / 2, abs_tol=1e-6)


def test_world_px_longitude_scales_linearly():
    # Долгота +180° = правый край мира.
    x, _ = lonlat_to_world_px(0.0, 180.0, 0)
    assert math.isclose(x, TILE_SIZE, abs_tol=1e-6)


def test_world_px_zoom_doubles_resolution():
    x0, _ = lonlat_to_world_px(0.0, 0.0, 0)
    x1, _ = lonlat_to_world_px(0.0, 0.0, 1)
    assert math.isclose(x1, x0 * 2, abs_tol=1e-6)


def test_haversine_one_degree_latitude():
    # 1° широты ≈ 111.19 км.
    d = haversine_m(0.0, 0.0, 1.0, 0.0)
    assert abs(d - 111195) < 50


def test_haversine_same_point_is_zero():
    assert haversine_m(55.75, 37.61, 55.75, 37.61) == 0.0


def test_telemetry_to_args_valid():
    assert telemetry_to_args({'lat': 55.7, 'lon': 37.6, 'heading': 90.0}) == (55.7, 37.6, 90.0)


def test_telemetry_to_args_heading_defaults_zero():
    assert telemetry_to_args({'lat': 1.0, 'lon': 2.0}) == (1.0, 2.0, 0.0)


def test_telemetry_to_args_missing_coords_returns_none():
    assert telemetry_to_args({'heading': 10.0}) is None
    assert telemetry_to_args({'lat': 'x', 'lon': 1.0}) is None
