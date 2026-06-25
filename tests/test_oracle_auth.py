from __future__ import annotations

import pytest
import requests

from app.tools.oracle_auth import OracleAuthClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("request failed")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def oracle_settings(test_settings):
    return test_settings.__class__(
        **{
            **test_settings.__dict__,
            "oracle_host_name": "oracle.example.com",
            "oracle_app_key": "app-key-123",
            "oracle_client_id": "client-id-123",
            "oracle_client_secret": "client-secret-456",
            "oracle_auth_mode": "basic",
            "oracle_enterprise_id": "TGE",
            "oracle_scope": "urn:opc:hgbu:ws:__myscopes__",
        }
    )


def test_oracle_auth_posts_exact_client_credentials_shape(test_settings):
    session = FakeSession(
        FakeResponse(
            payload={
                "access_token": "abcdef1234567890",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "urn:opc:hgbu:ws:__myscopes__",
            }
        )
    )

    token = OracleAuthClient(oracle_settings(test_settings), session=session).fetch_token()

    assert token.access_token == "abcdef1234567890"
    assert token.masked_access_token == "abcdef...7890"
    call = session.calls[0]
    assert call["url"] == "https://oracle.example.com/oauth/v1/tokens"
    assert call["headers"] == {
        "Content-Type": "application/x-www-form-urlencoded",
        "x-app-key": "app-key-123",
        "enterpriseId": "TGE",
        "Scope": "urn:opc:hgbu:ws:__myscopes__",
    }
    assert call["data"] == {
        "grant_type": "client_credentials",
        "scope": "urn:opc:hgbu:ws:__myscopes__",
    }
    assert call["auth"].username == "client-id-123"
    assert call["auth"].password == "client-secret-456"
    assert call["timeout"] == 30


def test_oracle_auth_can_send_client_credentials_in_form_body(test_settings):
    settings = test_settings.__class__(
        **{
            **oracle_settings(test_settings).__dict__,
            "oracle_auth_mode": "form",
        }
    )
    session = FakeSession(FakeResponse(payload={"access_token": "abcdef1234567890"}))

    OracleAuthClient(settings, session=session).fetch_token()

    call = session.calls[0]
    assert call["auth"] is None
    assert call["data"]["client_id"] == "client-id-123"
    assert call["data"]["client_secret"] == "client-secret-456"


def test_oracle_auth_accepts_host_with_scheme(test_settings):
    settings = test_settings.__class__(
        **{
            **oracle_settings(test_settings).__dict__,
            "oracle_host_name": "https://oracle.example.com/",
        }
    )

    client = OracleAuthClient(settings, session=FakeSession(FakeResponse(payload={"access_token": "token"})))

    assert client.token_url == "https://oracle.example.com/oauth/v1/tokens"


def test_oracle_auth_requires_config(test_settings):
    client = OracleAuthClient(test_settings, session=FakeSession(FakeResponse()))

    with pytest.raises(RuntimeError, match="Missing Oracle auth config"):
        client.fetch_token()


def test_oracle_auth_rejects_missing_access_token(test_settings):
    client = OracleAuthClient(
        oracle_settings(test_settings),
        session=FakeSession(FakeResponse(payload={"token_type": "Bearer"})),
    )

    with pytest.raises(RuntimeError, match="access_token"):
        client.fetch_token()


def test_oracle_auth_reports_http_error_without_token(test_settings):
    client = OracleAuthClient(
        oracle_settings(test_settings),
        session=FakeSession(FakeResponse(status_code=401, text='{"error":"invalid_client"}')),
    )

    with pytest.raises(RuntimeError, match="HTTP 401"):
        client.fetch_token()
