from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import msal
import requests

from app.ai.schemas import EmailInput
from app.config import GRAPH_CREDENTIALS_ERROR, Settings

logger = logging.getLogger(__name__)


class OutlookClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.require_graph_credentials()
        self.session = requests.Session()

    def _token(self) -> str:
        if self.settings.ms_auth_mode == "delegated":
            return self._delegated_token()
        return self._application_token()

    def _application_token(self) -> str:
        authority = f"https://login.microsoftonline.com/{self.settings.ms_tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id=self.settings.ms_client_id,
            client_credential=self.settings.ms_client_secret,
            authority=authority,
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in result:
            raise RuntimeError(f"Microsoft Graph authentication failed: {result.get('error_description')}")
        return result["access_token"]

    def _delegated_token(self) -> str:
        cache = msal.SerializableTokenCache()
        cache_path = self.settings.ms_token_cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            cache.deserialize(cache_path.read_text(encoding="utf-8"))

        authority = f"https://login.microsoftonline.com/{self.settings.graph_authority_tenant}"
        app = msal.PublicClientApplication(
            client_id=self.settings.ms_client_id,
            authority=authority,
            token_cache=cache,
        )
        accounts = app.get_accounts()
        result = app.acquire_token_silent(self.settings.ms_graph_scopes, account=accounts[0] if accounts else None)
        if not result:
            flow = app.initiate_device_flow(scopes=self.settings.ms_graph_scopes)
            if "user_code" not in flow:
                raise RuntimeError(f"Microsoft device-code flow failed to start: {flow}")
            print("\nMicrosoft sign-in required:")
            print(flow["message"])
            print()
            result = app.acquire_token_by_device_flow(flow)

        if cache.has_state_changed:
            cache_path.write_text(cache.serialize(), encoding="utf-8")

        if "access_token" not in result:
            raise RuntimeError(f"Microsoft delegated authentication failed: {result.get('error_description')}")
        return result["access_token"]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        response = self.session.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"Microsoft Graph request failed {response.status_code}: {response.text}")
        return response

    def _user_url(self, suffix: str) -> str:
        if self.settings.ms_auth_mode == "delegated":
            return f"{self.settings.graph_base_url}/me{suffix}"
        if not self.settings.ms_user_email:
            raise RuntimeError(GRAPH_CREDENTIALS_ERROR)
        user = quote(self.settings.ms_user_email)
        return f"{self.settings.graph_base_url}/users/{user}{suffix}"

    def _folder_segment(self, folder_name: str) -> str:
        return quote(folder_name)

    def get_newest_email(self) -> EmailInput:
        folder = self._folder_segment(self.settings.outlook_folder)
        url = self._user_url(f"/mailFolders/{folder}/messages")
        params = {
            "$top": "1",
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,sender,from,receivedDateTime,body,internetMessageId,isRead",
        }
        headers = self._headers()
        headers["Prefer"] = 'outlook.body-content-type="text"'
        response = self.session.get(url, headers=headers, params=params, timeout=30)
        if response.status_code >= 400:
            raise RuntimeError(f"Microsoft Graph newest-email request failed {response.status_code}: {response.text}")
        messages = response.json().get("value", [])
        if not messages:
            raise RuntimeError(f"No messages found in Outlook folder '{self.settings.outlook_folder}'.")
        return self._message_to_email(messages[0])

    def send_reply(self, original_email_id: str, to_email: str, subject: str, body: str) -> str:
        draft_id = self.create_draft_reply(original_email_id, to_email, subject, body)
        self._request("POST", self._user_url(f"/messages/{quote(draft_id)}/send"))
        return draft_id

    def create_draft_reply(self, original_email_id: str, to_email: str, subject: str, body: str) -> str:
        create_url = self._user_url(f"/messages/{quote(original_email_id)}/createReply")
        draft = self._request("POST", create_url).json()
        draft_id = draft["id"]
        patch_body = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }
        self._request("PATCH", self._user_url(f"/messages/{quote(draft_id)}"), json=patch_body)
        return draft_id

    def mark_email_as_read(self, email_id: str) -> None:
        self._request("PATCH", self._user_url(f"/messages/{quote(email_id)}"), json={"isRead": True})

    def move_email(self, email_id: str, folder_name: str) -> str | None:
        destination_id = self._resolve_folder_id(folder_name)
        if not destination_id:
            logger.warning("Could not resolve Outlook folder '%s'; email was not moved.", folder_name)
            return None
        response = self._request(
            "POST",
            self._user_url(f"/messages/{quote(email_id)}/move"),
            json={"destinationId": destination_id},
        )
        return response.json().get("id")

    def _resolve_folder_id(self, folder_name: str) -> str | None:
        direct = folder_name.strip()
        if direct:
            url = self._user_url(f"/mailFolders/{quote(direct)}")
            response = self.session.get(url, headers=self._headers(), timeout=30)
            if response.status_code < 400:
                return response.json().get("id")
        list_url = self._user_url("/mailFolders")
        response = self._request("GET", list_url, params={"$top": "200"})
        for folder in response.json().get("value", []):
            if folder.get("displayName", "").lower() == folder_name.lower():
                return folder.get("id")
        return None

    @staticmethod
    def _message_to_email(message: dict[str, Any]) -> EmailInput:
        sender = message.get("from") or message.get("sender") or {}
        email_address = sender.get("emailAddress") or {}
        body = message.get("body") or {}
        return EmailInput(
            email_id=message["id"],
            internet_message_id=message.get("internetMessageId"),
            subject=message.get("subject") or "",
            sender_name=email_address.get("name"),
            sender_email=email_address.get("address") or "",
            received_datetime=message.get("receivedDateTime") or "",
            body_text=body.get("content") or "",
            is_read=message.get("isRead"),
        )
