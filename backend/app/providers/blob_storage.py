from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import quote, urlparse

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import BlobSasPermissions, ContentSettings, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient

SAS_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class StoredBlobProperties:
    size_bytes: int
    content_type: str | None
    sha256: str | None


class BlobStorageError(Exception):
    pass


class BlobNotFoundError(BlobStorageError):
    pass


class BlobStorage(Protocol):
    async def create_upload_url(self, *, blob_name: str, expires_at: datetime) -> str: ...

    async def get_properties(self, *, blob_name: str) -> StoredBlobProperties | None: ...

    async def create_read_url(self, *, blob_name: str, expires_at: datetime) -> str: ...

    async def download_bounded(self, *, blob_name: str, max_bytes: int) -> bytes: ...

    async def upload_generated_model(
        self,
        *,
        blob_name: str,
        content: bytes,
        mime_type: str,
        sha256: str,
    ) -> bool: ...


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

    async def create_read_url(self, *, blob_name: str, expires_at: datetime) -> str:
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
                permission=BlobSasPermissions(read=True),
                start=start,
                expiry=expires_at,
                protocol="https",
            )
        except AzureError as error:
            raise BlobStorageError("Could not create a source-image URL.") from error

        container = quote(self._container_name, safe="")
        encoded_blob_name = quote(blob_name, safe="/")
        return f"{self._account_url}/{container}/{encoded_blob_name}?{sas}"

    async def download_bounded(self, *, blob_name: str, max_bytes: int) -> bytes:
        blob_client = self._service_client.get_blob_client(
            container=self._container_name,
            blob=blob_name,
        )
        try:
            properties = await blob_client.get_blob_properties()
            if properties.size > max_bytes:
                raise BlobStorageError("The blob exceeds the configured size limit.")
            downloader = await blob_client.download_blob()
            content = bytearray()
            async for chunk in downloader.chunks():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise BlobStorageError("The blob exceeds the configured size limit.")
            return bytes(content)
        except ResourceNotFoundError as error:
            raise BlobNotFoundError("The blob does not exist.") from error
        except AzureError as error:
            raise BlobStorageError("Could not download the blob.") from error

    async def upload_generated_model(
        self,
        *,
        blob_name: str,
        content: bytes,
        mime_type: str,
        sha256: str,
    ) -> bool:
        blob_client = self._service_client.get_blob_client(
            container=self._container_name,
            blob=blob_name,
        )
        try:
            await blob_client.upload_blob(
                content,
                overwrite=False,
                content_settings=ContentSettings(content_type=mime_type),
                metadata={"sha256": sha256},
            )
        except ResourceExistsError:
            return False
        except AzureError as error:
            raise BlobStorageError("Could not store the generated model.") from error
        return True

    async def close(self) -> None:
        await self._service_client.close()
        if self._credential is not None:
            await self._credential.close()
