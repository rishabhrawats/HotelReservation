from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from app.config import Settings, load_settings


@dataclass(frozen=True)
class OracleToken:
    access_token: str
    token_type: str | None = None
    expires_in: int | None = None
    scope: str | None = None

    @property
    def masked_access_token(self) -> str:
        token = self.access_token
        if len(token) <= 12:
            return "***"
        return f"{token[:6]}...{token[-4:]}"


class OracleAuthClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def fetch_token(self) -> OracleToken:
        self.settings.require_oracle_auth_config()
        response = self.session.post(
            self.token_url,
            headers=self._headers(),
            data=self._form_data(),
            auth=self._auth(),
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = _safe_error_body(response)
            raise RuntimeError(f"Oracle token request failed: HTTP {response.status_code} {body}") from exc
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Oracle token response did not include access_token.")
        return OracleToken(
            access_token=str(token),
            token_type=_optional_str(payload.get("token_type")),
            expires_in=_optional_int(payload.get("expires_in")),
            scope=_optional_str(payload.get("scope")),
        )

    @property
    def token_url(self) -> str:
        host = (self.settings.oracle_host_name or "").strip().rstrip("/")
        if not host:
            self.settings.require_oracle_auth_config()
        if not host.startswith(("http://", "https://")):
            host = f"https://{host}"
        return f"{host}/oauth/v1/tokens"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/x-www-form-urlencoded",
            "x-app-key": self.settings.oracle_app_key or "",
            "enterpriseId": self.settings.oracle_enterprise_id,
            "Scope": self.settings.oracle_scope,
        }

    def _form_data(self) -> dict[str, str]:
        data = {
            "grant_type": "client_credentials",
            "scope": self.settings.oracle_scope,
        }
        if self.settings.oracle_auth_mode == "form":
            data["client_id"] = self.settings.oracle_client_id or ""
            data["client_secret"] = self.settings.oracle_client_secret or ""
        return data

    def _auth(self) -> HTTPBasicAuth | None:
        if self.settings.oracle_auth_mode == "form":
            return None
        return HTTPBasicAuth(
            self.settings.oracle_client_id or "",
            self.settings.oracle_client_secret or "",
        )


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_error_body(response: requests.Response) -> str:
    text = (response.text or "").strip()
    if not text:
        return ""
    return text[:500]


def main() -> int:
    try:
        token = OracleAuthClient(load_settings()).fetch_token()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Oracle token request succeeded.")
    print(f"token_type: {token.token_type or '-'}")
    print(f"expires_in: {token.expires_in if token.expires_in is not None else '-'}")
    print(f"scope: {token.scope or '-'}")
    print(f"access_token_preview: {token.masked_access_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
