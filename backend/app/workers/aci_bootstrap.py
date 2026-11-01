"""Start an ACI worker after loading only its required Key Vault secrets."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Sequence
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx
from azure.core.credentials import AccessToken
from azure.identity import ManagedIdentityCredential

KEY_VAULT_SCOPE = "https://vault.azure.net/.default"
KEY_VAULT_API_VERSION = "7.4"
KEY_VAULT_TIMEOUT_SECONDS = 10.0

WorkerName = str
SecretReader = Callable[[str, str], str]


class TokenCredential(Protocol):
    def get_token(self, *scopes: str, **kwargs: object) -> AccessToken: ...

    def close(self) -> None: ...


def required_secret_names(worker_name: WorkerName) -> tuple[tuple[str, str], ...]:
    database_secret_name = _required_environment_value("DATABASE_URL_SECRET_NAME")
    if worker_name == "conversion":
        return (("DATABASE_URL", database_secret_name),)
    if worker_name == "generation":
        return (
            ("DATABASE_URL", database_secret_name),
            ("FAL_KEY", _required_environment_value("FAL_KEY_SECRET_NAME")),
        )
    raise ValueError("Worker name must be generation or conversion.")


def load_worker_secrets(
    worker_name: WorkerName,
    vault_url: str,
    credential: TokenCredential,
    secret_reader: SecretReader | None = None,
) -> dict[str, str]:
    secret_values: dict[str, str] = {}
    reader = secret_reader or _read_secret
    try:
        for environment_name, secret_name in required_secret_names(worker_name):
            secret_values[environment_name] = reader(
                _secret_url(vault_url, secret_name), credential.get_token(KEY_VAULT_SCOPE).token
            )
    finally:
        credential.close()
    return secret_values


def _required_environment_value(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be configured for the ACI worker bootstrap.")
    return value


def _secret_url(vault_url: str, secret_name: str) -> str:
    parsed = urlparse(vault_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
        raise ValueError("AZURE_KEY_VAULT_URL must be an HTTPS Key Vault URI without a path.")
    vault_base_url = vault_url.rstrip("/")
    encoded_secret_name = quote(secret_name, safe="")
    return f"{vault_base_url}/secrets/{encoded_secret_name}?api-version={KEY_VAULT_API_VERSION}"


def _read_secret(url: str, access_token: str) -> str:
    response = httpx.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=KEY_VAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    value = payload.get("value")
    if not isinstance(value, str) or not value:
        raise RuntimeError("Key Vault returned an empty secret value.")
    return value


def worker_command(worker_name: WorkerName) -> tuple[str, ...]:
    if worker_name == "generation":
        return ("python", "-m", "app.workers.generation_worker")
    if worker_name == "conversion":
        return ("python", "-m", "app.workers.conversion_worker")
    raise ValueError("Worker name must be generation or conversion.")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("worker", choices=("generation", "conversion"))
    args = parser.parse_args(argv)

    vault_url = _required_environment_value("AZURE_KEY_VAULT_URL")
    client_id = _required_environment_value("AZURE_CLIENT_ID")
    credential = ManagedIdentityCredential(client_id=client_id)
    os.environ.update(load_worker_secrets(args.worker, vault_url, credential))
    command = worker_command(args.worker)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
