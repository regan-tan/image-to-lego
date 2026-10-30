from __future__ import annotations

from azure.core.credentials import AccessToken

from app.workers import aci_bootstrap


class FakeCredential:
    def __init__(self) -> None:
        self.scopes: list[str] = []
        self.closed = False

    def get_token(self, *scopes: str, **_: object) -> AccessToken:
        self.scopes.extend(scopes)
        return AccessToken("test-token", 0)

    def close(self) -> None:
        self.closed = True


def test_conversion_bootstrap_reads_only_database_secret(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL_SECRET_NAME", "database-url")
    credential = FakeCredential()
    calls: list[str] = []

    def read_secret(url: str, _: str) -> str:
        calls.append(url)
        return "test-database-url"

    secrets = aci_bootstrap.load_worker_secrets(
        "conversion", "https://vault.example", credential, read_secret
    )

    assert secrets == {"DATABASE_URL": "test-database-url"}
    assert calls == ["https://vault.example/secrets/database-url?api-version=7.4"]
    assert credential.scopes == [aci_bootstrap.KEY_VAULT_SCOPE]
    assert credential.closed is True


def test_generation_bootstrap_reads_database_and_fal_secrets(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL_SECRET_NAME", "database-url")
    monkeypatch.setenv("FAL_KEY_SECRET_NAME", "fal-key")
    credential = FakeCredential()

    def read_secret(url: str, _: str) -> str:
        return url.rsplit("/", 1)[-1]

    secrets = aci_bootstrap.load_worker_secrets(
        "generation", "https://vault.example", credential, read_secret
    )

    assert set(secrets) == {"DATABASE_URL", "FAL_KEY"}
    assert credential.closed is True


def test_key_vault_url_rejects_paths() -> None:
    try:
        aci_bootstrap._secret_url("https://vault.example/secrets", "database-url")
    except ValueError as error:
        assert "AZURE_KEY_VAULT_URL" in str(error)
    else:
        raise AssertionError("Expected Key Vault URL validation to fail.")
