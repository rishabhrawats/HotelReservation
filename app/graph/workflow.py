from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.ai.schemas import EmailInput
from app.config import Settings, load_settings
from app.graph.nodes import (
    answer_policy_questions_node,
    classify_and_extract,
    clean_email,
    final_output,
    generate_reply_node,
    load_newest_email,
    log_processing_result_node,
    oracle_booking_node,
    retrieve_policy_context_node,
    send_or_draft_reply_node,
    validate_booking_readiness,
)
from app.graph.state import HotelAgentState


def build_workflow():
    builder = StateGraph(HotelAgentState)
    builder.add_node("load_newest_email", load_newest_email)
    builder.add_node("clean_email", clean_email)
    builder.add_node("classify_and_extract", classify_and_extract)
    builder.add_node("validate_booking_readiness", validate_booking_readiness)
    builder.add_node("retrieve_policy_context", retrieve_policy_context_node)
    builder.add_node("answer_policy_questions", answer_policy_questions_node)
    builder.add_node("oracle_booking", oracle_booking_node)
    builder.add_node("generate_reply", generate_reply_node)
    builder.add_node("send_or_draft_reply", send_or_draft_reply_node)
    builder.add_node("log_processing_result", log_processing_result_node)
    builder.add_node("final_output", final_output)

    builder.set_entry_point("load_newest_email")
    builder.add_edge("load_newest_email", "clean_email")
    builder.add_edge("clean_email", "classify_and_extract")
    builder.add_edge("classify_and_extract", "validate_booking_readiness")
    builder.add_conditional_edges(
        "validate_booking_readiness",
        _policy_route,
        {"rag": "retrieve_policy_context", "skip": "oracle_booking"},
    )
    builder.add_edge("retrieve_policy_context", "answer_policy_questions")
    builder.add_edge("answer_policy_questions", "oracle_booking")
    builder.add_edge("oracle_booking", "generate_reply")
    builder.add_edge("generate_reply", "send_or_draft_reply")
    builder.add_edge("send_or_draft_reply", "log_processing_result")
    builder.add_edge("log_processing_result", "final_output")
    builder.add_edge("final_output", END)
    return builder.compile()


def run_workflow(settings: Settings | None = None) -> HotelAgentState:
    settings = settings or load_settings()
    graph = build_workflow()
    return graph.invoke({"settings": settings, "errors": []})


def run_workflow_for_email(email: EmailInput, settings: Settings | None = None) -> HotelAgentState:
    settings = settings or load_settings()
    graph = build_workflow()
    return graph.invoke({"settings": settings, "errors": [], "email": email})


def _policy_route(state: HotelAgentState) -> str:
    intent = state["intent"]
    return "rag" if intent.questions else "skip"
