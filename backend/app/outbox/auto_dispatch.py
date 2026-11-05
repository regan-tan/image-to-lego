"""Best-effort API trigger for the durable submission-outbox dispatcher."""

import logging

from fastapi import BackgroundTasks

from app.core.config import Settings
from app.outbox.run import DispatcherExitCode, run

logger = logging.getLogger(__name__)


def schedule_auto_dispatch(background_tasks: BackgroundTasks, settings: Settings) -> bool:
    """Schedule one bounded dispatch only when the private dispatcher login is configured."""
    if not settings.outbox_auto_dispatch_enabled:
        return False
    if not settings.outbox_dispatcher_database_url:
        logger.warning("Automatic outbox dispatch is enabled without a dispatcher database URL.")
        return False

    dispatcher_settings = settings.model_copy(
        update={"database_url": settings.outbox_dispatcher_database_url}
    )
    background_tasks.add_task(_run_auto_dispatch, dispatcher_settings)
    return True


async def _run_auto_dispatch(settings: Settings) -> None:
    try:
        exit_code = await run(
            settings,
            max_messages=settings.outbox_dispatcher_max_messages,
            max_runtime_seconds=settings.outbox_dispatcher_max_runtime_seconds,
        )
    except Exception as error:
        logger.error("Automatic outbox dispatch failed: %s", type(error).__name__)
        return

    if exit_code is not DispatcherExitCode.SUCCESS:
        logger.warning("Automatic outbox dispatch ended with result: %s", exit_code.name)
