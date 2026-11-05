from fastapi import BackgroundTasks

from app.core.config import Settings
from app.outbox import auto_dispatch


def test_auto_dispatch_is_not_scheduled_when_disabled_or_missing_private_database_url() -> None:
    assert auto_dispatch.schedule_auto_dispatch(BackgroundTasks(), Settings()) is False
    assert (
        auto_dispatch.schedule_auto_dispatch(
            BackgroundTasks(), Settings(outbox_auto_dispatch_enabled=True)
        )
        is False
    )


def test_auto_dispatch_uses_a_copy_with_only_the_private_dispatcher_database_url() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://api.example.test/app",
        outbox_auto_dispatch_enabled=True,
        outbox_dispatcher_database_url="postgresql+asyncpg://dispatcher.example.test/app",
    )
    background_tasks = BackgroundTasks()

    assert auto_dispatch.schedule_auto_dispatch(background_tasks, settings) is True
    assert len(background_tasks.tasks) == 1
    dispatcher_settings = background_tasks.tasks[0].args[0]
    assert isinstance(dispatcher_settings, Settings)
    assert dispatcher_settings.database_url == "postgresql+asyncpg://dispatcher.example.test/app"
    assert settings.database_url == "postgresql+asyncpg://api.example.test/app"
