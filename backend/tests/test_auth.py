import json
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from app.core.config import Settings
from app.main import create_app

SUPABASE_URL = "https://project.supabase.co"
KEY_ID = "test-rsa-key"
EC_KEY_ID = "test-ec-key"


@pytest.fixture
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks(signing_key: rsa.RSAPrivateKey) -> dict[str, list[dict[str, str]]]:
    public_jwk = json.loads(RSAAlgorithm.to_jwk(signing_key.public_key()))
    public_jwk["kid"] = KEY_ID
    public_jwk["alg"] = "RS256"
    return {"keys": [public_jwk]}


def make_token(signing_key: rsa.RSAPrivateKey, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": "0c3d60a8-5117-44e5-821b-abc1c0c8f3d0",
        "aud": "authenticated",
        "iss": f"{SUPABASE_URL}/auth/v1",
        "exp": now + timedelta(minutes=5),
        "email": "builder@example.com",
        "user_metadata": {
            "full_name": "LEGO Builder",
            "avatar_url": "https://example.com/avatar.png",
        },
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": KEY_ID})


async def request_profile(token: str | None = None) -> httpx.Response:
    app = create_app(Settings(supabase_url=SUPABASE_URL))
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/profile", headers=headers)


@pytest.mark.asyncio
async def test_profile_returns_verified_supabase_user(
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
    jwks: dict[str, list[dict[str, str]]],
) -> None:
    async def fake_fetch_jwks(_: Settings) -> dict[str, list[dict[str, str]]]:
        return jwks

    monkeypatch.setattr("app.core.auth.fetch_jwks", fake_fetch_jwks)

    response = await request_profile(make_token(signing_key))

    assert response.status_code == 200
    assert response.json() == {
        "id": "0c3d60a8-5117-44e5-821b-abc1c0c8f3d0",
        "email": "builder@example.com",
        "displayName": "LEGO Builder",
        "avatarUrl": "https://example.com/avatar.png",
    }


@pytest.mark.asyncio
async def test_profile_rejects_missing_token() -> None:
    response = await request_profile()

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_profile_rejects_malformed_token(
    monkeypatch: pytest.MonkeyPatch,
    jwks: dict[str, list[dict[str, str]]],
) -> None:
    async def fake_fetch_jwks(_: Settings) -> dict[str, list[dict[str, str]]]:
        return jwks

    monkeypatch.setattr("app.core.auth.fetch_jwks", fake_fetch_jwks)

    response = await request_profile("not-a-jwt")

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("exp", datetime.now(UTC) - timedelta(minutes=5)),
        ("iss", "https://wrong-project.supabase.co/auth/v1"),
        ("aud", "wrong-audience"),
    ],
)
async def test_profile_rejects_invalid_claims(
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
    jwks: dict[str, list[dict[str, str]]],
    claim: str,
    value: object,
) -> None:
    async def fake_fetch_jwks(_: Settings) -> dict[str, list[dict[str, str]]]:
        return jwks

    monkeypatch.setattr("app.core.auth.fetch_jwks", fake_fetch_jwks)

    response = await request_profile(make_token(signing_key, **{claim: value}))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_profile_accepts_es256_token(monkeypatch: pytest.MonkeyPatch) -> None:
    signing_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = json.loads(ECAlgorithm.to_jwk(signing_key.public_key()))
    public_jwk["kid"] = EC_KEY_ID
    public_jwk["alg"] = "ES256"

    async def fake_fetch_jwks(_: Settings) -> dict[str, list[dict[str, str]]]:
        return {"keys": [public_jwk]}

    monkeypatch.setattr("app.core.auth.fetch_jwks", fake_fetch_jwks)
    token = jwt.encode(
        {
            "sub": "ec-user",
            "aud": "authenticated",
            "iss": f"{SUPABASE_URL}/auth/v1",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        signing_key,
        algorithm="ES256",
        headers={"kid": EC_KEY_ID},
    )

    response = await request_profile(token)

    assert response.status_code == 200
    assert response.json()["id"] == "ec-user"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({"kid": KEY_ID, "alg": "HS256"}, 401),
        ({"kid": "unknown-key"}, 401),
    ],
)
async def test_profile_rejects_unsupported_or_unknown_jwk(
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
    jwks: dict[str, list[dict[str, str]]],
    headers: dict[str, str],
    expected_status: int,
) -> None:
    async def fake_fetch_jwks(_: Settings) -> dict[str, list[dict[str, str]]]:
        return jwks

    monkeypatch.setattr("app.core.auth.fetch_jwks", fake_fetch_jwks)
    algorithm = headers.get("alg", "RS256")
    token = jwt.encode(
        {
            "sub": "test-user",
            "aud": "authenticated",
            "iss": f"{SUPABASE_URL}/auth/v1",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "not-a-supabase-secret-with-enough-length" if algorithm == "HS256" else signing_key,
        algorithm=algorithm,
        headers=headers,
    )

    response = await request_profile(token)

    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_profile_rejects_invalid_signature(
    monkeypatch: pytest.MonkeyPatch,
    jwks: dict[str, list[dict[str, str]]],
) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    async def fake_fetch_jwks(_: Settings) -> dict[str, list[dict[str, str]]]:
        return jwks

    monkeypatch.setattr("app.core.auth.fetch_jwks", fake_fetch_jwks)

    response = await request_profile(make_token(other_key))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_profile_returns_service_unavailable_for_malformed_jwks(
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
) -> None:
    async def fake_fetch_jwks(_: Settings) -> dict[str, object]:
        return {"keys": ["invalid-key"]}

    monkeypatch.setattr("app.core.auth.fetch_jwks", fake_fetch_jwks)

    response = await request_profile(make_token(signing_key))

    assert response.status_code == 503
