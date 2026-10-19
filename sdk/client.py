"""Маленький SDK: HTTP, знания и модель через платформу. Ключей модели здесь нет."""
import json
import os
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    input: dict
    run_token: str = Field(min_length=20, max_length=256)
    platform_url: str


class Context:
    def __init__(self, platform_url, token):
        # У агента один заранее известный шлюз. POST /run не превращается в HTTP-прокси.
        allowed = os.getenv("PLATFORM_URL", "http://platform:8080").rstrip("/")
        if platform_url.rstrip("/") != allowed:
            raise ValueError("Адрес платформы не совпадает с настройкой агента")
        self.url, self.token = allowed, token

    def _request(self, path, data=None):
        body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
        request = Request(self.url + path, data=body, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=240) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                detail = json.load(error).get("detail", "Платформа отклонила запрос")
            except (ValueError, AttributeError):
                detail = "Платформа отклонила запрос"
            raise ValueError(str(detail)) from None

    def get(self, section, query=""):
        return self._request("/internal/context?" + urlencode({"section": section, "q": query}))["records"]

    def search(self, section, query):
        return self.get(section, query)

    def workspace(self):
        return self._request("/internal/workspace")

    def skills(self):
        return self._request("/internal/skills")["skills"]

    def llm(self, purpose, data, system, prompt, max_tokens=2048, response_schema=None, skill_name=None):
        return self._request("/internal/llm", {
            "purpose": purpose, "data": data, "system": system,
            "prompt": prompt, "max_tokens": max_tokens, "response_schema": response_schema, "skill_name": skill_name})["text"]


def agent(name):
    """@agent('имя') превращает функцию (input, ctx) в отдельный HTTP-сервис."""
    def decorate(function):
        app = FastAPI(title=name, docs_url=None, redoc_url=None, openapi_url=None)

        @app.get("/health")
        def health():
            return {"status": "ok", "agent": name}

        @app.post("/run")
        def run(request: RunRequest):
            try:
                output, steps = function(request.input, Context(request.platform_url, request.run_token))
                return {"output": output, "steps": steps}
            except (ValueError, KeyError) as error:
                raise HTTPException(422, str(error)) from None

        app.agent_function = function
        return app
    return decorate
