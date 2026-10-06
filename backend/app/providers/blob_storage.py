from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import quote, urlparse

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient

SAS_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class StoredBlobProperties:
    size_bytes: int
    content_type: str | None
    sha256: str | None


class BlobStorageError(Exception):
    pass


class BlobStorage(Protocol):
    async def create_upload_url(self, *, blob_name: str, expires_at: datetime) -> str: ...

    async def get_properties(self, *, blob_name: str) -> StoredBlobProperties | None: ...


class AzureBlobStorage:
    def __init__(
        self,
        *,
        account_url: str,
        container_name: str,
        credential: AsyncTokenCredential | None = None,
        service_client: BlobServiceClient | None = None,
    ) -> None:
        parsed_url = urlparse(account_url)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            raise ValueError("Azure Storage account URL must use HTTPS.")

        self._account_url = account_url.rstrip("/")
        self._account_name = parsed_url.hostname.split(".", maxsplit=1)[0]
        self._container_name = container_name
        self._credential = credential
        if service_client is None:
            self._credential = credential or DefaultAzureCredential()
            self._service_client = BlobServiceClient(
                account_url=self._account_url,
                credential=self._credential,
            )
        else:
            self._service_client = service_client

    async def create_upload_url(self, *, blob_name: str, expires_at: datetime) -> str:
        start = datetime.now(expires_at.tzinfo) - SAS_CLOCK_SKEW
        try:
            delegation_key = await self._service_client.get_user_delegation_key(
                key_start_time=start,
                key_expiry_time=expires_at,
            )
            sas = generate_blob_sas(
                account_name=self._account_name,
                container_name=self._container_name,
                blob_name=blob_name,
                user_delegation_key=delegation_key,
                permission=BlobSasPermissions(create=True),
                start=start,
                expiry=expires_at,
                protocol="https",
            )
        except AzureError as error:
            raise BlobStorageError("Could not create an upload URL.") from error

        container = quote(self._container_name, safe="")
        encoded_blob_name = quote(blob_name, safe="/")
        return f"{self._account_url}/{container}/{encoded_blob_name}?{sas}"

    async def get_properties(self, *, blob_name: str) -> StoredBlobProperties | None:
        blob_client = self._service_client.get_blob_client(
            container=self._container_name,
            blob=blob_name,
        )
        try:
            properties = await blob_client.get_blob_properties()
        except ResourceNotFoundError:
            return None
        except AzureError as error:
            raise BlobStorageError("Could not inspect the uploaded blob.") from error

        metadata = properties.metadata or {}
        return StoredBlobProperties(
            size_bytes=properties.size,
            content_type=properties.content_settings.content_type,
            sha256=metadata.get("sha256"),
        )

    async def close(self) -> None:
        await self._service_client.close()
        if self._credential is not None:
            await self._credential.close()
