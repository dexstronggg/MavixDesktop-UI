"""Entry point: python -m mavixdesktop.

By default opens the PySide6 UI (login page → drone list → video).
Pass --headless to keep the legacy headless mode (auth + coordinator
loop with no GUI), useful for soak-testing against a live server.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger, setup_file_logging
from mavixdesktop.coordinator import SessionCoordinator
from mavixdesktop.server import token_store
from mavixdesktop.server.api import ApiError, ApiSession
from mavixdesktop.server.signal_client import SignalClient


def _init_dirs() -> None:
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    setup_file_logging()


# ---------- headless mode ----------

async def _authenticate_headless(api: ApiSession, email: str | None, password: str | None) -> tuple[str, str]:
    stored_email, stored_refresh = token_store.load()
    if stored_refresh:
        try:
            result = await api.refresh(stored_refresh)
            access = result.get('access_token', '')
            if access:
                logger.info('[auth] refreshed access token for %s', stored_email)
                return access, stored_refresh
        except ApiError as exc:
            logger.info('[auth] stored refresh invalid: %s', exc)

    if not email or not password:
        raise SystemExit(
            'No valid stored credentials and no --email/--password provided. '
            "Run with '--email me@example.com --password ...' to do a first login."
        )

    result = await api.login(email, password)
    access = result['access_token']
    refresh = result['refresh_token']
    token_store.save(email, refresh)
    logger.info('[auth] logged in as %s; refresh token saved', email)
    return access, refresh


async def _run_headless(email: str | None, password: str | None) -> None:
    api = await ApiSession.create()
    try:
        if not await api.health():
            logger.error('signal server unreachable at %s', settings.http_url)
            return
        access, refresh = await _authenticate_headless(api, email, password)
        signal_client = SignalClient(url=settings.ws_url, access_token=access)
        coordinator = SessionCoordinator(
            signal_client=signal_client,
            api_session=api,
            refresh_token=refresh,
        )
        await coordinator.run()
    finally:
        await api.close()


# ---------- GUI mode ----------

def _run_gui() -> int:
    from PySide6.QtWidgets import QApplication
    from mavixdesktop.ui.app import App

    app = QApplication(sys.argv)
    window = App()
    window.show()
    return app.exec()


# ---------- entry ----------

def main() -> None:
    parser = argparse.ArgumentParser(prog='mavixdesktop', description='Mavix GCS')
    parser.add_argument('--headless', action='store_true',
                        help='Run the coordinator without the Qt UI')
    parser.add_argument('--email', help='login email (first launch, headless or GUI)')
    parser.add_argument('--password', help='login password (first launch, headless only)')
    args = parser.parse_args()

    _init_dirs()
    if args.headless:
        try:
            asyncio.run(_run_headless(args.email, args.password))
        except KeyboardInterrupt:
            pass
        return

    sys.exit(_run_gui())


if __name__ == '__main__':
    main()
