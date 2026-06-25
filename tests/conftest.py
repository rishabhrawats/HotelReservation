from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        openai_api_key=None,
        openai_model="gpt-5.4-nano",
        openai_embedding_model="text-embedding-3-small",
        ms_tenant_id=None,
        ms_client_id=None,
        ms_client_secret=None,
        ms_user_email=None,
        ms_auth_mode="application",
        ms_graph_scopes=["User.Read", "Mail.ReadWrite", "Mail.Send", "offline_access"],
        ms_token_cache_path=tmp_path / "data" / "msal_token_cache.json",
        outlook_folder="Inbox",
        email_source="outlook",
        email_file_path=tmp_path / "sample_inbox" / "latest_email.json",
        auto_send_emails=False,
        enable_oracle_api=False,
        oracle_allow_reservation_create=False,
        oracle_allow_cancellation=False,
        oracle_alternative_search_days=7,
        oracle_alternative_max_options=3,
        oracle_host_name=None,
        oracle_app_key=None,
        oracle_client_id=None,
        oracle_client_secret=None,
        oracle_auth_mode="basic",
        oracle_enterprise_id="TGE",
        oracle_scope="urn:opc:hgbu:ws:__myscopes__",
        oracle_hotel_code="GB0783",
        oracle_room_type="DSPN",
        oracle_rate_plan_code="BARFLEX",
        oracle_market_code="WHOL",
        oracle_source_code="CEN",
        oracle_guarantee_code="PP",
        oracle_payment_method="CA",
        oracle_booking_medium="CEN",
        oracle_custom_reference_prefix="HTL-WBD",
        policy_dir=tmp_path / "policy",
        chroma_dir=tmp_path / "chroma",
        sqlite_db_path=tmp_path / "data" / "hotel_agent.db",
        demo_email_body_path=tmp_path / "demo_input" / "email_body.txt",
        demo_output_dir=tmp_path / "demo_output",
        use_sample_email=True,
        strict_real_mode=False,
        allow_local_ai_fallback=True,
        use_openai_policy_answer=False,
        force_policy_reingest=False,
    )
