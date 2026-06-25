from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_CREDENTIALS_ERROR = (
    "Missing Microsoft Graph credentials. For delegated mode configure MS_CLIENT_ID. "
    "For application mode configure MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, and MS_USER_EMAIL."
)
OPENAI_CREDENTIALS_ERROR = "Missing OPENAI_API_KEY. Real mode requires OpenAI structured outputs."
ORACLE_AUTH_CONFIG_ERROR = (
    "Missing Oracle auth config. Configure ORACLE_HOST_NAME, ORACLE_APP_KEY, "
    "ORACLE_CLIENT_ID, and ORACLE_CLIENT_SECRET."
)


def _to_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _path_from_env(name: str, default: str) -> Path:
    raw = os.getenv(name, default)
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    openai_embedding_model: str
    ms_tenant_id: str | None
    ms_client_id: str | None
    ms_client_secret: str | None
    ms_user_email: str | None
    ms_auth_mode: str
    ms_graph_scopes: list[str]
    ms_token_cache_path: Path
    outlook_folder: str
    email_source: str
    email_file_path: Path
    auto_send_emails: bool
    enable_oracle_api: bool
    oracle_allow_reservation_create: bool
    oracle_allow_cancellation: bool
    oracle_alternative_search_days: int
    oracle_alternative_max_options: int
    oracle_host_name: str | None
    oracle_app_key: str | None
    oracle_client_id: str | None
    oracle_client_secret: str | None
    oracle_auth_mode: str
    oracle_enterprise_id: str
    oracle_scope: str
    oracle_hotel_code: str
    oracle_room_type: str
    oracle_rate_plan_code: str
    oracle_market_code: str
    oracle_source_code: str
    oracle_guarantee_code: str
    oracle_payment_method: str
    oracle_booking_medium: str
    oracle_custom_reference_prefix: str
    policy_dir: Path
    chroma_dir: Path
    sqlite_db_path: Path
    demo_email_body_path: Path
    demo_output_dir: Path
    use_sample_email: bool
    strict_real_mode: bool
    allow_local_ai_fallback: bool
    use_openai_policy_answer: bool
    force_policy_reingest: bool
    graph_base_url: str = "https://graph.microsoft.com/v1.0"

    @property
    def has_graph_credentials(self) -> bool:
        if self.ms_auth_mode == "delegated":
            return bool(self.ms_client_id)
        return all(
            [
                self.ms_tenant_id,
                self.ms_client_id,
                self.ms_client_secret,
                self.ms_user_email,
            ]
        )

    def require_graph_credentials(self) -> None:
        if not self.has_graph_credentials:
            raise RuntimeError(GRAPH_CREDENTIALS_ERROR)

    @property
    def graph_authority_tenant(self) -> str:
        return self.ms_tenant_id or "common"

    def require_openai_credentials(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError(OPENAI_CREDENTIALS_ERROR)

    @property
    def has_oracle_auth_config(self) -> bool:
        return bool(
            self.oracle_host_name
            and self.oracle_app_key
            and self.oracle_client_id
            and self.oracle_client_secret
        )

    def require_oracle_auth_config(self) -> None:
        if not self.has_oracle_auth_config:
            raise RuntimeError(ORACLE_AUTH_CONFIG_ERROR)

    @property
    def can_use_local_ai_fallback(self) -> bool:
        return self.allow_local_ai_fallback and not self.strict_real_mode


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-nano"),
        openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        ms_tenant_id=os.getenv("MS_TENANT_ID") or None,
        ms_client_id=os.getenv("MS_CLIENT_ID") or None,
        ms_client_secret=os.getenv("MS_CLIENT_SECRET") or None,
        ms_user_email=os.getenv("MS_USER_EMAIL") or None,
        ms_auth_mode=os.getenv("MS_AUTH_MODE", "application").strip().lower(),
        ms_graph_scopes=[
            scope.strip()
            for scope in os.getenv("MS_GRAPH_SCOPES", "User.Read Mail.ReadWrite Mail.Send offline_access").replace(",", " ").split()
            if scope.strip()
        ],
        ms_token_cache_path=_path_from_env("MS_TOKEN_CACHE_PATH", "data/msal_token_cache.json"),
        outlook_folder=os.getenv("OUTLOOK_FOLDER", "Inbox"),
        email_source=os.getenv("EMAIL_SOURCE", "outlook").strip().lower(),
        email_file_path=_path_from_env("EMAIL_FILE_PATH", "data/sample_inbox/latest_email.json"),
        auto_send_emails=_to_bool(os.getenv("AUTO_SEND_EMAILS"), default=False),
        enable_oracle_api=_to_bool(os.getenv("ENABLE_ORACLE_API"), default=False),
        oracle_allow_reservation_create=_to_bool(os.getenv("ORACLE_ALLOW_RESERVATION_CREATE"), default=False),
        oracle_allow_cancellation=_to_bool(os.getenv("ORACLE_ALLOW_CANCELLATION"), default=False),
        oracle_alternative_search_days=int(os.getenv("ORACLE_ALTERNATIVE_SEARCH_DAYS", "7")),
        oracle_alternative_max_options=int(os.getenv("ORACLE_ALTERNATIVE_MAX_OPTIONS", "3")),
        oracle_host_name=os.getenv("ORACLE_HOST_NAME") or None,
        oracle_app_key=os.getenv("ORACLE_APP_KEY") or None,
        oracle_client_id=os.getenv("ORACLE_CLIENT_ID") or None,
        oracle_client_secret=os.getenv("ORACLE_CLIENT_SECRET") or os.getenv("ORACLE_CLIENT_PASSWORD") or None,
        oracle_auth_mode=os.getenv("ORACLE_AUTH_MODE", "basic").strip().lower(),
        oracle_enterprise_id=os.getenv("ORACLE_ENTERPRISE_ID", "TGE"),
        oracle_scope=os.getenv("ORACLE_SCOPE", "urn:opc:hgbu:ws:__myscopes__"),
        oracle_hotel_code=os.getenv("ORACLE_HOTEL_CODE", "GB0783"),
        oracle_room_type=os.getenv("ORACLE_ROOM_TYPE", "DSPN"),
        oracle_rate_plan_code=os.getenv("ORACLE_RATE_PLAN_CODE", "BARFLEX"),
        oracle_market_code=os.getenv("ORACLE_MARKET_CODE", "WHOL"),
        oracle_source_code=os.getenv("ORACLE_SOURCE_CODE", "CEN"),
        oracle_guarantee_code=os.getenv("ORACLE_GUARANTEE_CODE", "PP"),
        oracle_payment_method=os.getenv("ORACLE_PAYMENT_METHOD", "CA"),
        oracle_booking_medium=os.getenv("ORACLE_BOOKING_MEDIUM", "CEN"),
        oracle_custom_reference_prefix=os.getenv("ORACLE_CUSTOM_REFERENCE_PREFIX", "HTL-WBD"),
        policy_dir=_path_from_env("POLICY_DIR", "data/policy"),
        chroma_dir=_path_from_env("CHROMA_DIR", "data/chroma"),
        sqlite_db_path=_path_from_env("SQLITE_DB_PATH", "data/hotel_agent.db"),
        demo_email_body_path=_path_from_env("DEMO_EMAIL_BODY_PATH", "data/demo_input/email_body.txt"),
        demo_output_dir=_path_from_env("DEMO_OUTPUT_DIR", "data/demo_output"),
        use_sample_email=_to_bool(os.getenv("USE_SAMPLE_EMAIL"), default=False),
        strict_real_mode=_to_bool(os.getenv("STRICT_REAL_MODE"), default=False),
        allow_local_ai_fallback=_to_bool(os.getenv("ALLOW_LOCAL_AI_FALLBACK"), default=True),
        use_openai_policy_answer=_to_bool(os.getenv("USE_OPENAI_POLICY_ANSWER"), default=False),
        force_policy_reingest=_to_bool(os.getenv("FORCE_POLICY_REINGEST"), default=False),
    )
