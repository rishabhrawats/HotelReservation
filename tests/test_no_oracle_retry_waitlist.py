import pytest

from app.tools import oracle_booking_stub
from app.graph.workflow import run_workflow


def test_oracle_stub_functions_raise_not_implemented():
    for name in ["modify_booking"]:
        with pytest.raises(NotImplementedError):
            getattr(oracle_booking_stub, name)()


def test_no_retry_or_waitlist_functions_exist():
    exported = dir(oracle_booking_stub)
    assert not any("retry" in name.lower() for name in exported)
    assert not any("waitlist" in name.lower() for name in exported)


def test_no_retry_or_waitlist_functions_exist_in_app_code():
    app_root = __import__("pathlib").Path(__file__).resolve().parents[1] / "app"
    for path in app_root.rglob("*.py"):
        tree = __import__("ast").parse(path.read_text(encoding="utf-8"))
        for node in __import__("ast").walk(tree):
            name = getattr(node, "name", "")
            if not name:
                continue
            assert "retry" not in name.lower()
            assert "waitlist" not in name.lower()


def test_workflow_does_not_call_oracle_stub(monkeypatch, test_settings):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Oracle stub should not be called in the current workflow")

    for name in ["check_availability", "create_booking", "cancel_booking", "modify_booking"]:
        monkeypatch.setattr(oracle_booking_stub, name, fail_if_called)
    monkeypatch.setattr(
        "app.graph.nodes.retrieve_policy_contexts",
        lambda questions, settings=None, top_k=5: {question.question: [] for question in questions},
    )
    monkeypatch.setattr(
        "app.graph.nodes.answer_policy_question",
        lambda question, chunks, settings=None: __import__("app.ai.schemas", fromlist=["PolicyAnswer"]).PolicyAnswer(
            question=question.question,
            answer="I'm unable to confirm this from the available hotel policy information. Our reservations team will review and confirm.",
            sources=[],
            confidence=0.2,
            insufficient_policy_context=True,
        ),
    )
    monkeypatch.setattr("app.graph.nodes.send_or_create_draft", lambda *args, **kwargs: "DRAFT_ONLY")

    state = run_workflow(test_settings)

    assert state["final_result"].reply.reply_type == "policy_answer_plus_booking_acknowledgement"
