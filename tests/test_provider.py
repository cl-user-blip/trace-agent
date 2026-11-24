import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from trace_agent.planners import ChatPlanner


def test_live_provider_is_opt_in_and_requires_explicit_model(monkeypatch):
    monkeypatch.delenv("TRACE_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("TRACE_AGENT_MODEL", raising=False)
    with pytest.raises(ValueError, match="required"):
        ChatPlanner()


def test_chat_provider_contract_with_mock_response(monkeypatch):
    monkeypatch.setenv("TRACE_AGENT_API_KEY", "fake-test-secret")
    monkeypatch.setenv("TRACE_AGENT_MODEL", "test-model")
    monkeypatch.setenv("TRACE_AGENT_BASE_URL", "https://example.invalid/v1")
    captured = {}

    def fake_open(request, timeout):
        captured.update(json.loads(request.data))
        assert request.get_header("Authorization") == "Bearer fake-test-secret"
        assert timeout == 30
        return BytesIO(json.dumps({"choices": [{"message": {"tool_calls": [{"id": "x", "function": {
            "name": "search", "arguments": '{"query":"cache"}'}}]}}]}).encode())

    monkeypatch.setattr("trace_agent.planners.urllib.request.build_opener", lambda *a: SimpleNamespace(open=fake_open))
    result = ChatPlanner().decide({"task": "cache", "history": []})
    assert result == {"type": "tool", "name": "search", "arguments": {"query": "cache"}}
    assert captured["parallel_tool_calls"] is False
    assert "fake-test-secret" not in json.dumps(captured)


@pytest.mark.parametrize("base", ["http://example.com/v1", "https://user:secret@example.com/v1", "https://example.com/v1?key=secret"])
def test_live_provider_rejects_insecure_or_credential_urls(monkeypatch, base):
    monkeypatch.setenv("TRACE_AGENT_API_KEY", "fake")
    monkeypatch.setenv("TRACE_AGENT_MODEL", "fake")
    monkeypatch.setenv("TRACE_AGENT_BASE_URL", base)
    with pytest.raises(ValueError):
        ChatPlanner()


@pytest.mark.parametrize("response", [
    {}, [], {"choices": []}, {"choices": [None]}, {"choices": [{"message": "text"}]},
    {"choices": [{"message": {"tool_calls": "invalid"}}]},
    {"choices": [{"message": {"tool_calls": [{"function": {"name": "search", "arguments": "[]"}}]}}]},
    {"choices": [{"message": {"tool_calls": [{"function": {"name": "search", "arguments": "{"}}]}}]},
    {"choices": [{"message": {"content": None}}]},
])
def test_malformed_provider_responses_are_controlled_errors(monkeypatch, response):
    monkeypatch.setenv("TRACE_AGENT_API_KEY", "fake")
    monkeypatch.setenv("TRACE_AGENT_MODEL", "fake")
    monkeypatch.setenv("TRACE_AGENT_BASE_URL", "https://example.invalid/v1")
    def fake_open(request, timeout):
        return BytesIO(json.dumps(response).encode())
    monkeypatch.setattr("trace_agent.planners.urllib.request.build_opener", lambda *a: SimpleNamespace(open=fake_open))
    with pytest.raises(ValueError):
        ChatPlanner().decide({"task": "cache", "history": []})


def test_redirect_is_rejected_before_new_request():
    import urllib.error
    import urllib.request
    from trace_agent.planners import NoRedirect

    request = urllib.request.Request("https://example.invalid/v1", headers={"Authorization": "Bearer fake"})
    with pytest.raises(urllib.error.HTTPError) as error:
        NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://attacker.invalid")
    assert error.value.code == 302
