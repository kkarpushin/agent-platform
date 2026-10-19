#!/usr/bin/env python3
"""One command starts the platform and the local authenticated CLI worker."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from cli_worker import Worker, WorkerError, check_cli, install_stop_handlers

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "mayak-agent-platform-v2"


def prepare_env(path, provider, port):
    """Keep unrelated .env values. Never read or copy a provider auth file."""
    if path.is_symlink():
        raise WorkerError("Файл .env является ссылкой. Используйте обычный локальный файл.")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    values = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Z_][A-Z_0-9]*)=(.*)$", line.strip())
        if match:
            values[match[1]] = match[2].strip().strip('\"\'')
    token = values.get("CLI_WORKER_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        token = secrets.token_urlsafe(32)
    updates = {"LLM_MODE": "cli", "CLI_PROVIDER": provider,
               "CLI_WORKER_TOKEN": token, "PORT": str(port)}
    lines = [line for line in text.splitlines()
             if not any(re.match(r"^\s*" + key + r"\s*=", line) for key in updates)]
    lines.extend(key + "=" + value for key, value in updates.items())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".env.", delete=False) as target:
            temporary = Path(target.name)
            os.chmod(temporary, 0o600)
            target.write("\n".join(lines).rstrip() + "\n")
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return updates


def compose(project, arguments, environment, *, quiet=False, timeout=None):
    command = ["docker", "compose", "--project-name", project, "--project-directory", str(ROOT),
               "--env-file", str(ROOT / ".env"), "-f", str(ROOT / "compose.yaml")] + arguments
    return subprocess.run(command, cwd=ROOT, env=environment, check=True, timeout=timeout,
                          stdout=subprocess.DEVNULL if quiet else None,
                          stderr=subprocess.DEVNULL if quiet else None)


def docker_check():
    try:
        version = subprocess.run(["docker", "compose", "version", "--short"], check=True,
                                 capture_output=True, text=True, timeout=15)
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", version.stdout)
        if not match or tuple(map(int, match.groups())) < (2, 24, 4):
            raise WorkerError("Нужен Docker Compose 2.24.4 или новее. Обновите Docker Desktop либо Compose.")
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=20)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise WorkerError("Запустите Docker Desktop или Docker Engine с Compose. Подготовка описана в docs/cli-setup.md.") from None


def main():
    install_stop_handlers()
    parser = argparse.ArgumentParser(description="Запуск помощника руководителя")
    parser.add_argument("--provider", choices=("claude", "codex"), required=True,
                        help="Уже установленный CLI с выполненным входом в аккаунт")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--project", default=PROJECT, help="Отдельное имя данных этой учебной системы")
    parser.add_argument("--check", action="store_true", help="Проверить среду, ничего не запускать")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or not re.fullmatch(r"[a-z][a-z0-9_-]{2,50}", args.project):
        parser.error("Порт: 1024–65535; имя проекта: строчные латинские буквы, цифры, дефис.")
    started = False
    environment = None
    try:
        check = check_cli(args.provider)
        docker_check()
        print(f"{args.provider} {check['version']}: вход в аккаунт подтверждён.", flush=True)
        if args.check:
            print("Среда готова. Обращение к модели ещё не выполнялось.")
            return 0
        values = prepare_env(ROOT / ".env", args.provider, args.port)
        environment = {**os.environ, **values}
        print("Запускаем платформу. При первом запуске сборка занимает несколько минут.", flush=True)
        started = True
        compose(args.project, ["up", "-d", "--build", "--wait", "--wait-timeout", "180"], environment)
        url = f"http://127.0.0.1:{args.port}"
        worker = Worker(url, values["CLI_WORKER_TOKEN"], args.provider)
        worker.heartbeat()
        print(f"Откройте {url}. Запрос к модели произойдёт при запуске агента.", flush=True)
        worker.run()
        return 0
    except KeyboardInterrupt:
        print("\nОстанавливаем учебную платформу; задачи и история сохраняются.", flush=True)
        return 0
    except WorkerError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Не удалось связаться с платформой. Проверьте локальный адрес и состояние контейнеров.", file=sys.stderr)
        return 1
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Запуск контейнеров не завершён. Проверьте сообщение Docker и повторите команду.", file=sys.stderr)
        return 1
    finally:
        if started and environment:
            try:
                compose(args.project, ["stop", "--timeout", "10"], environment, quiet=True, timeout=40)
            except (OSError, subprocess.SubprocessError):
                print(f"Остановите контейнеры командой: docker compose -p {args.project} stop", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
