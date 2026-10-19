"""Учебная платформа: границы доступа, знания, запуски и решения людей.

Запуск: uvicorn app:app --app-dir platform --host 0.0.0.0 --port 8080.
Агенты исполняются отдельными HTTP-сервисами; бизнес-логики здесь нет.
"""
from __future__ import annotations

import hashlib
import asyncio
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import psycopg
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft202012Validator, ValidationError, SchemaError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

LOG = logging.getLogger("agent_platform")
SECTION_TITLES = {"projects": "Проекты", "rules": "Правила работы", "finance": "Внутренние финансы"}
LAYER_TITLES = [
    "Цели и люди", "Роли и полномочия", "Знания и информация", "Скиллы",
    "Агенты и модели", "Инструменты и доступы", "Процессы", "Запуск и состояние",
    "Проверка и улучшение",
]
PROCESS_STEPS = ["Прочитать сообщение", "Найти знания и задачи", "Предложить действие", "Проверить", "Получить решение Анны", "Обновить доску", "Проверить продолжение"]


@dataclass
class Settings:
    root: Path = field(default_factory=lambda: Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parents[1])))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "postgresql://platform:platform@db:5432/platform"))
    platform_url: str = field(default_factory=lambda: os.getenv("PLATFORM_URL", "http://platform:8080"))
    agent_urls: dict = field(default_factory=lambda: json.loads(os.getenv("AGENT_URLS", '{}')))
    auth_mode: str = field(default_factory=lambda: os.getenv("AUTH_MODE", "demo"))
    person_tokens: dict = field(default_factory=lambda: json.loads(os.getenv("PERSON_TOKENS", '{}')))
    llm_mode: str = field(default_factory=lambda: os.getenv("LLM_MODE", "cli"))
    agent_timeout: float = field(default_factory=lambda: float(os.getenv("AGENT_TIMEOUT_SECONDS", "480")))

    cli_worker_token: str = field(default_factory=lambda: os.getenv("CLI_WORKER_TOKEN", ""))
    cli_provider: str = field(default_factory=lambda: os.getenv("CLI_PROVIDER", "codex"))

    def validate(self):
        self.root = Path(self.root)
        if self.auth_mode not in {"demo", "token"}:
            raise ValueError("AUTH_MODE должен быть demo или token")
        if self.llm_mode not in {"cli", "fixture"}:
            raise ValueError("LLM_MODE должен быть cli; fixture предназначен только для автоматических тестов")
        if self.cli_provider not in {"claude", "codex"}:
            raise ValueError("CLI_PROVIDER должен быть claude или codex")
        if self.auth_mode == "token" and not self.person_tokens:
            raise ValueError("В режиме token заполните PERSON_TOKENS")
        if not 1 <= self.agent_timeout <= 600:
            raise ValueError("AGENT_TIMEOUT_SECONDS должен быть от 1 до 600")
        if not isinstance(self.agent_urls, dict):
            raise ValueError("AGENT_URLS должен быть объектом адресов сервисов")
        for endpoint in self.agent_urls.values():
            parsed = urlsplit(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Адрес агента должен быть HTTP(S) URL без учётных данных")


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RunBody(StrictBody):
    agent: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    input: dict[str, Any]
    refresh: bool = False
    retry_reason: str = Field(default="", max_length=2000)
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")


class RevisionBody(StrictBody):
    base_version: int = Field(ge=1)
    markdown: str = Field(min_length=1, max_length=100000)


class ApprovalBody(StrictBody):
    version: int = Field(ge=1)
    note: str = Field(default="", max_length=5000)


class LearningBody(StrictBody):
    text: str = Field(min_length=5, max_length=5000)


class LLMBody(StrictBody):
    purpose: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    system: str = Field(default="", max_length=30000)
    prompt: str = Field(default="", max_length=60000)
    data: dict[str, Any] = Field(default_factory=dict)
    max_tokens: int = Field(default=1024, ge=256, le=4096)
    response_schema: dict[str, Any] | None = None
    skill_name: str | None = Field(default=None, max_length=80)


class WorkerBody(StrictBody):
    worker_id: str = Field(min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9._:-]+$')
    provider: str = Field(pattern=r'^(claude|codex)$')


class WorkerResult(StrictBody):
    text: str = Field(max_length=200000)
    model: str = Field(max_length=200)
    provider: str = Field(pattern=r'^(claude|codex)$')
    input_tokens: int = Field(ge=0,le=10000000)
    output_tokens: int = Field(ge=0,le=1000000)
    usage: dict[str,Any] = Field(default_factory=dict)
    duration_ms: int = Field(ge=0,le=600000)
    cost_usd: None = None


class WorkerCompleteBody(StrictBody):
    claim_token: str = Field(min_length=20,max_length=200)
    status: str = Field(pattern=r'^(completed|error)$')
    result: WorkerResult | None = None
    error: str | None = Field(default=None,max_length=2000)


class InboxBody(StrictBody):
    event_id: str = Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9._:-]+$')
    project_id: str = Field(min_length=1,max_length=80)
    text: str = Field(min_length=1,max_length=20000)
    author: str = Field(min_length=1,max_length=100)
    received_at: datetime


def normalized_address(address: str) -> str:
    """Compare IPv4 and IPv4-mapped IPv6 peers as the same address."""
    try:
        parsed = ipaddress.ip_address(address)
        return str(parsed.ipv4_mapped or parsed) if isinstance(parsed, ipaddress.IPv6Address) else str(parsed)
    except ValueError:
        # TestClient uses the literal name 'testclient'; actual sockets return IPs.
        return address


def resolve_agent_addresses(agent_urls: dict[str, str]) -> set[str]:
    """Resolve current container IPs, without retaining stale Docker DNS answers.

    Resolution errors propagate: the public surface must fail closed if an
    agent's network identity cannot be established. Forwarded headers are never
    used here; uvicorn must also run with --no-proxy-headers.
    """
    addresses = set()
    for endpoint in agent_urls.values():
        parsed = urlsplit(endpoint)
        resolved = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if not resolved:
            raise OSError("Не удалось определить адрес сервиса агента")
        addresses.update(normalized_address(item[4][0]) for item in resolved)
    return addresses


def frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(f"{path.name}: нужен YAML-заголовок между строками ---")
    meta = yaml.safe_load(parts[1])
    if not isinstance(meta, dict):
        raise ValueError(f"{path.name}: заголовок должен быть объектом")
    return meta, parts[2].strip()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def schema_check(schema: dict, value: Any, label: str):
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{label}: значения должны быть корректным JSON без NaN и Infinity") from None
    try:
        Draft202012Validator(schema).validate(value)
    except ValidationError as exc:
        # Never include invalid values, agent exception details, or private text in an error.
        path = ".".join(map(str, exc.absolute_path)) or "корень"
        raise HTTPException(422, f"{label}: поле «{path}» не соответствует схеме (правило {exc.validator})") from None


def load_sources(root: Path) -> tuple[dict, list[dict]]:
    roles = yaml.safe_load((root / "config/roles.yaml").read_text(encoding="utf-8"))
    if isinstance(roles, dict) and set(roles) == {"roles"}:
        roles = roles["roles"]
    people = yaml.safe_load((root / "config/people.yaml").read_text(encoding="utf-8"))
    if isinstance(people, dict) and set(people) == {"people"}:
        people = people["people"]
    if not isinstance(roles, dict) or not roles or not isinstance(people, list):
        raise ValueError("Проверьте структуру config/roles.yaml и people.yaml")
    for name, role in roles.items():
        if not isinstance(role, dict) or not isinstance(role.get("sections"), list):
            raise ValueError(f"У роли {name} отсутствует список sections")
    ids = set()
    for person in people:
        if not isinstance(person, dict) or not person.get("id") or person.get("role") not in roles or person["id"] in ids:
            raise ValueError("Некорректный или повторный сотрудник в people.yaml")
        ids.add(person["id"])
    agents = {}
    for path in sorted((root / "agents").glob("*/agent.yaml")):
        if path.parent.name.startswith("_"):
            continue
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        required = {"name", "version", "owner", "description", "input", "output", "context", "roles"}
        if not isinstance(manifest, dict) or not required <= manifest.keys():
            raise ValueError(f"Неполный манифест {path.parent.name}")
        if manifest["name"] != path.parent.name or manifest["name"] in agents:
            raise ValueError("Имя агента должно совпадать с папкой и быть уникальным")
        if not isinstance(manifest["roles"], list) or not set(manifest["roles"]) <= roles.keys():
            raise ValueError(f"Неизвестные роли агента {manifest['name']}")
        if not isinstance(manifest["context"], list):
            raise ValueError(f"context агента {manifest['name']} должен быть списком")
        if not isinstance(manifest.get("workspace", False), bool):
            raise ValueError("workspace должен быть true или false: это разрешение читать рабочее состояние")
        for key in ("input", "output"):
            Draft202012Validator.check_schema(manifest[key])
            if manifest[key].get("type") != "object" or manifest[key].get("additionalProperties") is not False:
                raise ValueError(f"{manifest['name']}.{key}: нужна схема object с additionalProperties: false")
        agents[manifest["name"]] = manifest
    records, record_ids = [], set()
    for path in sorted((root / "knowledge").glob("*/*.md")):
        meta, content = frontmatter(path)
        required = {"id", "section", "access", "owner", "updated", "title", "data"}
        if not required <= meta.keys() or not isinstance(meta["data"], dict):
            raise ValueError(f"Неполные метаданные {path.name}")
        if meta["id"] in record_ids:
            raise ValueError(f"Повторный id знания в {path.name}")
        if meta["section"] != path.parent.name or not isinstance(meta["access"], list) or not set(meta["access"]) <= roles.keys():
            raise ValueError(f"Некорректные section/access в {path.name}")
        if meta["owner"] not in ids:
            raise ValueError(f"Неизвестный владелец в {path.name}")
        try:
            meta["updated"] = date.fromisoformat(str(meta["updated"]))
        except ValueError:
            raise ValueError(f"Некорректная дата updated в {path.name}") from None
        for key in ("id", "title", "section", "owner"):
            if not isinstance(meta[key], str) or not meta[key].strip():
                raise ValueError(f"Поле {key} в {path.name} должно быть непустой строкой")
        record_ids.add(meta["id"])
        records.append({**meta, "content": content, "version": hashlib.sha256(path.read_bytes()).hexdigest()})
    skills = []
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        meta, content = frontmatter(path)
        if not all(isinstance(meta.get(k), str) for k in ("name", "description")):
            raise ValueError(f"Некорректный скилл {path.parent.name}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", path.parent.name) or meta["name"] != path.parent.name:
            raise ValueError("Имя скилла должно совпадать с его папкой")
        skill_roles = meta.get("roles", list(roles))
        skill_context = meta.get("context", [])
        if not isinstance(skill_roles, list) or not set(skill_roles) <= roles.keys() or not isinstance(skill_context, list) or not all(isinstance(x, str) for x in skill_context):
            raise ValueError("Некорректные роли или разделы скилла")
        execution = meta.get("execution", "instruction")
        if execution not in {"draft", "instruction"}:
            raise ValueError("Скилл может иметь execution draft или instruction")
        skills.append({"name": meta["name"], "description": meta["description"], "content": content, "version": hashlib.sha256(path.read_bytes()).hexdigest(), "roles": skill_roles, "context": skill_context, "execution": execution})
    skill_names = {s["name"] for s in skills}
    for manifest in agents.values():
        if not isinstance(manifest.get("skills", []), list) or not set(manifest.get("skills", [])) <= skill_names:
            raise ValueError(f"Агент {manifest['name']} объявил отсутствующий скилл")
    goals_path = root / "config/goals.yaml"
    goals = yaml.safe_load(goals_path.read_text(encoding="utf-8")) if goals_path.exists() else {
        "purpose": "Связать поручения, знания, способы работы и проверяемые решения людей",
        "success_criteria": ["Результат основан на источниках", "Доступы соблюдены", "Решение привязано к версии"],
    }
    process = PROCESS_STEPS
    for path in sorted((root / "processes").glob("*.md")):
        if path.read_text(encoding="utf-8").startswith("---"):
            meta, _ = frontmatter(path)
            if isinstance(meta.get("steps"), list) and all(isinstance(s, str) for s in meta["steps"]):
                process = meta["steps"]
                break
    return {"roles": roles, "people": people, "agents": agents, "skills": skills, "goals": goals, "process": process}, records


def fixture_response(body: LLMBody) -> str:
    """Explicit deterministic fixtures for isolated tests; never a model fallback."""
    data = body.data
    if body.purpose == "select_skill":
        return json.dumps({"skill": data["skills"][0]["name"]})
    if body.purpose == "work_assistant":
        return json.dumps({"markdown": "Учебная проверка рабочего помощника.", "selected_skill": data["skill"], "source_refs": [x["id"] for x in data["sources"]], "suggested_agent": None, "suggested_input": {}, "missing_capability": ""}, ensure_ascii=False)
    if body.purpose == "daily_brief":
        return json.dumps({"markdown": "# Сводка руководителя\n\nКонтрольная подстановка для автоматического теста. Задач: " + str(len(data["workspace"]["tasks"])), "source_refs": [x["id"] for x in data["sources"]], "questions": []}, ensure_ascii=False)
    if body.purpose != "classify_message":
        raise HTTPException(422, "Для этой операции нет контрольного ответа")
    event, tasks = data["event"], data["tasks"]
    project = event["project_id"]
    existing = next((t for t in tasks if t["id"] == "TASK-E001"), None)
    out = {"markdown": "Предложение для проверки Анной. Контрольная подстановка теста.", "action": "create", "event_id": event["event_id"], "project_id": project, "task_id": None, "base_version": None, "title": "Получить недостающие тексты Орбиты", "owner": "mark", "status": "blocked", "due_date": None, "blocked_by": "Ждём тексты клиента", "question": "", "source_refs": [project, "R01", "R02"]}
    if event["event_id"] == "E002":
        out.update(action="update" if existing else "question", task_id=existing["id"] if existing else None, base_version=existing["version"] if existing else None, status="done", blocked_by="", question="" if existing else "Где задача получения текстов?")
    elif event["event_id"] == "E003":
        out.update(action="question", question="Анна, какой срок запуска можно обещать после проверки готовности?", owner=None, title="", blocked_by="")
    elif event["event_id"] == "E004" and existing:
        out.update(action="no_action", task_id=existing["id"], base_version=existing["version"], question="", blocked_by="")
    elif event["event_id"] == "E005":
        out.update(title="Собрать ещё 8 контрольных вопросов Контура", owner="lev", status="todo", blocked_by="")
    return json.dumps(out, ensure_ascii=False)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.validate()
    config: dict = {}

    @contextmanager
    def db():
        with psycopg.connect(settings.database_url, row_factory=dict_row, connect_timeout=5) as connection:
            yield connection

    def sync_sources() -> int:
        nonlocal config
        fresh_config, records = load_sources(settings.root)
        # Parsing and validating every file happens before touching the previous index.
        with db() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(701901)")
            connection.execute("DELETE FROM knowledge")
            for record in records:
                connection.execute("""INSERT INTO knowledge
                    (id,title,section,access,owner,updated,version,content,data,search_vector)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        setweight(to_tsvector('russian',%s),'A') || setweight(to_tsvector('russian',%s),'B'))""",
                    (record["id"], record["title"], record["section"], record["access"], record["owner"], record["updated"], record["version"], record["content"], Jsonb(record["data"]), record["title"], record["content"] + " " + json.dumps(record["data"], ensure_ascii=False)))
        config = fresh_config
        app.state.config = config
        return len(records)

    @asynccontextmanager
    async def lifespan(app):
        for attempt in range(30):
            try:
                with db() as connection:
                    connection.execute((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
                break
            except psycopg.OperationalError:
                if attempt == 29:
                    raise
                time.sleep(1)
        sync_sources()
        seed_workspace()
        # A local restart cannot resume an in-flight HTTP call. Preserve the failed run.
        with db() as connection:
            connection.execute("UPDATE runs SET status='error', error='Платформа перезапущена во время выполнения. Запустите заново с новым идентификатором запроса.', finished_at=now(), duration_ms=(extract(epoch FROM now()-created_at)*1000)::integer WHERE status='running'")
            connection.execute("UPDATE run_tokens SET active=false WHERE active=true")
            connection.execute("UPDATE cli_jobs SET status='error',error='Платформа перезапущена во время обращения к CLI',finished_at=now() WHERE status IN ('queued','claimed')")
        yield

    app = FastAPI(title="Маяк — девять слоёв AI-системы", lifespan=lifespan)
    app.state.settings, app.state.config = settings, config
    app.state.sync_sources, app.state.db = sync_sources, db

    @app.middleware("http")
    async def request_limits(request: Request, call_next):
        # Agents can reach this listener over their private Docker network.
        # The local-demo employee switch must NEVER be available to them:
        # otherwise X-Person: anna would bypass every run-token scope check.
        internal = request.url.path in {"/internal/context", "/internal/llm", "/internal/workspace", "/internal/skills"}
        health = request.method == "GET" and request.url.path == "/api/health"
        if not internal and not health:
            try:
                agent_addresses = await asyncio.to_thread(resolve_agent_addresses, settings.agent_urls)
            except (OSError, ValueError):
                return JSONResponse({"detail": "Не удалось проверить сетевые границы агентов. Проверьте доступность их сервисов."}, status_code=503)
            if request.client is None or normalized_address(request.client.host) in agent_addresses:
                return JSONResponse({"detail": "Сервисам агентов доступны только внутренние API по токену запуска."}, status_code=403)
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > 1048576:
                    return JSONResponse({"detail": "Запрос превышает 1 МБ"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Некорректная длина запроса"}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [".".join(str(x) for x in item["loc"]) for item in exc.errors()]
        return JSONResponse({"detail": "Проверьте обязательные поля и формат запроса: " + ", ".join(fields)}, status_code=422)

    @app.exception_handler(psycopg.Error)
    async def database_error(request, exc):
        LOG.error("Ошибка базы данных: %s", type(exc).__name__)
        return JSONResponse({"detail": "Не удалось выполнить операцию в базе данных. Повторите запрос после проверки сервиса."}, status_code=503)

    def person(request: Request):
        if settings.auth_mode == "token":
            header = request.headers.get("authorization", "")
            if not header.startswith("Bearer "):
                raise HTTPException(401, "Нужен личный токен в Authorization: Bearer")
            token = header[7:]
            person_id = next((pid for secret, pid in settings.person_tokens.items() if secrets.compare_digest(token.encode(), secret.encode())), None)
            if not person_id:
                raise HTTPException(401, "Нужен действующий личный токен")
        else:
            person_id = request.headers.get("x-person", "mark")
        result = next((p for p in config["people"] if p["id"] == person_id), None)
        if result is None:
            raise HTTPException(401, "Неизвестный сотрудник")
        return result

    def ceo(current):
        if current["role"] != "ceo" or not config["roles"][current["role"]].get("can_approve", False):
            raise HTTPException(403, "Это действие доступно согласующему руководителю")

    def permitted_run(connection, run_id, current, lock=False):
        try:
            run_id = uuid.UUID(str(run_id))
        except ValueError:
            raise HTTPException(404, "Запуск не найден") from None
        row = connection.execute("SELECT * FROM runs WHERE id=%s" + (" FOR UPDATE" if lock else ""), (run_id,)).fetchone()
        if row is None or (row["person_id"] != current["id"] and current["role"] != "ceo"):
            raise HTTPException(404, "Запуск не найден")
        return row

    def full_run(connection, row):
        run_id = row["id"]
        result = {key: value for key, value in row.items() if key not in {"manifest", "input_hash", "request_id"}}
        result["versions"] = connection.execute("SELECT version,output,author,created_at FROM revisions WHERE run_id=%s ORDER BY version", (run_id,)).fetchall()
        result["output"] = result["versions"][-1]["output"] if result["versions"] else None
        result["decisions"] = connection.execute("SELECT version,author,note,created_at FROM decisions WHERE run_id=%s ORDER BY id", (run_id,)).fetchall()
        result["context_events"] = connection.execute("SELECT section,query,records,hidden_count FROM context_events WHERE run_id=%s ORDER BY id", (run_id,)).fetchall()
        result["model_calls"] = connection.execute("SELECT purpose,mode,model,input_tokens,output_tokens,cost_usd,skill_refs,status,usage FROM model_calls WHERE run_id=%s ORDER BY id", (run_id,)).fetchall()
        result["learnings"] = connection.execute("SELECT id,run_id,version,text,author,created_at FROM learnings WHERE run_id=%s ORDER BY id", (run_id,)).fetchall()
        result["review_feedback"] = row["manifest"].get("_retry_reason", "")
        result["source_warnings"] = source_warnings(connection, run_id)
        result["task_state_stale"] = task_state_stale(connection,row)
        result["task_application"] = connection.execute("SELECT task_id,version,run_version FROM task_history WHERE run_id=%s ORDER BY version DESC LIMIT 1", (run_id,)).fetchone()
        return jsonable_encoder(result)

    def source_warnings(connection, run_id):
        changed = connection.execute("""SELECT DISTINCT reference->>'id' AS id
            FROM context_events event CROSS JOIN LATERAL jsonb_array_elements(event.records) reference
            LEFT JOIN knowledge current ON current.id=reference->>'id'
            WHERE event.run_id=%s AND (current.id IS NULL OR current.version<>reference->>'version')
            ORDER BY id""", (run_id,)).fetchall()
        return [{"id": item["id"], "reason": "Источник изменён или удалён после запуска. Нужен новый запуск."} for item in changed]

    def query_context(connection, role: str, section: str | None, query: str = "", limit: int = 50):
        if len(query) > 300:
            raise HTTPException(422, "Поисковый запрос длиннее 300 символов")
        if section is not None and not re.fullmatch(r"[a-z0-9_-]{1,80}", section):
            raise HTTPException(422, "Некорректное имя раздела")
        sections = config["roles"][role]["sections"]
        # MATERIALIZED makes role/section filtering a boundary before ranking/search.
        where_section = "WHERE section=%s" if section else ""
        scoped_params = (section,) if section else ()
        total = connection.execute("SELECT count(*) AS n FROM knowledge " + where_section, scoped_params).fetchone()["n"]
        permitted_sql = "SELECT * FROM knowledge WHERE %s=ANY(access) AND section=ANY(%s)"
        permitted_params = (role, sections)
        if section:
            permitted_sql += " AND section=%s"
            permitted_params += (section,)
        visible = connection.execute("SELECT count(*) AS n FROM (" + permitted_sql + ") visible", permitted_params).fetchone()["n"]
        select = "SELECT id,title,section,owner,updated,version,content,data FROM permitted"
        if query.strip():
            sql = "WITH permitted AS MATERIALIZED (" + permitted_sql + ") " + select + " WHERE search_vector @@ plainto_tsquery('russian', %s) ORDER BY ts_rank(search_vector,plainto_tsquery('russian',%s)) DESC,id LIMIT %s"
            params = permitted_params + (query, query, limit)
        else:
            sql = "WITH permitted AS MATERIALIZED (" + permitted_sql + ") " + select + " ORDER BY section,id LIMIT %s"
            params = permitted_params + (limit,)
        records = connection.execute(sql, params).fetchall()
        return {"records": jsonable_encoder(records), "hidden_count": total - visible}

    def run_token(request: Request):
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or len(header) > 200:
            raise HTTPException(401, "Нужен токен запуска")
        token_hash = hashlib.sha256(header[7:].encode()).hexdigest()
        with db() as connection:
            row = connection.execute("""SELECT runs.* FROM run_tokens JOIN runs ON runs.id=run_tokens.run_id
                WHERE token_hash=%s AND active AND expires_at>now() AND runs.status='running'""", (token_hash,)).fetchone()
        if row is None:
            raise HTTPException(401, "Токен запуска недействителен или истёк")
        return row

    def seed_workspace():
        """Seed immutable fictional inputs once; a restart never resets task state."""
        events = yaml.safe_load((settings.root / 'config/inbox.yaml').read_text()) or []
        initial = yaml.safe_load((settings.root / 'config/tasks.yaml').read_text()) or []
        with db() as connection:
            for event in events:
                connection.execute("INSERT INTO inbox(event_id,project_id,text,author,received_at,input_hash) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING", (event['event_id'],event['project_id'],event['text'],event['author'],event['received_at'],canonical_hash(event)))
            for task in initial:
                row = connection.execute("INSERT INTO tasks(id,project_id,title,owner,status,due_date,blocked_by,source_refs) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING *", (task['id'],task['project_id'],task['title'],task['owner'],task['status'],task['due_date'],task['blocked_by'],Jsonb(task['source_refs']))).fetchone()
                if row:
                    connection.execute("INSERT INTO task_history(task_id,version,snapshot,author) VALUES(%s,1,%s,'starter')", (row['id'],Jsonb(jsonable_encoder(row))))

    def workspace_snapshot(connection, role, project_id='all', event_id=None, sections=None):
        project_context_enabled = sections is None or 'projects' in sections
        project_context = query_context(connection, role, 'projects') if project_context_enabled else {'records':[], 'hidden_count':0}
        projects = project_context['records']
        allowed = {p['data']['project_id'] for p in projects if 'project_id' in p['data']}
        event = None
        if event_id:
            event = connection.execute("SELECT * FROM inbox WHERE event_id=%s AND project_id=ANY(%s)", (event_id,list(allowed))).fetchone()
            if event:
                project_id = event['project_id']
        if project_id != 'all':
            allowed &= {project_id}
            projects = [p for p in projects if p['data']['project_id'] in allowed]
        tasks = connection.execute("SELECT * FROM tasks WHERE project_id=ANY(%s) ORDER BY id", (list(allowed),)).fetchall()
        # Shared task state is visible to project roles. Private run narratives are not.
        events = connection.execute("SELECT i.event_id,i.project_id,i.text,i.author,i.received_at,coalesce(r.status,'new') AS status,i.current_run_id AS run_id FROM inbox i LEFT JOIN runs r ON r.id=i.current_run_id WHERE i.project_id=ANY(%s) ORDER BY i.event_id", (list(allowed),)).fetchall()
        decisions = connection.execute("SELECT h.task_id,h.version,h.author,h.created_at,h.snapshot FROM task_history h JOIN tasks t ON t.id=h.task_id WHERE t.project_id=ANY(%s) ORDER BY h.created_at DESC LIMIT 50", (list(allowed),)).fetchall()
        return jsonable_encoder({'_project_context':{'enabled':project_context_enabled,'hidden_count':project_context['hidden_count']},'event':event,'project_name':next((p['data']['name'] for p in projects if event and p['data']['project_id']==event['project_id']),''),'projects':projects,'tasks':tasks,'people':config['people'],'inbox':events,'decisions':decisions})

    def validate_output(connection, run_id, manifest, input_data, output):
        refs = output.get('source_refs', [])
        rows = connection.execute("SELECT DISTINCT reference->>'id' AS id FROM context_events e CROSS JOIN LATERAL jsonb_array_elements(e.records) reference WHERE run_id=%s", (run_id,)).fetchall()
        if not set(refs) <= {r['id'] for r in rows}:
            raise HTTPException(422, 'Результат ссылается на источник, который не был получен в этом запуске')
        if manifest['name'] != 'task-intake':
            return
        snapshot = manifest['_workspace']; event = snapshot['event']
        if output['event_id'] != event['event_id'] or output['project_id'] != event['project_id']:
            raise HTTPException(422, 'Агент изменил сообщение или проект')
        if output['owner'] is not None and output['owner'] not in {p['id'] for p in snapshot['people']}:
            raise HTTPException(422, 'Неизвестный ответственный')
        if output['due_date']:
            try: date.fromisoformat(output['due_date'])
            except ValueError: raise HTTPException(422, 'Некорректная дата задачи') from None
        action = output['action']
        if action in {'create','update'}:
            if not output['title'].strip() or not output['owner']:
                raise HTTPException(422, 'Для изменения нужны задача и ответственный')
            if action == 'create' and (output['task_id'] is not None or output['base_version'] is not None):
                raise HTTPException(422, 'Новая задача не имеет предыдущей версии')
            if action == 'update':
                previous = next((t for t in snapshot['tasks'] if t['id']==output['task_id'] and t['project_id']==event['project_id']),None)
                if previous is None or previous['version'] != output['base_version']:
                    raise HTTPException(422, 'Изменение не основано на полученной версии задачи')
        if action == 'question' and not output['question'].strip():
            raise HTTPException(422, 'Не сформулирован вопрос человеку')

    def task_state_stale(connection, run):
        if run['agent']!='task-intake' or run['status']!='needs_review' or not run['current_version']:return False
        output=connection.execute('SELECT output FROM revisions WHERE run_id=%s AND version=%s',(run['id'],run['current_version'])).fetchone()['output']
        if output['action']=='create':
            now=connection.execute('SELECT id,version FROM tasks WHERE project_id=%s ORDER BY id',(output['project_id'],)).fetchall()
            before=sorted((t['id'],t['version']) for t in run['manifest']['_workspace']['tasks'])
            return [(t['id'],t['version']) for t in now]!=before
        if output['action']=='update':
            task=connection.execute('SELECT version FROM tasks WHERE id=%s',(output['task_id'],)).fetchone()
            return task is None or task['version']!=output['base_version']
        return False

    def apply_task_change(connection, run, version, current):
        if run['agent'] != 'task-intake':
            return
        output = connection.execute('SELECT output FROM revisions WHERE run_id=%s AND version=%s',(run['id'],version)).fetchone()['output']
        validate_output(connection,run['id'],run['manifest'],run['input'],output)
        connection.execute('SELECT pg_advisory_xact_lock(701904)')
        event = connection.execute('SELECT * FROM inbox WHERE event_id=%s FOR UPDATE',(output['event_id'],)).fetchone()
        if not event or event['current_run_id'] != run['id']:
            raise HTTPException(409,'Сообщение уже связано с другим запуском')
        if output['action'] not in {'create','update'}:
            return
        task_id = 'TASK-' + event['event_id'] if output['action']=='create' else output['task_id']
        previous = connection.execute('SELECT * FROM tasks WHERE id=%s FOR UPDATE',(task_id,)).fetchone()
        if output['action']=='create' and previous:
            raise HTTPException(409,'Задача этого сообщения уже существует; повтор не применён')
        if output['action']=='create':
            now_tasks=connection.execute('SELECT id,version FROM tasks WHERE project_id=%s ORDER BY id FOR UPDATE',(output['project_id'],)).fetchall()
            before_tasks=sorted((t['id'],t['version']) for t in run['manifest']['_workspace']['tasks'])
            if [(t['id'],t['version']) for t in now_tasks]!=before_tasks:
                raise HTTPException(409,'Доска проекта изменилась после подготовки новой задачи. Нужен новый разбор, чтобы не создать повтор.')
            normalized=' '.join(output['title'].casefold().split())
            if any(' '.join(t['title'].casefold().split())==normalized for t in run['manifest']['_workspace']['tasks']):
                raise HTTPException(409,'На доске уже есть задача с таким результатом. Проверьте возможный повтор.')
        if output['action']=='update' and (previous is None or previous['version'] != output['base_version']):
            raise HTTPException(409,'Задача изменилась после подготовки результата. Нужен новый запуск по новому сообщению.')
        new_version = previous['version']+1 if previous else 1
        values=(output['title'],output['owner'],output['status'],output['due_date'],output['blocked_by'],Jsonb(output['source_refs']))
        if previous:
            task = connection.execute('UPDATE tasks SET title=%s,owner=%s,status=%s,due_date=%s,blocked_by=%s,source_refs=%s,version=%s,updated_at=now() WHERE id=%s RETURNING *',values+(new_version,task_id)).fetchone()
        else:
            task = connection.execute('INSERT INTO tasks(title,owner,status,due_date,blocked_by,source_refs,id,project_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *',values+(task_id,output['project_id'])).fetchone()
        connection.execute('INSERT INTO task_history(task_id,version,snapshot,author,run_id,run_version) VALUES(%s,%s,%s,%s,%s,%s)',(task_id,new_version,Jsonb(jsonable_encoder(task)),current['id'],run['id'],version))

    def worker_state():
        with db() as connection:
            worker = connection.execute("SELECT provider,last_seen,last_seen>now()-interval '45 seconds' AS connected FROM cli_workers ORDER BY last_seen DESC LIMIT 1").fetchone()
        return jsonable_encoder(worker or {'provider':settings.cli_provider,'last_seen':None,'connected':False})

    def worker_auth(request: Request):
        expected = settings.cli_worker_token
        actual = request.headers.get('authorization','')
        if len(expected) < 32 or not actual.startswith('Bearer ') or not secrets.compare_digest(actual[7:].encode(),expected.encode()):
            raise HTTPException(401,'Нужен служебный токен локального исполнителя CLI')

    @app.post('/api/cli/heartbeat', dependencies=[Depends(worker_auth)])
    def heartbeat(body: WorkerBody):
        if body.provider != settings.cli_provider:
            raise HTTPException(409,'Выбран другой CLI; проверьте CLI_PROVIDER')
        with db() as connection:
            connection.execute('INSERT INTO cli_workers(worker_id,provider) VALUES(%s,%s) ON CONFLICT(worker_id) DO UPDATE SET provider=excluded.provider,last_seen=now()',(body.worker_id,body.provider))
        return {'status':'ok'}

    @app.post('/api/cli/claim', dependencies=[Depends(worker_auth)])
    def claim_job(body: WorkerBody):
        heartbeat(body)
        with db() as connection:
            row = connection.execute("SELECT j.* FROM cli_jobs j JOIN runs r ON r.id=j.run_id WHERE j.status='queued' AND r.status='running' ORDER BY j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1").fetchone()
            if not row:
                return {'job':None}
            token = secrets.token_urlsafe(32)
            connection.execute("UPDATE cli_jobs SET status='claimed',worker_id=%s,claim_hash=%s,claimed_at=now() WHERE id=%s",(body.worker_id,hashlib.sha256(token.encode()).hexdigest(),row['id']))
            return {'job':{'id':str(row['id']),'claim_token':token,'request':row['request']}}

    @app.post('/api/cli/jobs/{job_id}/complete', dependencies=[Depends(worker_auth)])
    def complete_job(job_id: uuid.UUID, body: WorkerCompleteBody):
        with db() as connection:
            row = connection.execute('SELECT * FROM cli_jobs WHERE id=%s FOR UPDATE',(job_id,)).fetchone()
            if not row or not row['claim_hash'] or not secrets.compare_digest(row['claim_hash'],hashlib.sha256(body.claim_token.encode()).hexdigest()):
                raise HTTPException(404,'Задание не найдено')
            if row['status'] == 'completed' and body.status == 'completed' and body.result:
                repeated=body.result.model_dump();repeated['cost_usd']=None;repeated['mode']='cli'
                if row['result']==repeated:return {'status':'ok'}
            if row['status'] == 'error' and body.status == 'error' and row['finished_at']:
                return {'status':'ok'}
            if row['status'] != 'claimed':
                raise HTTPException(409,'Задание уже завершено или отменено; повтор не принят')
            if (datetime.now(timezone.utc)-row['claimed_at']).total_seconds()>210:
                raise HTTPException(409,'Истёк срок задания; поздний ответ не принят')
            if body.status == 'completed':
                if body.result is None or not body.result.text.strip() or body.result.provider != settings.cli_provider:
                    raise HTTPException(422,'Некорректный результат CLI')
                result=body.result.model_dump();result['cost_usd']=None;result['mode']='cli'
                encoded=json.dumps(result,ensure_ascii=False)
                if settings.cli_worker_token in encoded:
                    raise HTTPException(422,'Служебные данные не принимаются в результат')
                connection.execute("UPDATE cli_jobs SET status='completed',result=%s,finished_at=now(),request='{}' WHERE id=%s",(Jsonb(result),job_id))
            else:
                connection.execute("UPDATE cli_jobs SET status='error',error='CLI не завершил запрос. Проверьте авторизацию и доступность выбранного CLI; повторного вызова не было.',finished_at=now(),request='{}' WHERE id=%s",(job_id,))
        return {'status':'ok'}

    @app.get('/api/workspace')
    def workspace(current=Depends(person)):
        with db() as connection:
            snapshot=workspace_snapshot(connection,current['role'])
            for task in snapshot['tasks']:
                task['history']=jsonable_encoder(connection.execute('SELECT version,author,created_at,run_id,run_version,snapshot FROM task_history WHERE task_id=%s ORDER BY version',(task['id'],)).fetchall())
            # IDs of somebody else's private run are not exposed in the shared inbox.
            for event in snapshot['inbox']:
                if event['run_id'] and current['role']!='ceo':
                    owner=connection.execute('SELECT person_id FROM runs WHERE id=%s',(event['run_id'],)).fetchone()
                    if owner['person_id']!=current['id']:event['run_id']=None
            counts={'pending_approvals':sum(e['status']=='needs_review' for e in snapshot['inbox']),'blocked_tasks':sum(t['status']=='blocked' for t in snapshot['tasks']),'unprocessed_events':sum(e['status']=='new' for e in snapshot['inbox']),'open_questions':0}
            if snapshot['projects']:
                counts['open_questions']=connection.execute("SELECT count(*) AS n FROM inbox i JOIN runs r ON r.id=i.current_run_id JOIN revisions v ON v.run_id=r.id AND v.version=r.current_version WHERE i.project_id=ANY(%s) AND r.status='needs_review' AND v.output->>'action'='question'",([p['data']['project_id'] for p in snapshot['projects']],)).fetchone()['n']
            return {'access':bool(snapshot['projects']),'inbox':snapshot['inbox'],'tasks':snapshot['tasks'],'projects':snapshot['projects'],'attention':counts}

    @app.post('/api/inbox')
    def add_event(body: InboxBody, current=Depends(person)):
        if current['role'] not in {'ceo','sales'}:
            raise HTTPException(403,'Добавлять сообщения может координатор или руководитель')
        with db() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(701903)")
            allowed={p['data'].get('project_id') for p in query_context(connection,current['role'],'projects')['records']}
            if body.project_id not in allowed:raise HTTPException(403,'Проект недоступен')
            values=body.model_dump(mode='json');fingerprint=canonical_hash(values)
            old=connection.execute('SELECT input_hash FROM inbox WHERE event_id=%s',(body.event_id,)).fetchone()
            if old and old['input_hash']!=fingerprint:raise HTTPException(409,'event_id уже обозначает другое сообщение')
            connection.execute('INSERT INTO inbox(event_id,project_id,text,author,received_at,input_hash) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING',(body.event_id,body.project_id,body.text,body.author,body.received_at,fingerprint))
        return {'event_id':body.event_id,'created':not bool(old)}

    @app.get('/internal/workspace')
    def internal_workspace(run=Depends(run_token)):
        if not run['manifest'].get('workspace',False):
            raise HTTPException(403,'Агент не объявил чтение рабочего состояния')
        snapshot = run['manifest'].get('_workspace',{})
        context = snapshot.get('_project_context',{})
        if context.get('enabled'):
            # Record exactly the source versions in the issued run snapshot.
            # Re-reading current knowledge here would conceal a concurrent sync.
            references = [{'id':p['id'],'title':p['title'],'version':p['version']} for p in snapshot.get('projects',[])]
            with db() as connection:
                connection.execute('INSERT INTO context_events(run_id,section,query,records,hidden_count) VALUES(%s,%s,%s,%s,%s)',(run['id'],'projects','Снимок рабочего состояния',Jsonb(references),context.get('hidden_count',0)))
        return {key:value for key,value in snapshot.items() if not key.startswith('_')}

    @app.get('/internal/skills')
    def internal_skills(run=Depends(run_token)):
        return {'skills':run['manifest'].get('_available_skills',[])}

    @app.get("/api/health")
    def health():
        try:
            with db() as connection:
                connection.execute("SELECT 1")
            return {"status": "ok", "database": "ok", "llm_mode": settings.llm_mode, "cli_worker": worker_state(), "cli_provider": settings.cli_provider}
        except psycopg.Error:
            return JSONResponse({"status": "error", "database": "unavailable", "llm_mode": settings.llm_mode, "cli_worker": worker_state(), "cli_provider": settings.cli_provider}, status_code=503)

    @app.get("/api/bootstrap")
    def bootstrap(current=Depends(person)):
        with db() as connection:
            all_sections = sorted(set(SECTION_TITLES) | {r["section"] for r in connection.execute("SELECT DISTINCT section FROM knowledge")})
            sections = []
            for section in all_sections:
                aggregate = connection.execute("""SELECT count(*) AS total,
                    count(*) FILTER (WHERE %s=ANY(access) AND section=ANY(%s)) AS visible,
                    array_agg(DISTINCT owner) FILTER (WHERE %s=ANY(access) AND section=ANY(%s)) AS owners,
                    max(updated) FILTER (WHERE %s=ANY(access) AND section=ANY(%s)) AS updated
                    FROM knowledge WHERE section=%s""", (current["role"], config["roles"][current["role"]]["sections"], current["role"], config["roles"][current["role"]]["sections"], current["role"], config["roles"][current["role"]]["sections"], section)).fetchone()
                sections.append({"name": section, "title": SECTION_TITLES.get(section, section), "count": aggregate["visible"], "hidden_count": aggregate["total"] - aggregate["visible"], "owners": sorted(aggregate["owners"] or []), "updated": str(aggregate["updated"]) if aggregate["updated"] else None})
            filter_sql = "" if current["role"] == "ceo" else " WHERE person_id=%s"
            metrics = {row["agent"]: row for row in connection.execute("""SELECT agent,count(*) AS runs,
                coalesce(sum(input_tokens),0) AS input_tokens,coalesce(sum(output_tokens),0) AS output_tokens,
                CASE WHEN count(*) FILTER(WHERE cost_usd IS NULL)>0 THEN NULL ELSE sum(cost_usd) END AS cost_usd
                FROM runs""" + filter_sql + " GROUP BY agent", () if current["role"] == "ceo" else (current["id"],)).fetchall()}
        return {"demo": settings.auth_mode == "demo", "llm_mode": settings.llm_mode, "cli_worker": worker_state(),
            "person": current, "people": config["people"] if settings.auth_mode == "demo" else [current],
            "roles": config["roles"], "agents": [{**manifest, "allowed": current["role"] in manifest["roles"], "metrics": metrics.get(manifest["name"], {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0})} for manifest in config["agents"].values()],
            "sections": sections, "skills": [s for s in config["skills"] if current["role"] in s["roles"]], "process": config["process"],
            "policies": {"approval": "Руководитель утверждает точную версию. Правка требует нового решения.",
                "sending": "Внешняя отправка не подключена.", "network": "Агенты обращаются только к платформе в своей внутренней сети.",
                "auth": "Переключатель сотрудника демонстрирует роли и не проверяет личность." if settings.auth_mode == "demo" else "Личность определяется личным токеном."},
            "goals": config["goals"], "layers": [{"number": i + 1, "title": title} for i, title in enumerate(LAYER_TITLES)]}

    @app.get("/api/knowledge")
    def knowledge(section: str | None = None, q: str = "", current=Depends(person)):
        with db() as connection:
            return query_context(connection, current["role"], section, q)

    @app.post("/api/sync")
    def sync(current=Depends(person)):
        ceo(current)
        try:
            count = sync_sources()
        except (ValueError, OSError, yaml.YAMLError, SchemaError) as exc:
            # Local authors can inspect the file; no raw YAML contents are echoed.
            raise HTTPException(422, "Синхронизация отменена: проверьте файлы, метаданные и схемы. Предыдущий индекс сохранён.") from None
        return {"count": count, "message": "Знания и настройки синхронизированы"}

    @app.get("/api/runs")
    def runs(current=Depends(person)):
        with db() as connection:
            sql = "SELECT id,agent,person_id,status,created_at,current_version,cost_usd,llm_mode FROM runs"
            params = ()
            if current["role"] != "ceo":
                sql += " WHERE person_id=%s"
                params = (current["id"],)
            return {"runs": jsonable_encoder(connection.execute(sql + " ORDER BY created_at DESC LIMIT 100", params).fetchall())}

    @app.get("/api/runs/{run_id}")
    def read_run(run_id: str, current=Depends(person)):
        with db() as connection:
            return full_run(connection, permitted_run(connection, run_id, current))

    @app.post("/api/runs")
    def start_run(body: RunBody, current=Depends(person)):
        feedback=body.retry_reason.strip()
        if (body.refresh or feedback) and body.agent != "task-intake":
            raise HTTPException(422,"Повторный разбор сообщения доступен только процессу task-intake")
        if feedback and (not body.refresh or len(feedback)<5):
            raise HTTPException(422,"Для повторного разбора укажите refresh:true и замечание не короче пяти символов")
        manifest = config["agents"].get(body.agent)
        if manifest is None:
            raise HTTPException(404, "Агент не найден")
        if current["role"] not in manifest["roles"]:
            raise HTTPException(403, "Ваша роль не может запускать этого агента")
        schema_check(manifest["input"], body.input, "Вход агента")
        if any(current["role"] not in s["roles"] for s in config["skills"] if s["name"] in manifest.get("skills", [])):
            raise HTTPException(403,"Роль не может выполнять один из способов работы этого агента")
        runtime_manifest = {**manifest, "_skills": [s for s in config["skills"] if s["name"] in manifest.get("skills", [])]}
        if body.agent == "work-assistant":
            runtime_manifest["_available_skills"] = [s for s in config["skills"] if s["execution"] == "draft" and current["role"] in s["roles"]]
            runtime_manifest["context"] = sorted(set(manifest["context"]) | {section for skill in runtime_manifest["_available_skills"] for section in skill["context"]})
        fingerprint = canonical_hash({"agent": body.agent, "input": body.input})
        run_id, token = uuid.uuid4(), secrets.token_urlsafe(48)
        with db() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(701902)")
            repeated=connection.execute("SELECT * FROM runs WHERE person_id=%s AND request_id=%s", (current["id"],body.request_id)).fetchone()
            if repeated:
                if repeated["input_hash"] != fingerprint:
                    raise HTTPException(409,"Этот request_id уже использован с другим входом")
                return full_run(connection,repeated)
            snapshot = workspace_snapshot(connection, current["role"], body.input.get("project_id", "all"), body.input.get("event_id"), runtime_manifest["context"]) if runtime_manifest.get("workspace",False) else {}
            if feedback:
                runtime_manifest["_retry_reason"] = feedback
                snapshot["review_feedback"] = feedback
            runtime_manifest["_workspace"] = snapshot
            if body.agent == "task-intake":
                event = snapshot["event"]
                if event is None:
                    raise HTTPException(404, "Сообщение не найдено в доступном проекте")
                if event.get("current_run_id"):
                    previous = permitted_run(connection, event["current_run_id"], current, lock=True)
                    if previous["status"] != "error":
                        if body.refresh:
                            if previous["status"] != "needs_review" or not (feedback or source_warnings(connection,previous["id"]) or task_state_stale(connection,previous)):
                                raise HTTPException(409,"Повторить можно только несогласованный разбор: укажите замечание проверяющего или сначала обновите изменившиеся источники и задачи")
                        else:
                            return full_run(connection, previous)
            inserted = connection.execute("""INSERT INTO runs
                (id,agent,person_id,role,status,input,input_hash,request_id,manifest,llm_mode,cost_usd)
                VALUES (%s,%s,%s,%s,'running',%s,%s,%s,%s,%s,%s)
                ON CONFLICT (person_id,request_id) DO NOTHING RETURNING id""",
                (run_id, body.agent, current["id"], current["role"], Jsonb(body.input), fingerprint, body.request_id, Jsonb(runtime_manifest), settings.llm_mode, 0 if settings.llm_mode == "fixture" else None)).fetchone()
            if not inserted:
                previous = connection.execute("SELECT * FROM runs WHERE person_id=%s AND request_id=%s", (current["id"], body.request_id)).fetchone()
                if previous["input_hash"] != fingerprint:
                    raise HTTPException(409, "Этот request_id уже использован с другим входом. Создайте новый идентификатор.")
                return full_run(connection, previous)
            if body.agent == "task-intake":
                connection.execute("UPDATE inbox SET current_run_id=%s WHERE event_id=%s", (run_id, body.input["event_id"]))
            connection.execute("INSERT INTO run_tokens(token_hash,run_id,expires_at) VALUES (%s,%s,now()+interval '15 minutes')", (hashlib.sha256(token.encode()).hexdigest(), run_id))
        started = time.monotonic()
        output, steps, error = None, [], None
        try:
            endpoint = settings.agent_urls.get(body.agent)
            if not endpoint:
                raise HTTPException(503, "Для агента не настроен адрес сервиса в AGENT_URLS")
            with httpx.Client(timeout=settings.agent_timeout, trust_env=False, follow_redirects=False) as client:
                response = client.post(endpoint.rstrip("/") + "/run", json={"input": body.input, "run_token": token, "platform_url": settings.platform_url})
            if response.status_code != 200:
                safe_messages = [
                    "Модель вернула предложение не по схеме. Изменения не применены.",
                    "Модель сослалась на источник, который не получала.",
                    "Модель выбрала неизвестного ответственного.",
                    "Обновление не ссылается на точную существующую задачу.",
                    "Не хватает разрешённых сведений проекта или правил.",
                    "Скилл не найден или недоступен роли.",
                    "Результат скилла не прошёл проверку формата, источников или маршрута.",
                    "Сводка не соответствует формату или содержит неизвестные источники.",
                    "Локальный исполнитель CLI не подключён. Выполните python3 scripts/start.py и проверьте вход в выбранный CLI.",
                    "CLI не завершил запрос. Проверьте авторизацию и доступность выбранного CLI; повторного вызова не было.",
                    "CLI не ответил вовремя. Автоматического повторного вызова не было; проверьте локальный исполнитель.",
                    "CLI вернул ответ не по ожидаемой схеме. Изменения не применены.",
                ]
                safe_errors = {message: message for message in safe_messages}
                try:
                    detail = response.json().get("detail")
                    if isinstance(detail, dict):
                        detail = detail.get("code")
                    if isinstance(detail, str) and detail in safe_errors:
                        raise HTTPException(502, safe_errors[detail])
                except (ValueError, AttributeError):
                    pass
                raise HTTPException(502, "Агент не смог завершить работу. Проверьте входные данные и доступность модели; повторите запуск после исправления.")
            if len(response.content) > 1048576:
                raise HTTPException(502, "Агент вернул слишком большой ответ")
            result = response.json()
            if not isinstance(result, dict) or set(result) != {"output", "steps"}:
                raise HTTPException(502, "Ответ агента должен содержать только output и steps")
            output, steps = result["output"], result["steps"]
            schema_check(manifest["output"], output, "Выход агента")
            with db() as connection:
                validate_output(connection, run_id, runtime_manifest, body.input, output)
            schema_check({"type": "array", "maxItems": 50, "items": {"type": "object", "required": ["title", "detail"], "properties": {"title": {"type": "string", "maxLength": 200}, "detail": {"type": "string", "maxLength": 5000}}, "additionalProperties": False}}, steps, "Шаги агента")
            # Guard against accidental token echoes in code supplied by learners.
            if token in json.dumps(result, ensure_ascii=False) or (settings.cli_worker_token and settings.cli_worker_token in json.dumps(result, ensure_ascii=False)):
                raise HTTPException(502, "Ответ агента содержит служебные данные и не сохранён")
        except HTTPException as exc:
            error = str(exc.detail)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            error = "Не удалось получить корректный ответ агента. Проверьте его сервис и формат output/steps."
        except Exception as exc:
            LOG.error("Непредвиденная ошибка вызова агента: %s", type(exc).__name__)
            error = "Запуск прерван внутренней ошибкой. Проверьте сервис агента перед повторным запуском."
        finally:
            with db() as connection:
                connection.execute("UPDATE run_tokens SET active=false WHERE run_id=%s", (run_id,))
                if error:
                    connection.execute("UPDATE runs SET status='error',error=%s,finished_at=now(),duration_ms=%s WHERE id=%s", (error, int((time.monotonic()-started)*1000), run_id))
                else:
                    connection.execute("INSERT INTO revisions(run_id,version,output,author) VALUES (%s,1,%s,%s)", (run_id, Jsonb(output), "agent:" + body.agent))
                    connection.execute("UPDATE runs SET status='needs_review',steps=%s,current_version=1,finished_at=now(),duration_ms=%s WHERE id=%s", (Jsonb(steps), int((time.monotonic()-started)*1000), run_id))
        with db() as connection:
            return full_run(connection, connection.execute("SELECT * FROM runs WHERE id=%s", (run_id,)).fetchone())

    @app.post("/api/runs/{run_id}/revisions")
    def revise(run_id: str, body: RevisionBody, current=Depends(person)):
        with db() as connection:
            row = permitted_run(connection, run_id, current, lock=True)
            if row["agent"] == "task-intake" and row["status"] == "approved":
                raise HTTPException(409, "Решение уже применено. Для продолжения добавьте новое сообщение; историю не переписываем.")
            if row["status"] not in {"needs_review", "approved"}:
                raise HTTPException(409, "Редактировать можно только готовый результат")
            if row["current_version"] != body.base_version:
                raise HTTPException(409, "Результат уже изменился. Обновите страницу перед правкой.")
            old = connection.execute("SELECT output FROM revisions WHERE run_id=%s AND version=%s", (row["id"], body.base_version)).fetchone()["output"]
            output = {**old, "markdown": body.markdown}
            schema_check(row["manifest"]["output"], output, "Исправленный выход")
            if old == output:
                return full_run(connection, row)
            version = body.base_version + 1
            connection.execute("INSERT INTO revisions(run_id,version,output,author) VALUES (%s,%s,%s,%s)", (row["id"], version, Jsonb(output), current["id"]))
            row = connection.execute("UPDATE runs SET current_version=%s,status='needs_review' WHERE id=%s RETURNING *", (version, row["id"])).fetchone()
            return full_run(connection, row)

    @app.post("/api/runs/{run_id}/approve")
    def approve(run_id: str, body: ApprovalBody, current=Depends(person)):
        ceo(current)
        with db() as connection:
            connection.execute("SELECT pg_advisory_xact_lock_shared(701901)")
            row = permitted_run(connection, run_id, current, lock=True)
            if row["status"] not in {"needs_review", "approved"} or row["current_version"] != body.version:
                raise HTTPException(409, "Можно согласовать только последнюю готовую версию")
            if source_warnings(connection, row["id"]):
                raise HTTPException(409, "Источники изменились после подготовки результата. Выполните новый запуск перед согласованием.")
            prior = connection.execute("SELECT * FROM decisions WHERE run_id=%s AND version=%s", (row["id"], body.version)).fetchone()
            if prior and prior["note"] != body.note:
                raise HTTPException(409, "Решение по этой версии уже сохранено. История решений неизменяема.")
            if not prior:
                apply_task_change(connection, row, body.version, current)
                connection.execute("INSERT INTO decisions(run_id,version,author,note) VALUES (%s,%s,%s,%s)", (row["id"], body.version, current["id"], body.note))
            row = connection.execute("UPDATE runs SET status='approved' WHERE id=%s RETURNING *", (row["id"],)).fetchone()
            return full_run(connection, row)

    @app.get("/api/memory")
    def memory(current=Depends(person)):
        with db() as connection:
            condition = "" if current["role"] == "ceo" else " WHERE r.person_id=%s"
            params = () if current["role"] == "ceo" else (current["id"],)
            decisions = connection.execute("SELECT d.* FROM decisions d JOIN runs r ON r.id=d.run_id" + condition + " ORDER BY d.created_at DESC LIMIT 100", params).fetchall()
            learnings = connection.execute("SELECT l.* FROM learnings l JOIN runs r ON r.id=l.run_id" + condition + " ORDER BY l.created_at DESC LIMIT 100", params).fetchall()
            return jsonable_encoder({"decisions": decisions, "learnings": learnings})

    @app.post("/api/runs/{run_id}/learnings")
    def add_learning(run_id: str, body: LearningBody, current=Depends(person)):
        ceo(current)
        with db() as connection:
            row = permitted_run(connection, run_id, current, lock=True)
            if row["status"] != "approved":
                raise HTTPException(409, "Урок можно сохранить только после согласования текущей версии")
            result = connection.execute("INSERT INTO learnings(run_id,version,text,author) VALUES (%s,%s,%s,%s) RETURNING *", (row["id"], row["current_version"], body.text, current["id"])).fetchone()
            return jsonable_encoder(result)

    @app.get("/internal/context")
    def internal_context(section: str, q: str = "", limit: int = 50, run=Depends(run_token)):
        if section not in run["manifest"]["context"]:
            raise HTTPException(403, "Агент не объявил доступ к этому разделу")
        if not 1 <= limit <= 50:
            raise HTTPException(422, "limit должен быть от 1 до 50")
        with db() as connection:
            result = query_context(connection, run["role"], section, q, limit)
            references = [{"id": r["id"], "title": r["title"], "version": r["version"]} for r in result["records"]]
            connection.execute("INSERT INTO context_events(run_id,section,query,records,hidden_count) VALUES (%s,%s,%s,%s,%s)", (run["id"], section, q, Jsonb(references), result["hidden_count"]))
            return result

    @app.post('/internal/llm')
    def llm(body: LLMBody, run=Depends(run_token)):
        data_json=json.dumps(body.data,ensure_ascii=False,allow_nan=False)
        if len(data_json)>200000:raise HTTPException(413,'Слишком большой контекст модели')
        if body.response_schema is not None:
            try:Draft202012Validator.check_schema(body.response_schema)
            except SchemaError:raise HTTPException(422,'Некорректная схема ответа модели') from None
        skills=run['manifest'].get('_skills',[])
        if body.skill_name:
            skills=[s for s in run['manifest'].get('_available_skills',[]) if s['name']==body.skill_name]
            if not skills:raise HTTPException(403,'Скилл не разрешён для этого запуска')
        skill_refs=[{'name':s['name'],'version':s['version']} for s in skills]
        model='fixture-test-only' if settings.llm_mode=='fixture' else settings.cli_provider
        with db() as connection:
            latest=connection.execute('SELECT status FROM runs WHERE id=%s FOR UPDATE',(run['id'],)).fetchone()
            if latest['status']!='running':raise HTTPException(401,'Запуск уже завершён')
            calls=connection.execute('SELECT count(*) AS n FROM model_calls WHERE run_id=%s',(run['id'],)).fetchone()['n']
            if calls>=6:raise HTTPException(429,'Лимит: не более шести обращений к модели на запуск')
            call_id=connection.execute("INSERT INTO model_calls(run_id,purpose,mode,model,input_tokens,output_tokens,cost_usd,skill_refs,status) VALUES(%s,%s,%s,%s,0,0,%s,%s,'running') RETURNING id",(run['id'],body.purpose,settings.llm_mode,model,0 if settings.llm_mode=='fixture' else None,Jsonb(skill_refs))).fetchone()['id']
        result=None;job_id=None
        try:
            if settings.llm_mode=='fixture':
                result={'text':fixture_response(body),'mode':'fixture','model':model,'input_tokens':0,'output_tokens':0,'cost_usd':0,'usage':{'fixture':True}}
            else:
                if len(settings.cli_worker_token)<32 or not worker_state()['connected']:
                    raise HTTPException(503,'Локальный исполнитель CLI не подключён. Выполните python3 scripts/start.py и проверьте вход в выбранный CLI.')
                system='\n\n'.join(['Способы работы платформы:\n'+'\n\n'.join(s['content'] for s in skills),body.system]) if skills else body.system
                request={'purpose':body.purpose,'system':system,'prompt':body.prompt,'data':body.data,'max_tokens':body.max_tokens,'response_schema':body.response_schema}
                job_id=uuid.uuid4()
                with db() as connection:
                    connection.execute("INSERT INTO cli_jobs(id,call_id,run_id,request,status) VALUES(%s,%s,%s,%s,'queued')",(job_id,call_id,run['id'],Jsonb(request)))
                deadline=time.monotonic()+210
                while time.monotonic()<deadline:
                    with db() as connection:
                        job=connection.execute('SELECT status,result,error FROM cli_jobs WHERE id=%s',(job_id,)).fetchone()
                    if job['status']=='completed':result=job['result'];break
                    if job['status']=='error':raise HTTPException(502,job['error'])
                    time.sleep(.3)
                if result is None:raise HTTPException(504,'CLI не ответил вовремя. Автоматического повторного вызова не было; проверьте локальный исполнитель.')
                if body.response_schema:
                    try:
                        value=json.loads(result['text']);Draft202012Validator(body.response_schema).validate(value)
                    except (ValueError,ValidationError,TypeError):
                        raise HTTPException(502,'CLI вернул ответ не по ожидаемой схеме. Изменения не применены.') from None
        except Exception:
            with db() as connection:
                if result is not None:
                    connection.execute("UPDATE model_calls SET status='error',model=%s,input_tokens=%s,output_tokens=%s,cost_usd=%s,usage=%s WHERE id=%s",(result['model'],result['input_tokens'],result['output_tokens'],result['cost_usd'],Jsonb({**result.get('usage',{}), **({'provider':result['provider']} if 'provider' in result else {})}),call_id))
                    connection.execute('UPDATE runs SET input_tokens=input_tokens+%s,output_tokens=output_tokens+%s,cost_usd=%s WHERE id=%s',(result['input_tokens'],result['output_tokens'],0 if settings.llm_mode=='fixture' else None,run['id']))
                else:
                    connection.execute("UPDATE model_calls SET status='error' WHERE id=%s",(call_id,))
                if job_id:
                    connection.execute("UPDATE cli_jobs SET status='error',error='Обращение к CLI отменено или завершилось ошибкой',finished_at=now(),request='{}' WHERE id=%s AND status IN ('queued','claimed')",(job_id,))
            raise
        with db() as connection:
            connection.execute('UPDATE model_calls SET model=%s,input_tokens=%s,output_tokens=%s,cost_usd=%s,status=%s,usage=%s WHERE id=%s',(result['model'],result['input_tokens'],result['output_tokens'],result['cost_usd'],'completed',Jsonb({**result.get('usage',{}), **({'provider':result['provider']} if 'provider' in result else {})}),call_id))
            connection.execute('UPDATE runs SET input_tokens=input_tokens+%s,output_tokens=output_tokens+%s,cost_usd=%s WHERE id=%s',(result['input_tokens'],result['output_tokens'],0 if settings.llm_mode=='fixture' else None,run['id']))
        return result

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="interface")
    return app


app = create_app()
