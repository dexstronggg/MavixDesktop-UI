# Changelog

Все значимые изменения станции оператора **MavixDesktop** документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
проект придерживается [семантического версионирования](https://semver.org/lang/ru/).

## [1.0.0] - 2026-06-10

Первый стабильный релиз станции оператора комплекса доставки грузов на базе БПЛА.

### Added
- Нативная карта на `QPainter` (без QtWebEngine), демо-карта на центре Ставрополя
  до получения GPS-фикса.
- Полная ГОСТ-документация и диаграммы; раздел «Принципы проектирования».
- Скрипт запуска тестов (`run_tests.sh`, offscreen), покрытие тестами поднято с 53% до 72%.
- Проприетарная лицензия (LICENSE) и история изменений (CHANGELOG).

### Fixed
- Устранено зависание окна при открытии QGroundControl.
- Быстрый hot-plug джойстика через `event.pump()` вместо `quit()`/`init()`.
- Не падать в windowed-сборке при `sys.stderr is None`.

## [0.6.0] - 2026-06-07

### Added
- Операторский поток доставки: вход, список заявок, карта, управляемый сброс груза.
- API оператора и доставок, AUX-канал сброса груза.

### Fixed
- WebRTC-поля в настройках теперь действительно сохраняются.

## [0.5.0] - 2026-06-01

### Changed
- Рефакторинг и единый стиль кода, удаление мёртвых хуков, чистка CRSF-слоя.

## [0.4.0] - 2026-05-28

### Added
- Страница настроек и удаление дронов из списка.
- Прод-дефолты `SIGNAL_URL` и STUN/TURN, подробные ICE-логи, опция force-relay.

### Fixed
- Реальный `iceTransportPolicy=relay` через aioice, разбор trickle-кандидатов.
- Обновление aiortc до ≥1.14 ради поддержки `iceTransportPolicy`.

## [0.3.0] - 2026-05-25

### Added
- Сборка единым файлом через PyInstaller (Linux + Windows).
- AppImage как основной Linux-формат распространения.

## [0.2.0] - 2026-05-21

### Added
- Сводка-статистика и грид карточек дронов, status-tint, центрирование.
- Калибровка джойстика с подписями и progress-индикатором.
- Логин: spinner, «Забыли пароль?» с запросом на API.
- Иконка приложения с логотипом Mavix.
- Скрипты сборки `.exe` (Windows) и `.deb` (Linux).

## [0.1.0] - 2026-05-17

### Added
- Импорт исходного снапшота MavixDesktop как старт редизайна.
- Редизайн интерфейса под визуальный язык сайта Mavix (карточки, иконки, cyan-акцент).
- Локальный демо-режим для проверки UI без сервера.
- Перекраска SVG-иконок и рисованный логотип через `QPainter`, анимированный фон логина.

[1.0.0]: https://github.com/dexstronggg/MavixDesktop-UI/releases/tag/v1.0.0
[0.6.0]: https://github.com/dexstronggg/MavixDesktop-UI/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/dexstronggg/MavixDesktop-UI/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/dexstronggg/MavixDesktop-UI/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/dexstronggg/MavixDesktop-UI/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dexstronggg/MavixDesktop-UI/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dexstronggg/MavixDesktop-UI/releases/tag/v0.1.0
