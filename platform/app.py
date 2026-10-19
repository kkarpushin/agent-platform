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
from decimal import Decimal, InvalidOperation
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
SECTION_TITLES = {
    "services": "Услуги и цены", "costs": "Себестоимость", "cases": "Кейсы",
    "clients": "Клиенты", "templates": "Шаблоны", "technical": "Технические сведения",
}
LAYER_TITLES = [
    "Цели и люди", "Роли и полномочия", "Знания и информация", "Скиллы",
    "Агенты и модели", "Инструменты и доступы", "Процессы", "Запуск и состояние",
    "Проверка и улучшение",
]
PROCESS_STEPS = [
    "Получить заявку", "Найти разрешённые знания", "Выбрать услуги",
    "Рассчитать цену программой", "Подготовить предложение", "Проверить результат",
    "Получить решение человека",
]


@dataclass
class Settings:
    root: Path = field(default_factory=lambda: Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parents[1])))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "postgresql://platform:platform@db:5432/platform"))
    platform_url: str = field(default_factory=lambda: os.getenv("PLATFORM_URL", "http://platform:8080"))
    agent_urls: dict = field(default_factory=lambda: json.loads(os.getenv("AGENT_URLS", '{}')))
    auth_mode: str = field(default_factory=lambda: os.getenv("AUTH_MODE", "demo"))
    person_tokens: dict = field(default_factory=lambda: json.loads(os.getenv("PERSON_TOKENS", '{}')))
    llm_mode: str = field(default_factory=lambda: os.getenv("LLM_MODE", "demo"))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", ""))
    input_price: str | None = field(default_factory=lambda: os.getenv("INPUT_PRICE_PER_MILLION") or None)
    output_price: str | None = field(default_factory=lambda: os.getenv("OUTPUT_PRICE_PER_MILLION") or None)
    agent_timeout: float = field(default_factory=lambda: float(os.getenv("AGENT_TIMEOUT_SECONDS", "180")))

    def validate(self):
        self.root = Path(self.root)
        if self.auth_mode not in {"demo", "token"}:
            raise ValueError("AUTH_MODE должен быть demo или token")
        if self.llm_mode not in {"demo", "anthropic"}:
            raise ValueError("LLM_MODE должен быть demo или anthropic")
        if self.auth_mode == "token" and not self.person_tokens:
            raise ValueError("В режиме token заполните PERSON_TOKENS")
        for value in (self.input_price, self.output_price):
            if value is not None and (not Decimal(value).is_finite() or Decimal(value) < 0):
                raise ValueError("Цена токенов должна быть конечным неотрицательным числом")
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
        skills.append({"name": meta["name"], "description": meta["description"], "content": content, "version": hashlib.sha256(path.read_bytes()).hexdigest()})
    skill_names = {s["name"] for s in skills}
    for manifest in agents.values():
        if not isinstance(manifest.get("skills", []), list) or not set(manifest.get("skills", [])) <= skill_names:
            raise ValueError(f"Агент {manifest['name']} объявил отсутствующий скилл")
    goals_path = root / "config/goals.yaml"
    goals = yaml.safe_load(goals_path.read_text(encoding="utf-8")) if goals_path.exists() else {
        "purpose": "Подготовить обоснованное предложение клиенту и передать решение человеку",
        "success_criteria": ["Цена рассчитана по источникам", "Доступы соблюдены", "Решение привязано к версии"],
    }
    process = PROCESS_STEPS
    for path in sorted((root / "processes").glob("*.md")):
        if path.read_text(encoding="utf-8").startswith("---"):
            meta, _ = frontmatter(path)
            if isinstance(meta.get("steps"), list) and all(isinstance(s, str) for s in meta["steps"]):
                process = meta["steps"]
                break
    return {"roles": roles, "people": people, "agents": agents, "skills": skills, "goals": goals, "process": process}, records


def demo_response(body: LLMBody) -> str:
    if body.purpose not in {"select_services", "draft_proposal"}:
        raise HTTPException(422, "Для этой операции нет демонстрационного ответа. Добавьте явный пример в demo_response или используйте настроенную модель.")
    data = body.data
    if body.purpose == "select_services":
        task = str(data.get("task", "")).casefold()
        services = data.get("services", [])
        selected = []
        for item in services:
            service = item.get("data", item)
            if any(str(keyword).casefold() in task for keyword in service.get("keywords", []) if str(keyword).strip()):
                selected.append(service["service_id"])
        return json.dumps({"service_ids": selected}, ensure_ascii=False)
    client = data.get("client", "Клиент")
    if isinstance(client, dict):
        client = client.get("name", client.get("data", {}).get("name", "Клиент"))
    services = data.get("services", [])
    lines = ["> Демонстрационный текст: модель не вызывалась. Требуется проверка человеком.", "", f"Для клиента «{client}» подготовлен состав работ по задаче: {data.get('task', '')}", "", "## Предлагаемые работы"]
    for item in services:
        lines.append(f"- {item.get('name', item.get('service_id', 'Услуга'))}")
    cases = data.get("cases", [])
    if cases:
        lines += ["", "## Примеры из базы знаний"]
        lines += [f"- {item.get('title', 'Кейс')} [{item.get('id', '')}]" for item in cases if isinstance(item, dict)]
    lines += ["", "Вопрос перед началом: кто со стороны клиента предоставит исходные материалы и подтвердит результат?"]
    return "\n".join(lines)


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
        # A local restart cannot resume an in-flight HTTP call. Preserve the failed run.
        with db() as connection:
            connection.execute("UPDATE runs SET status='error', error='Платформа перезапущена во время выполнения. Запустите заново с новым идентификатором запроса.', finished_at=now(), duration_ms=(extract(epoch FROM now()-created_at)*1000)::integer WHERE status='running'")
            connection.execute("UPDATE run_tokens SET active=false WHERE active=true")
        yield

    app = FastAPI(title="Маяк — девять слоёв AI-системы", lifespan=lifespan)
    app.state.settings, app.state.config = settings, config
    app.state.sync_sources, app.state.db = sync_sources, db

    @app.middleware("http")
    async def request_limits(request: Request, call_next):
        # Agents can reach this listener over their private Docker network.
        # The local-demo employee switch must NEVER be available to them:
        # otherwise X-Person: anna would bypass every run-token scope check.
        internal = request.url.path in {"/internal/context", "/internal/llm"}
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
        result["source_warnings"] = source_warnings(connection, run_id)
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

    @app.get("/api/health")
    def health():
        try:
            with db() as connection:
                connection.execute("SELECT 1")
            return {"status": "ok", "database": "ok", "llm_mode": settings.llm_mode}
        except psycopg.Error:
            return JSONResponse({"status": "error", "database": "unavailable", "llm_mode": settings.llm_mode}, status_code=503)

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
        return {"demo": settings.auth_mode == "demo", "llm_mode": settings.llm_mode,
            "person": current, "people": config["people"] if settings.auth_mode == "demo" else [current],
            "roles": config["roles"], "agents": [{**manifest, "allowed": current["role"] in manifest["roles"], "metrics": metrics.get(manifest["name"], {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0})} for manifest in config["agents"].values()],
            "sections": sections, "skills": config["skills"], "process": config["process"],
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
        manifest = config["agents"].get(body.agent)
        if manifest is None:
            raise HTTPException(404, "Агент не найден")
        if current["role"] not in manifest["roles"]:
            raise HTTPException(403, "Ваша роль не может запускать этого агента")
        schema_check(manifest["input"], body.input, "Вход агента")
        runtime_manifest = {**manifest, "_skills": [s for s in config["skills"] if s["name"] in manifest.get("skills", [])]}
        fingerprint = canonical_hash({"agent": body.agent, "input": body.input})
        run_id, token = uuid.uuid4(), secrets.token_urlsafe(48)
        with db() as connection:
            inserted = connection.execute("""INSERT INTO runs
                (id,agent,person_id,role,status,input,input_hash,request_id,manifest,llm_mode,cost_usd)
                VALUES (%s,%s,%s,%s,'running',%s,%s,%s,%s,%s,%s)
                ON CONFLICT (person_id,request_id) DO NOTHING RETURNING id""",
                (run_id, body.agent, current["id"], current["role"], Jsonb(body.input), fingerprint, body.request_id, Jsonb(runtime_manifest), settings.llm_mode, 0 if settings.llm_mode == "demo" or (settings.input_price is not None and settings.output_price is not None) else None)).fetchone()
            if not inserted:
                previous = connection.execute("SELECT * FROM runs WHERE person_id=%s AND request_id=%s", (current["id"], body.request_id)).fetchone()
                if previous["input_hash"] != fingerprint:
                    raise HTTPException(409, "Этот request_id уже использован с другим входом. Создайте новый идентификатор.")
                return full_run(connection, previous)
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
                safe_errors = {
                    "client_not_found": "Клиент не найден в доступных знаниях. Проверьте имя в разделе «Знания».",
                    "Клиент не найден в доступных знаниях. Проверьте имя в разделе «Знания».": "Клиент не найден в доступных знаниях. Проверьте имя в разделе «Знания».",
                    "Клиент не найден. Добавьте запись о клиенте и синхронизируйте знания.": "Клиент не найден. Добавьте запись о клиенте и синхронизируйте знания.",
                    "Модель вернула непонятный список услуг. Расчёт остановлен.": "Модель вернула непонятный список услуг. Расчёт остановлен.",
                    "Нужен непустой список идентификаторов услуг.": "Нужен непустой список идентификаторов услуг.",
                    "Нет подходящей услуги в каталоге. Уточните задачу или добавьте услугу.": "Нет подходящей услуги в каталоге. Уточните задачу или добавьте услугу.",
                    "Модель выбрала неизвестную или повторяющуюся услугу. Расчёт остановлен.": "Модель выбрала неизвестную или повторяющуюся услугу. Расчёт остановлен.",
                    "model_unavailable": "Модель недоступна. Проверьте ANTHROPIC_API_KEY, ANTHROPIC_MODEL и баланс провайдера.",
                    "invalid_selection": "Модель выбрала услуги, которых нет в доступном прайсе. Требуется проверка человеком.",
                }
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
            schema_check({"type": "array", "maxItems": 50, "items": {"type": "object", "required": ["title", "detail"], "properties": {"title": {"type": "string", "maxLength": 200}, "detail": {"type": "string", "maxLength": 5000}}, "additionalProperties": False}}, steps, "Шаги агента")
            # Guard against accidental token echoes in code supplied by learners.
            if token in json.dumps(result, ensure_ascii=False) or (settings.anthropic_api_key and settings.anthropic_api_key in json.dumps(result, ensure_ascii=False)):
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

    @app.post("/internal/llm")
    def llm(body: LLMBody, run=Depends(run_token)):
        try:
            data_json = json.dumps(body.data, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise HTTPException(422, "Данные модели должны быть корректным JSON без NaN и Infinity") from None
        if len(data_json) > 200000:
            raise HTTPException(413, "Слишком большой контекст модели")
        skills = run["manifest"].get("_skills", [])
        skill_refs = [{"name": s["name"], "version": s["version"]} for s in skills]
        model = "demo-deterministic" if settings.llm_mode == "demo" else settings.anthropic_model
        # Reserve a call while locking the run. Failed requests also use the budget.
        with db() as connection:
            latest = connection.execute("SELECT status FROM runs WHERE id=%s FOR UPDATE", (run["id"],)).fetchone()
            if latest["status"] != "running":
                raise HTTPException(401, "Запуск уже завершён")
            calls = connection.execute("SELECT count(*) AS n FROM model_calls WHERE run_id=%s", (run["id"],)).fetchone()["n"]
            if calls >= 6:
                raise HTTPException(429, "Лимит: не более шести обращений к модели на запуск")
            call_id = connection.execute("INSERT INTO model_calls(run_id,purpose,mode,model,input_tokens,output_tokens,cost_usd,skill_refs,status) VALUES (%s,%s,%s,%s,0,0,%s,%s,'running') RETURNING id",
                (run["id"], body.purpose, settings.llm_mode, model, 0 if settings.llm_mode == "demo" else None, Jsonb(skill_refs))).fetchone()["id"]
        result = None
        def record_usage(result, status):
            with db() as connection:
                connection.execute("UPDATE model_calls SET model=%s,input_tokens=%s,output_tokens=%s,cost_usd=%s,status=%s,usage=%s WHERE id=%s", (result["model"], result["input_tokens"], result["output_tokens"], result["cost_usd"], status, Jsonb(result.get("usage", {})), call_id))
                connection.execute("""UPDATE runs SET input_tokens=input_tokens+%s,output_tokens=output_tokens+%s,
                    cost_usd=CASE WHEN cost_usd IS NULL OR %s::numeric IS NULL THEN NULL ELSE cost_usd+%s END WHERE id=%s""", (result["input_tokens"], result["output_tokens"], result["cost_usd"], result["cost_usd"], run["id"]))

        try:
            if settings.llm_mode == "demo":
                try:
                    text = demo_response(body)
                except (TypeError, KeyError, AttributeError):
                    raise HTTPException(422, "Проверьте data для демонстрационного ответа модели") from None
                result = {"text": text, "mode": "demo", "model": model, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0}
            else:
                if not settings.anthropic_api_key:
                    raise HTTPException(503, "Для настоящей модели заполните ANTHROPIC_API_KEY на платформе")
                if not settings.anthropic_model:
                    raise HTTPException(503, "Для настоящей модели заполните ANTHROPIC_MODEL на платформе")
                system = "\n\n".join(["Способы работы платформы:\n" + "\n\n".join(s["content"] for s in skills), body.system]) if skills else body.system
                try:
                    response = httpx.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01"}, json={"model": model, "max_tokens": body.max_tokens, "system": system, "messages": [{"role": "user", "content": body.prompt + "\n\nДанные:\n" + json.dumps(body.data, ensure_ascii=False)}]}, timeout=60, follow_redirects=False, trust_env=False)
                    if response.status_code != 200:
                        raise HTTPException(502, "Провайдер модели отклонил запрос. Проверьте ключ, модель и баланс. Демонстрационный ответ не подставлялся.")
                    payload = response.json()
                    usage = payload["usage"]
                    uncached, tokens_out = int(usage["input_tokens"]), int(usage["output_tokens"])
                    cache_read = int(usage.get("cache_read_input_tokens", 0))
                    cache_write = int(usage.get("cache_creation_input_tokens", 0))
                    tokens_in = uncached + cache_read + cache_write
                    if min(uncached, tokens_out, cache_read, cache_write) < 0:
                        raise ValueError("usage")
                    cost = None
                    if settings.input_price is not None and settings.output_price is not None and not cache_read and not cache_write:
                        cost = (Decimal(tokens_in)*Decimal(settings.input_price) + Decimal(tokens_out)*Decimal(settings.output_price)) / 1000000
                    result = {"text": "", "mode": "anthropic", "model": payload.get("model", model), "input_tokens": tokens_in, "output_tokens": tokens_out, "cost_usd": cost, "usage": {"input_tokens": uncached, "output_tokens": tokens_out, "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}}
                    if payload.get("stop_reason") == "max_tokens":
                        raise HTTPException(502, "Модель не завершила ответ: достигнут лимит токенов. Неполный результат не принят.")
                    result["text"] = "\n".join(block["text"] for block in payload["content"] if block.get("type") == "text")
                    if not result["text"].strip():
                        raise HTTPException(502, "Модель не вернула текстовый ответ")
                except (httpx.HTTPError, ValueError, TypeError, KeyError):
                    raise HTTPException(502, "Не удалось получить ответ модели. Демонстрационный ответ не подставлялся.") from None
        except Exception:
            if result is not None:
                record_usage(result, "error")
            else:
                with db() as connection:
                    connection.execute("UPDATE model_calls SET status='error' WHERE id=%s", (call_id,))
                    if settings.llm_mode == "anthropic":
                        connection.execute("UPDATE runs SET cost_usd=NULL WHERE id=%s", (run["id"],))
            raise
        record_usage(result, "completed")
        return jsonable_encoder(result)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="interface")
    return app


app = create_app()
