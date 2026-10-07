from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from azure.storage.blob import BlobSasPermissions
from azure.storage.blob.aio import BlobServiceClient

from app.providers.blob_storage import AzureBlobStorage


class FakeBlobServiceClient:
    async def get_user_delegation_key(
        self,
        key_start_time: datetime,
        key_expiry_time: datetime,
    ) -> object:
        del key_start_time, key_expiry_time
        return object()

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_upload_sas_is_https_and_create_only_for_one_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_generate_blob_sas(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "sp=c&spr=https&sig=secret"

    monkeypatch.setattr("app.providers.blob_storage.generate_blob_sas", fake_generate_blob_sas)
    storage = AzureBlobStorage(
        account_url="https://legostorage.blob.core.windows.net",
        container_name="artifacts",
        service_client=cast(BlobServiceClient, FakeBlobServiceClient()),
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=10)

    url = await storage.create_upload_url(
        blob_name="projects/project-id/uploads/upload-id/image.png",
        expires_at=expires_at,
    )
    await storage.close()

    permission = cast(BlobSasPermissions, captured["permission"])
    assert captured["container_name"] == "artifacts"
    assert captured["blob_name"] == "projects/project-id/uploads/upload-id/image.png"
    assert captured["expiry"] == expires_at
    assert captured["protocol"] == "https"
    assert permission.create is True
    assert permission.write is False
    assert permission.read is False
    assert permission.delete is False
    assert url.startswith(
        "https://legostorage.blob.core.windows.net/artifacts/"
        "projects/project-id/uploads/upload-id/image.png?"
    )


@pytest.mark.asyncio
async def test_reconstruction_source_sas_is_https_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_generate_blob_sas(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "sp=r&spr=https&sig=secret"

    monkeypatch.setattr("app.providers.blob_storage.generate_blob_sas", fake_generate_blob_sas)
    storage = AzureBlobStorage(
        account_url="https://legostorage.blob.core.windows.net",
        container_name="artifacts",
        service_client=cast(BlobServiceClient, FakeBlobServiceClient()),
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=10)

    await storage.create_read_url(
        blob_name="projects/project-id/uploads/upload-id/image.png",
        expires_at=expires_at,
    )
    await storage.close()

    permission = cast(BlobSasPermissions, captured["permission"])
    assert captured["blob_name"] == "projects/project-id/uploads/upload-id/image.png"
    assert captured["protocol"] == "https"
    assert permission.read is True
    assert permission.create is False
    assert permission.write is False
