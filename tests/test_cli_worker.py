"""Bridge protocol tests use explicit fixtures; they make no model/network calls."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cli_worker", ROOT / "scripts" / "cli_worker.py")
worker = importlib.util.module_from_spec(spec)
sys.modules["cli_worker"] = worker
spec.loader.exec_module(worker)
start_spec = importlib.util.spec_from_file_location("mayak_start", ROOT / "scripts" / "start.py")
start = importlib.util.module_from_spec(start_spec)
start_spec.loader.exec_module(start)


def test_commands_remove_host_customizations_and_model_tools(tmp_path):
    claude = worker.make_command("claude", tmp_path, {"system": "test"})
    assert claude[claude.index("--tools") + 1] == ""
    for flag in ["--safe-mode", "--restricted", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"]:
        assert flag in claude
    codex = worker.make_command("codex", tmp_path, {})
    assert "--ignore-user-config" in codex and "--ephemeral" in codex
    assert "project_doc_max_bytes=0" in codex
    assert 'web_search="disabled"' in codex
    for capability in ["shell_tool", "apps", "plugins", "hooks", "memories", "multi_agent", "code_mode_host"]:
        assert codex[codex.index(capability) - 1] == "--disable"
    assert "danger-full-access" not in codex


def test_credentials_not_in_child_environment(monkeypatch):
    for name in ["CLI_WORKER_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY", "PYTHONPATH", "BASH_ENV"]:
        monkeypatch.setenv(name, "must-not-leave-worker")
    assert not any(value == "must-not-leave-worker" for value in worker.cli_environment().values())


def test_claude_preserves_actual_usage_but_not_estimated_subscription_cost():
    raw = json.dumps({"subtype": "success", "structured_output": {"answer": "fixture"},
                      "usage": {"input_tokens": 3, "cache_read_input_tokens": 14, "output_tokens": 6},
                      "modelUsage": {"fixture-model": {}}, "total_cost_usd": 42,
                      "session_id": "private", "email": "private"})
    result = worker.parse_result("claude", raw)
    assert json.loads(result["text"]) == {"answer": "fixture"}
    assert result["model"] == "fixture-model" and result["output_tokens"] == 6
    assert result["usage"]["cache_read_input_tokens"] == 14
    assert result["cost_usd"] is None and "private" not in json.dumps(result)


def test_codex_requires_completed_turn_and_rejects_tools():
    events = [{"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}},
              {"type": "turn.completed", "usage": {"input_tokens": 9, "output_tokens": 3}}]
    assert worker.parse_result("codex", "\n".join(map(json.dumps, events)))["input_tokens"] == 9
    with pytest.raises(worker.WorkerError):
        worker.parse_result("codex", json.dumps(events[0]))
    events.insert(0, {"type": "item.started", "item": {"type": "command_execution"}})
    with pytest.raises(worker.WorkerError, match="инструмент"):
        worker.parse_result("codex", "\n".join(map(json.dumps, events)))


def test_parse_error_never_leaks_raw_cli_reply():
    for provider in ["codex", "claude"]:
        with pytest.raises(worker.WorkerError) as caught:
            worker.parse_result(provider, "secret-auth-token")
        assert "secret-auth-token" not in str(caught.value)


@pytest.mark.parametrize("url", ["https://remote.test", "http://remote.test", "http://localhost@remote.test", "http://127.0.0.1/?token=x"])
def test_worker_rejects_remote_addresses(url):
    with pytest.raises(worker.WorkerError):
        worker.Worker(url, "x" * 40, "claude")


def test_redirect_never_forwards_bearer():
    with pytest.raises(worker.WorkerError):
        worker.NoRedirect().redirect_request(None, None, 302, "", {}, "https://remote.test")


def test_env_update_keeps_user_values_and_never_contains_provider_auth(tmp_path):
    path = tmp_path / ".env"
    path.write_text('AUTH_MODE=token\nPERSON_TOKENS={"example":"anna"}\nLLM_MODE=demo\n')
    values = start.prepare_env(path, "codex", 8081)
    content = path.read_text()
    assert 'AUTH_MODE=token' in content and 'PERSON_TOKENS={"example":"anna"}' in content
    assert 'LLM_MODE=cli' in content and 'LLM_MODE=demo' not in content
    assert len(values["CLI_WORKER_TOKEN"]) >= 32
    assert start.prepare_env(path, "claude", 8081)["CLI_WORKER_TOKEN"] == values["CLI_WORKER_TOKEN"]


def test_job_failure_is_reported_without_generated_fallback(monkeypatch):
    instance = worker.Worker("http://127.0.0.1:8080", "x" * 40, "claude")
    calls = []
    def post(path, body):
        calls.append((path, body))
        if path.endswith("claim"):
            return {"job": {"id": "12345678-1234-1234-1234-123456789abc", "claim_token": "lease", "request": {}}}
        return {"status": "ok"}
    instance.post = post
    def fail(*args):
        raise worker.WorkerError("Проверочная ошибка CLI.")
    monkeypatch.setattr(worker, "invoke", fail)
    assert instance.once()
    assert calls[-1][1] == {"claim_token": "lease", "status": "error", "error": "Проверочная ошибка CLI."}


def test_submit_retry_does_not_repeat_model_call(monkeypatch):
    instance = worker.Worker("http://127.0.0.1:8080", "x" * 40, "claude")
    invocations, submits = [], []
    def post(path, body):
        if path.endswith("claim"):
            return {"job": {"id": "12345678-1234-1234-1234-123456789abc", "claim_token": "lease", "request": {}}}
        submits.append(body)
        if len(submits) == 1:
            raise OSError("fixture lost response")
        return {"status": "ok"}
    instance.post = post
    instance.stopping.set()
    monkeypatch.setattr(worker, "invoke", lambda *args: invocations.append(args) or {"text": "fixture"})
    assert instance.once()
    assert len(invocations) == 1 and len(submits) == 2 and submits[0] == submits[1]


def test_cli_timeout_terminates_child(tmp_path):
    with pytest.raises(worker.WorkerError, match="180 секунд"):
        worker.run_bounded([sys.executable, "-c", "import time; time.sleep(10)"],
                           cwd=tmp_path, timeout=0.03)


def test_large_cli_reply_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "MAX_OUTPUT_BYTES", 100)
    with pytest.raises(worker.WorkerError, match="слишком большой"):
        worker.run_bounded([sys.executable, "-c", "print('x' * 1000)"], cwd=tmp_path)


def test_absent_usage_is_not_fabricated():
    with pytest.raises(worker.WorkerError, match="расход токенов"):
        worker.parse_result("claude", json.dumps({"result": "fixture", "subtype": "success"}))


def test_codex_native_schema_keeps_optional_fields_optional():
    from jsonschema import Draft202012Validator
    schema = {"type": "object", "properties": {"event_id": {"type": "string"},
              "project_id": {"type": "string"}}, "additionalProperties": False}
    normalized = worker.codex_schema(schema)
    validator = Draft202012Validator(normalized)
    for value in [{}, {"event_id": "E001"}, {"project_id": "P01"}, {"event_id": "E001", "project_id": "P01"}]:
        validator.validate(value)
    assert not validator.is_valid({"event_id": None})
    assert not validator.is_valid({"unexpected": "value"})


def test_codex_unwraps_native_result():
    events = [{"type": "item.completed", "item": {"type": "agent_message", "text": '{"result":{"blocker":"text"}}'}},
              {"type": "turn.completed", "usage": {"input_tokens": 9, "output_tokens": 3}}]
    result = worker.parse_result("codex", "\n".join(map(json.dumps, events)), wrapped=True)
    assert json.loads(result["text"]) == {"blocker": "text"}


def test_initial_connection_error_is_safe():
    instance = worker.Worker("http://127.0.0.1:8080", "x" * 40, "claude")
    def fail(*args):
        raise OSError("sensitive internal error")
    instance.post = fail
    with pytest.raises(worker.WorkerError) as caught:
        instance.run()
    assert "sensitive" not in str(caught.value)


def test_start_rejects_old_compose(monkeypatch):
    class Result:
        stdout = "2.23.1"
    monkeypatch.setattr(start.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(worker.WorkerError, match="2.24.4"):
        start.docker_check()


def test_start_accepts_supported_compose_version(monkeypatch):
    class Result:
        stdout = "v2.37.1-desktop.1"
    monkeypatch.setattr(start.subprocess, "run", lambda *args, **kwargs: Result())
    start.docker_check()
