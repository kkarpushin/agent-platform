"""Backend contracts against a real PostgreSQL instance in isolated schemas.

Run with TEST_DATABASE_URL. Each test creates/drops only its random test schema;
application tables and user runs are never cleared.
"""
import importlib.util
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mayak_backend", ROOT / "platform/app.py")
backend = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)


def test_schema_errors_do_not_echo_private_values():
    schema = {"type": "object", "properties": {"amount": {"type": "number"}}, "additionalProperties": False}
    with pytest.raises(HTTPException) as raised:
        backend.schema_check(schema, {"amount": "PRIVATE_AMOUNT"}, "Выход")
    assert "PRIVATE_AMOUNT" not in raised.value.detail
    assert "amount" in raised.value.detail


def test_demo_uses_available_ids_and_does_not_invent_usage():
    body = backend.LLMBody(purpose="select_services", data={"task": "Нужен аудит", "services": [{"data": {"service_id": "S01", "keywords": ["аудит"]}}, {"data": {"service_id": "S02", "keywords": ["база знаний"]}}]})
    assert json.loads(backend.demo_response(body)) == {"service_ids": ["S01"]}


@pytest.fixture
def system(tmp_path, monkeypatch):
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Укажите TEST_DATABASE_URL для настоящих проверок PostgreSQL")
    schema = "test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    for folder in ("config", "knowledge", "agents", "skills", "processes"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    settings = backend.Settings(root=tmp_path, database_url=make_conninfo(dsn, options=f"-c search_path={schema}"), auth_mode="demo", llm_mode="demo", agent_urls={"client-brief": "http://brief", "commercial-proposal": "http://proposal"}, anthropic_api_key="", anthropic_model="test-model", input_price=None, output_price=None)
    app = backend.create_app(settings)
    monkeypatch.setattr(backend, "resolve_agent_addresses", lambda _: {"172.30.0.21", "172.30.0.22"})
    original_client = httpx.Client
    state = {"calls": 0, "behavior": "ok", "tokens": [], "internal": []}
    with TestClient(app) as client:
        def agent_handler(request):
            state["calls"] += 1
            payload = json.loads(request.content)
            token = payload["run_token"]
            state["tokens"].append(token)
            headers = {"Authorization": "Bearer " + token}
            if state["behavior"] == "invalid":
                return httpx.Response(200, json={"output": {"unwanted": "PRIVATE_OUTPUT"}, "steps": []})
            if state["behavior"] == "echo_token":
                return httpx.Response(200, json={"output": {"markdown": token, "client": "Орбита", "sources": []}, "steps": []})
            if state["behavior"] == "timeout":
                raise httpx.ReadTimeout("private upstream error")
            knowledge = client.get("/internal/context", params={"section": "clients", "q": "Орбита"}, headers=headers)
            assert knowledge.status_code == 200
            state["internal"].append(knowledge.json())
            undeclared = client.get("/internal/context", params={"section": "technical"}, headers=headers)
            assert undeclared.status_code == 403
            if state["behavior"] == "llm":
                for _ in range(7):
                    result = client.post("/internal/llm", headers=headers, json={"purpose": state.get("purpose", "draft_proposal"), "data": {"client": "Орбита", "task": "Аудит", "total_price": 1800, "timeline": 5}})
                    state["internal"].append({"status": result.status_code, "body": result.json()})
            if request.url.host == "proposal":
                costs = client.get("/internal/context", params={"section": "costs"}, headers=headers)
                state["internal"].append(costs.json())
                output = {"markdown": "Предложение", "services": [{"service_id": "S01", "name": "Аудит", "price_usd": 1800, "days": 5}], "total_price": 1800, "timeline": 5, "cases": [], "assumptions": []}
            else:
                output = {"markdown": "Справка", "client": "Орбита", "sources": [r["id"] for r in knowledge.json()["records"]]}
            return httpx.Response(200, json={"output": output, "steps": [{"title": "Проверено", "detail": "Источники получены через платформу"}]})
        def mocked_client(*args, **kwargs):
            return original_client(*args, **kwargs, transport=httpx.MockTransport(agent_handler))
        monkeypatch.setattr(backend.httpx, "Client", mocked_client)
        yield client, app, state, tmp_path
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def launch(client, agent="client-brief", person="mark", request_id=None):
    data = {"client": "Орбита"}
    if agent == "commercial-proposal":
        data.update(task="Нужен аудит", deadline="Через месяц", language="ru")
    return client.post("/api/runs", headers={"X-Person": person}, json={"agent": agent, "input": data, "request_id": request_id or str(uuid.uuid4())})


def test_real_russian_fts_and_role_filter_before_search(system):
    client, app, state, _ = system
    assert client.get("/api/health").json()["database"] == "ok"
    result = client.get("/api/knowledge", params={"section": "services", "q": "процессов"}).json()
    assert any(r["data"].get("service_id") == "S01" for r in result["records"])
    costs = client.get("/api/knowledge", params={"section": "costs"}).json()
    assert costs["records"] == [] and costs["hidden_count"] > 0
    finance = client.get("/api/knowledge", params={"section": "costs"}, headers={"X-Person": "irina"})
    assert finance.status_code == 200 and finance.json()["records"]
    bootstrap = client.get("/api/bootstrap").json()
    assert len(bootstrap["layers"]) == 9
    assert bootstrap["skills"] and bootstrap["goals"]


def test_role_denied_before_agent_call_and_invalid_input(system):
    client, _, state, _ = system
    assert launch(client, "commercial-proposal", "olga").status_code == 403
    assert state["calls"] == 0
    result = client.post("/api/runs", json={"agent": "client-brief", "input": {"client": "Орбита", "unexpected": "secret"}, "request_id": "invalid-001"})
    assert result.status_code == 422 and "secret" not in result.text
    assert state["calls"] == 0


def test_run_idempotency_context_trace_and_token_revocation(system):
    client, app, state, _ = system
    first = launch(client, "commercial-proposal", request_id="repeat-0001").json()
    assert first["status"] == "needs_review", first
    assert launch(client, "commercial-proposal", request_id="repeat-0001").json()["id"] == first["id"]
    assert state["calls"] == 1
    assert launch(client, request_id="repeat-0001").status_code == 409
    costs = next(e for e in first["context_events"] if e["section"] == "costs")
    assert costs["records"] == [] and costs["hidden_count"] > 0
    encoded = json.dumps(first, ensure_ascii=False)
    assert "COST-S" not in encoded and state["tokens"][0] not in encoded
    assert client.get("/internal/context?section=clients", headers={"Authorization": "Bearer " + state["tokens"][0]}).status_code == 401
    with app.state.db() as connection:
        assert not connection.execute("SELECT active FROM run_tokens").fetchone()["active"]


def test_immutable_versions_and_exact_approval(system):
    client, _, state, _ = system
    run = launch(client).json()
    url = "/api/runs/" + run["id"]
    assert client.post(url + "/approve", json={"version": 1}).status_code == 403
    approved = client.post(url + "/approve", headers={"X-Person": "anna"}, json={"version": 1, "note": "Проверено"}).json()
    assert approved["status"] == "approved"
    edited = client.post(url + "/revisions", json={"base_version": 1, "markdown": "Исправлено"}).json()
    assert edited["status"] == "needs_review" and edited["current_version"] == 2
    assert edited["versions"][0]["output"]["markdown"] == "Справка"
    assert edited["decisions"][0]["version"] == 1
    assert client.post(url + "/approve", headers={"X-Person": "anna"}, json={"version": 1}).status_code == 409
    assert client.post(url + "/revisions", json={"base_version": 1, "markdown": "Другие правки"}).status_code == 409
    assert client.get(url, headers={"X-Person": "olga"}).status_code == 404
    assert client.post(url + "/learnings", headers={"X-Person": "anna"}, json={"text": "Проверить источники"}).status_code == 409
    assert client.post(url + "/approve", headers={"X-Person": "anna"}, json={"version": 2}).status_code == 200
    assert client.post(url + "/learnings", headers={"X-Person": "anna"}, json={"text": "Проверить источники"}).status_code == 200
    assert client.get("/api/memory").json()["learnings"]
    assert client.get("/api/memory", headers={"X-Person": "olga"}).json() == {"decisions": [], "learnings": []}


@pytest.mark.parametrize("behavior", ["invalid", "echo_token", "timeout"])
def test_failed_agent_preserves_error_without_output_or_token(system, behavior):
    client, _, state, _ = system
    state["behavior"] = behavior
    result = launch(client).json()
    assert result["status"] == "error" and result["error"]
    assert result["output"] is None and result["versions"] == []
    assert "PRIVATE_OUTPUT" not in json.dumps(result)
    assert state["tokens"][0] not in json.dumps(result)
    assert client.get("/internal/context?section=clients", headers={"Authorization": "Bearer " + state["tokens"][0]}).status_code == 401


def test_atomic_sync_failure_keeps_index_and_deleted_sources_removed(system):
    client, app, _, root = system
    before = client.get("/api/knowledge?section=services").json()
    broken = root / "knowledge/services/broken.md"
    broken.write_text("---\nid: broken\n---\nInvalid")
    result = client.post("/api/sync", headers={"X-Person": "anna"})
    assert result.status_code == 422
    assert client.get("/api/knowledge?section=services").json() == before
    broken.unlink()
    deleted = root / "knowledge/services/S01.md"
    deleted.unlink()
    assert client.post("/api/sync", headers={"X-Person": "anna"}).status_code == 200
    assert all(r["id"] != "S01" for r in client.get("/api/knowledge?section=services").json()["records"])


def test_gateway_call_limit_and_demo_usage(system):
    client, _, state, _ = system
    state["behavior"] = "llm"
    run = launch(client, "commercial-proposal").json()
    assert run["status"] == "needs_review"
    assert len(run["model_calls"]) == 6
    assert run["cost_usd"] == 0 and run["input_tokens"] == run["output_tokens"] == 0
    calls = [r for r in state["internal"] if "status" in r]
    assert [c["status"] for c in calls] == [200] * 6 + [429]
    assert all(c["skill_refs"] for c in run["model_calls"])


def test_failed_real_gateway_calls_are_counted_and_no_demo_fallback(system):
    client, app, state, _ = system
    app.state.settings.llm_mode = "anthropic"
    state["behavior"] = "llm"
    run = launch(client).json()
    calls = [r for r in state["internal"] if "status" in r]
    assert [c["status"] for c in calls] == [503] * 6 + [429]
    assert all(c["mode"] == "anthropic" and c["status"] == "error" for c in run["model_calls"])
    assert run["cost_usd"] is None


def test_person_token_mode_ignores_role_switch_header(system):
    client, app, _, _ = system
    app.state.settings.auth_mode = "token"
    app.state.settings.person_tokens = {"test-token-123": "mark"}
    assert client.get("/api/bootstrap", headers={"X-Person": "anna"}).status_code == 401
    response = client.get("/api/bootstrap", headers={"X-Person": "anna", "Authorization": "Bearer test-token-123"})
    assert response.status_code == 200
    assert response.json()["person"]["id"] == "mark"
    assert len(response.json()["people"]) == 1
    assert client.post("/api/sync", headers={"X-Person": "anna", "Authorization": "Bearer test-token-123"}).status_code == 403


@pytest.mark.parametrize("peer", ["172.30.0.21", "::ffff:172.30.0.21"])
def test_agent_network_cannot_impersonate_employee_or_read_public_surface(system, peer):
    client, app, _, _ = system
    agent_client = TestClient(app, client=(peer, 55000))
    try:
        headers = {"X-Person": "anna", "X-Forwarded-For": "127.0.0.1", "Forwarded": "for=127.0.0.1"}
        for path in ("/api/bootstrap", "/api/knowledge?section=costs", "/api/runs", "/api/memory", "/docs", "/openapi.json", "/redoc", "/", "/app.js"):
            response = agent_client.get(path, headers=headers)
            assert response.status_code == 403, (path, response.text)
            assert "COST-S" not in response.text
        assert agent_client.post("/api/sync", headers=headers).status_code == 403
        assert agent_client.get("/internal/context?section=costs", headers=headers).status_code == 401
        assert agent_client.get("/api/health", headers=headers).status_code == 200
        assert client.get("/api/bootstrap").status_code == 200
    finally:
        agent_client.close()


def test_network_gate_fails_closed_and_refreshes_container_addresses(system, monkeypatch):
    client, app, _, _ = system
    def unavailable(_):
        raise OSError("DNS unavailable")
    monkeypatch.setattr(backend, "resolve_agent_addresses", unavailable)
    assert client.get("/api/bootstrap").status_code == 503
    assert client.post("/api/sync", headers={"X-Person": "anna"}).status_code == 503
    assert client.get("/api/health").status_code == 200
    assert client.get("/internal/context?section=clients").status_code == 401
    monkeypatch.setattr(backend, "resolve_agent_addresses", lambda _: {"testclient"})
    assert client.get("/api/bootstrap").status_code == 403
    monkeypatch.setattr(backend, "resolve_agent_addresses", lambda _: {"172.30.0.99"})
    assert client.get("/api/bootstrap").status_code == 200


def test_resolver_includes_all_addresses_and_normalizes_ipv6(monkeypatch):
    def resolve(host, port, **kwargs):
        assert host in {"brief", "proposal"}
        return [(backend.socket.AF_INET, backend.socket.SOCK_STREAM, 6, "", ("172.30.0.21", port)),
                (backend.socket.AF_INET6, backend.socket.SOCK_STREAM, 6, "", ("::ffff:172.30.0.21", port, 0, 0)),
                (backend.socket.AF_INET6, backend.socket.SOCK_STREAM, 6, "", ("fd00::21", port, 0, 0))]
    monkeypatch.setattr(backend.socket, "getaddrinfo", resolve)
    assert backend.resolve_agent_addresses({"one": "http://brief:8000", "two": "http://proposal:8000"}) == {"172.30.0.21", "fd00::21"}


def test_approval_rejects_changed_knowledge_without_rewriting_result(system):
    client, _, _, root = system
    run = launch(client).json()
    assert run["context_events"][0]["records"]
    source = root / "knowledge/clients" / (run["context_events"][0]["records"][0]["id"] + ".md")
    source.write_text(source.read_text() + "\nОбновлённые сведения клиента.\n")
    assert client.post("/api/sync", headers={"X-Person": "anna"}).status_code == 200
    read = client.get("/api/runs/" + run["id"]).json()
    assert read["source_warnings"]
    assert read["versions"] == run["versions"]
    response = client.post("/api/runs/" + run["id"] + "/approve", headers={"X-Person": "anna"}, json={"version": 1})
    assert response.status_code == 409 and "Источники изменились" in response.text


@pytest.mark.parametrize("cache,stop_reason", [(False, "end_turn"), (True, "end_turn"), (False, "max_tokens")])
def test_real_gateway_usage_skill_injection_and_truncation(system, monkeypatch, cache, stop_reason):
    client, app, state, _ = system
    settings = app.state.settings
    settings.llm_mode, settings.anthropic_api_key = "anthropic", "platform-only-secret"
    settings.input_price, settings.output_price = "3", "15"
    state["behavior"] = "llm"
    requests = []
    def provider(url, **kwargs):
        requests.append(kwargs)
        return httpx.Response(200, json={"model": "configured-model", "stop_reason": stop_reason, "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50 if cache else 0}, "content": [{"type": "text", "text": "Текст ответа"}]})
    monkeypatch.setattr(backend.httpx, "post", provider)
    run = launch(client, "commercial-proposal").json()
    assert len(requests) == 6
    assert "Способы работы платформы" in requests[0]["json"]["system"]
    assert run["input_tokens"] == (150 if cache else 100) * 6
    assert run["output_tokens"] == 120
    assert (run["cost_usd"] is None) if cache else (abs(run["cost_usd"] - 0.0036) < 0.0000001)
    assert "platform-only-secret" not in json.dumps(run)
    assert all(c["skill_refs"] and c["usage"] for c in run["model_calls"])
    expected = "error" if stop_reason == "max_tokens" else "completed"
    assert all(c["status"] == expected for c in run["model_calls"])
    if stop_reason == "max_tokens":
        assert all(item["status"] == 502 for item in state["internal"] if "status" in item and item["status"] != 429)


def test_custom_llm_purpose_is_supported_in_real_mode(system, monkeypatch):
    client, app, state, _ = system
    app.state.settings.llm_mode = "anthropic"
    app.state.settings.anthropic_api_key = "test-only-key"
    state["behavior"], state["purpose"] = "llm", "summarize_client"
    def provider(url, **kwargs):
        return httpx.Response(200, json={"model":"configured", "stop_reason":"end_turn", "usage":{"input_tokens":12,"output_tokens":5}, "content":[{"type":"text","text":"Краткая справка"}]})
    monkeypatch.setattr(backend.httpx, "post", provider)
    run = launch(client).json()
    assert len(run["model_calls"]) == 6
    assert all(c["purpose"] == "summarize_client" and c["status"] == "completed" for c in run["model_calls"])


def test_unknown_demo_purpose_never_silently_generates_proposal(system):
    client, app, state, _ = system
    state["behavior"], state["purpose"] = "llm", "summarize_client"
    run = launch(client).json()
    calls = [x for x in state["internal"] if "status" in x]
    assert all(x["status"] in (422, 429) for x in calls)
    assert all(c["status"] == "error" for c in run["model_calls"])
    assert not any("text" in x.get("body", {}) for x in calls)
