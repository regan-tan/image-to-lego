from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, cast

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWK

from app.core.config import Settings

bearer_scheme = HTTPBearer(auto_error=False)
JWKS_REQUEST_TIMEOUT_SECONDS = 5.0
ALLOWED_JWT_ALGORITHMS = frozenset({"ES256", "RS256"})
CredentialsDependency = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str
    email: str | None
    display_name: str | None
    avatar_url: str | None


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


SettingsDependency = Annotated[Settings, Depends(get_app_settings)]


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def fetch_jwks(settings: Settings) -> Mapping[str, Any]:
    if not settings.supabase_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )

    jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        async with httpx.AsyncClient(timeout=JWKS_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            jwks = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
        ) from error

    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if not isinstance(keys, list) or not all(isinstance(key, dict) for key in keys):
        raise authentication_service_unavailable()
    return cast(Mapping[str, Any], jwks)


def authentication_service_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication is temporarily unavailable.",
    )


def get_matching_jwk(header: Mapping[str, Any], jwks: Mapping[str, Any]) -> PyJWK:
    algorithm = header.get("alg")
    key_id = header.get("kid")
    if algorithm not in ALLOWED_JWT_ALGORITHMS or not isinstance(key_id, str) or not key_id:
        raise unauthorized()

    keys = jwks.get("keys")
    if not isinstance(keys, list) or not all(isinstance(key, dict) for key in keys):
        raise authentication_service_unavailable()

    for key_data in keys:
        if isinstance(key_data, dict) and key_data.get("kid") == key_id:
            if key_data.get("alg") != algorithm:
                raise unauthorized()
            try:
                key = PyJWK.from_dict(key_data, algorithm=algorithm)
            except jwt.PyJWTError as error:
                raise authentication_service_unavailable() from error
            if key.algorithm_name != algorithm:
                raise unauthorized()
            return key

    raise unauthorized()


def optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


async def get_current_user(
    credentials: CredentialsDependency,
    settings: SettingsDependency,
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()

    try:
        header = jwt.get_unverified_header(credentials.credentials)
    except jwt.PyJWTError as error:
        raise unauthorized() from error

    jwks = await fetch_jwks(settings)
    signing_key = get_matching_jwk(header, jwks)
    if not settings.supabase_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )

    try:
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=[signing_key.algorithm_name],
            audience=settings.supabase_jwt_audience,
            issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as error:
        raise unauthorized() from error

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise unauthorized()

    metadata = claims.get("user_metadata")
    user_metadata = metadata if isinstance(metadata, dict) else {}
    return AuthenticatedUser(
        id=subject,
        email=optional_string(claims.get("email")),
        display_name=optional_string(user_metadata.get("full_name"))
        or optional_string(user_metadata.get("name")),
        avatar_url=optional_string(user_metadata.get("avatar_url")),
    )
