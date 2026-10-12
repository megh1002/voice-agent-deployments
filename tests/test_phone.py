"""The Vapi phone endpoint: auth, one agent session per call, OpenAI-style streaming.
The model is scripted, so no API calls are made.
"""

import importlib
import json
import warnings
from types import SimpleNamespace as NS

from core import llm


def client_with_secret(monkeypatch, secret="phone-secret"):
    monkeypatch.setenv("VAPI_SECRET", secret)
    monkeypatch.delenv("PUBLIC_MODE", raising=False)
    import webapp.app
    mod = importlib.reload(webapp.app)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
    return TestClient(mod.app), mod


def vapi_body(call_id, *turns, stream=True):
    messages = [{"role": "system", "content": "(vapi system prompt, ignored)"},
                {"role": "assistant", "content": "Thanks for calling Ravenswood Family Medicine..."}]
    for t in turns:
        messages.append({"role": "user", "content": t})
    return {"model": "custom", "stream": stream, "messages": messages,
            "call": {"id": call_id, "customer": {"number": "+15555550123"}}}


def scripted(*replies):
    replies = iter(replies)
    return lambda **kw: NS(stop_reason="end_turn", content=[NS(type="text", text=next(replies))])


AUTH = {"Authorization": "Bearer phone-secret"}


def test_phone_is_off_without_a_secret(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    monkeypatch.delenv("VAPI_SECRET")
    assert client.post("/vapi/chat/completions", json=vapi_body("c1", "hi")).status_code == 503


def test_wrong_secret_is_rejected(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    r = client.post("/vapi/chat/completions", json=vapi_body("c1", "hi"), headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_turns_on_the_same_call_share_one_session(monkeypatch):
    client, mod = client_with_secret(monkeypatch)
    monkeypatch.setattr(llm, "create", scripted("How can I help?", "Sure, what's your date of birth?"))
    r1 = client.post("/vapi/chat/completions", json=vapi_body("call-abc", "Hi"), headers=AUTH)
    r2 = client.post("/vapi/chat/completions", json=vapi_body("call-abc", "Hi", "I want to cancel"), headers=AUTH)
    assert r1.status_code == r2.status_code == 200
    chunks = [json.loads(l[6:]) for l in r2.text.splitlines() if l.startswith("data: {")]
    assert chunks[0]["choices"][0]["delta"]["content"] == "Sure, what's your date of birth?"
    assert r2.text.rstrip().endswith("data: [DONE]")
    session = mod.PHONE_CALLS["call-abc"]
    assert [t["text"] for t in session.record["transcript"] if t["speaker"] == "caller"] == ["Hi", "I want to cancel"]
    assert len(session.record["latencies_s"]) == 2


def test_non_streaming_response(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    monkeypatch.setattr(llm, "create", scripted("Hello there."))
    r = client.post("/vapi/chat/completions", json=vapi_body("c2", "Hi", stream=False), headers=AUTH)
    assert r.json()["choices"][0]["message"]["content"] == "Hello there."


def test_no_new_caller_words_means_no_model_call(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    monkeypatch.setattr(llm, "create", lambda **kw: (_ for _ in ()).throw(AssertionError("should not call")))
    body = vapi_body("c3")  # ends with the assistant's greeting
    r = client.post("/vapi/chat/completions", json=body, headers=AUTH)
    assert r.status_code == 200


def teardown_module():
    import webapp.app
    importlib.reload(webapp.app)


def test_secret_accepted_in_common_formats(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    monkeypatch.setattr(llm, "create", scripted("a", "b", "c", "d"))
    for i, headers in enumerate([{"Authorization": "Bearer phone-secret"}, {"Authorization": "phone-secret"},
                                 {"X-Api-Key": "phone-secret"}, {"Authorization": "Bearer Bearer phone-secret"}]):
        assert client.post("/vapi/chat/completions", json=vapi_body(f"fmt{i}", "hi"), headers=headers).status_code == 200
    assert client.post("/vapi/chat/completions", json=vapi_body("fmtx", "hi"),
                       headers={"X-Api-Key": "wrong"}).status_code == 401
