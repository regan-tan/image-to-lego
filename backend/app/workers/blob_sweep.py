"""Deletes Blob folders whose project no longer exists in PostgreSQL.

Deleting a project (DELETE /api/v1/projects/{projectId}) removes only its database rows. Every file
the application writes lives under projects/{projectId}/, so this sweep finds folders without a
project row and removes them. It reports by default and deletes only when asked:

    uv run python -m app.workers.blob_sweep            # report orphaned folders
    uv run python -m app.workers.blob_sweep --delete   # delete them
"""

import argparse
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from azure.identity.aio import DefaultAzureCredential
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.providers.blob_storage import AzureBlobStorage, BlobStorage, ListedBlob
from app.repositories.projects import ProjectExistenceRepository
from app.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository

logger = logging.getLogger(__name__)

PROJECTS_PREFIX = "projects/"


@dataclass(frozen=True, slots=True)
class OrphanedProjectFolder:
    project_id: UUID
    blob_names: tuple[str, ...]


async def sweep_orphaned_blobs(
    *,
    blob_storage: BlobStorage,
    projects: ProjectExistenceRepository,
    now: datetime,
    min_age: timedelta,
    delete: bool,
) -> list[OrphanedProjectFolder]:
    """Find, and optionally delete, project folders that have no project row.

    A folder counts as orphaned only when its project ID no longer exists and every blob in it is
    older than ``min_age``. Names that are not under a UUID folder are never touched.
    """
    blobs_by_project = _group_by_project(await blob_storage.list_blobs(prefix=PROJECTS_PREFIX))
    if not blobs_by_project:
        return []

    existing_ids = await projects.existing_project_ids(candidate_ids=list(blobs_by_project))
    newest_allowed = now - min_age
    orphaned_folders = []
    for project_id in sorted(blobs_by_project):
        project_blobs = blobs_by_project[project_id]
        if project_id in existing_ids:
            continue
        if any(blob.last_modified > newest_allowed for blob in project_blobs):
            # Written recently; a later sweep will collect it once it is old enough.
            continue
        blob_names = tuple(sorted(blob.name for blob in project_blobs))
        orphaned_folders.append(OrphanedProjectFolder(project_id, blob_names))

    if delete:
        for folder in orphaned_folders:
            for blob_name in folder.blob_names:
                await blob_storage.delete_blob(blob_name=blob_name)
    return orphaned_folders


def _group_by_project(blobs: list[ListedBlob]) -> dict[UUID, list[ListedBlob]]:
    blobs_by_project: dict[UUID, list[ListedBlob]] = defaultdict(list)
    for blob in blobs:
        folder_name, separator, _ = blob.name.removeprefix(PROJECTS_PREFIX).partition("/")
        if not separator:
            continue
        try:
            project_id = UUID(folder_name)
        except ValueError:
            continue
        blobs_by_project[project_id].append(blob)
    return blobs_by_project


async def run_sweep(settings: Settings, *, delete: bool) -> None:
    if not (
        settings.database_url
        and settings.azure_storage_account_url
        and settings.azure_storage_container
    ):
        raise RuntimeError("Blob sweep configuration is incomplete.")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    blob_storage = AzureBlobStorage(
        account_url=settings.azure_storage_account_url,
        container_name=settings.azure_storage_container,
        credential=DefaultAzureCredential(),
    )
    try:
        async with session_factory() as session:
            orphaned_folders = await sweep_orphaned_blobs(
                blob_storage=blob_storage,
                projects=SqlAlchemyProjectRepository(session),
                now=datetime.now(UTC),
                min_age=timedelta(minutes=settings.blob_sweep_min_age_minutes),
                delete=delete,
            )
    finally:
        await blob_storage.close()
        await engine.dispose()

    action = "Deleted" if delete else "Would delete"
    # Blob names include user-chosen file names, so the report logs only project IDs and counts.
    for folder in orphaned_folders:
        logger.info(
            "%s %d blob(s) for deleted project %s",
            action,
            len(folder.blob_names),
            folder.project_id,
        )
    logger.info("%s %d orphaned project folder(s).", action, len(orphaned_folders))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete Blob folders whose project no longer exists."
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="delete orphaned folders instead of only reporting them",
    )
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    # The Azure SDK logs every HTTP request at INFO, which would bury the sweep report.
    logging.getLogger("azure").setLevel(logging.WARNING)
    asyncio.run(run_sweep(get_settings(), delete=arguments.delete))


if __name__ == "__main__":
    main()
