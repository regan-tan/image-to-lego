from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.health import router as health_router
from app.api.v1 import router as api_v1_router
from app.core.config import Settings, get_settings
from app.providers.blob_storage import AzureBlobStorage


def create_app(settings: Settings | None = None) -> FastAPI:
    application_settings = settings or get_settings()
    engine = (
        create_async_engine(application_settings.database_url, pool_pre_ping=True)
        if application_settings.database_url
        else None
    )
    session_factory = (
        async_sessionmaker(engine, expire_on_commit=False) if engine is not None else None
    )
    blob_storage = None
    if (
        application_settings.azure_storage_account_url
        and application_settings.azure_storage_container
    ):
        blob_storage = AzureBlobStorage(
            account_url=application_settings.azure_storage_account_url,
            container_name=application_settings.azure_storage_container,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if blob_storage is not None:
            await blob_storage.close()
        if engine is not None:
            await engine.dispose()

    application = FastAPI(
        title="Image to LEGO API",
        version="0.1.0",
        description="REST API for the Image to LEGO capstone project.",
        lifespan=lifespan,
    )
    application.state.settings = application_settings
    application.state.session_factory = session_factory
    application.state.blob_storage = blob_storage
    application.add_middleware(
        CORSMiddleware,
        allow_origins=application_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
    application.include_router(api_v1_router)
    return application


app = create_app()
