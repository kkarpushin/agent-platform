"""Focused browser check for schema forms; no platform/database is used.

Run with an existing local Playwright + Chromium installation:
    python3 tests/browser_schema.py

The temporary server serves only static files. All API requests are intercepted
by fixtures. Playwright is a development check, not a runtime dependency.
"""

import copy
import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    static = Path(__file__).resolve().parents[1] / "platform" / "static"
    handler = functools.partial(QuietStaticHandler, directory=str(static))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    posted = []
    errors = []
    schema = {
        "type": "object",
        "properties": {
            "disabled_by_default": {"type": "boolean", "default": False},
            "enabled_by_default": {"type": "boolean", "default": True},
            "settings": {"type": "object", "default": {"limit": 3}},
            "items": {"type": "array", "default": [1, "два"]},
            "boolean_choice": {"type": "boolean", "enum": [True, False], "default": False},
            "number_choice": {"type": "integer", "enum": [1, 2], "default": 2},
            "language": {"type": "string", "enum": ["ru"], "default": "ru"},
        },
    }
    schema["required"] = list(schema["properties"])

    def fixture(route):
        request = route.request
        if request.url.endswith("/api/bootstrap"):
            person = {"id": "mark", "name": "Марк", "role": "sales"}
            payload = {
                "demo": True, "llm_mode": "demo", "person": person,
                "people": [person], "roles": {"sales": {"title": "Продажи"}},
                "sections": [], "skills": [], "process": [],
                "agents": [{
                    "name": "schema-fixture", "version": "test", "owner": "mark",
                    "description": "Изолированная проверка формы",
                    "roles": ["sales"], "context": [], "allowed": True,
                    "input": schema,
                    "output": {"type": "object", "properties": {"markdown": {"type": "string"}}},
                }],
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
        elif request.url.endswith("/api/runs") and request.method == "POST":
            posted.append(request.post_data_json)
            route.fulfill(status=422, content_type="application/json",
                          body=json.dumps({"detail": "Учебная фикстура получила вход; реального запуска нет."}))
        else:
            raise AssertionError(f"Unexpected API request: {request.method} {request.url}")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 900})
            page.route("**/api/**", fixture)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"{base}/#agent/schema-fixture")
            page.wait_for_selector("#agent-run-form")
            expect(page.locator("#input-disabled_by_default")).not_to_be_checked()
            expect(page.locator("#input-enabled_by_default")).to_be_checked()
            assert page.locator("#agent-run-form").evaluate("form => form.checkValidity()")
            assert json.loads(page.locator("#input-settings").input_value()) == {"limit": 3}
            assert json.loads(page.locator("#input-items").input_value()) == [1, "два"]
            page.locator("#input-enabled_by_default").uncheck()
            page.click("#run-agent-button")
            expect(page.locator("#agent-run-form .form-error")).to_contain_text("фикстура получила вход")
            assert posted[-1]["input"] == {
                "disabled_by_default": False, "enabled_by_default": False,
                "settings": {"limit": 3}, "items": [1, "два"],
                "boolean_choice": False, "number_choice": 2, "language": "ru",
            }

            unsupported = [
                {"type": ["string", "null"], "default": None},
                {"type": "null"},
                {"type": "string", "nullable": True},
                {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                {"$ref": "#/$defs/Example"},
                {"type": "unknown"},
            ]
            for field_schema in unsupported:
                schema.clear()
                schema.update({"type": "object", "properties": {"special": copy.deepcopy(field_schema)}})
                page.reload()
                expect(page.locator("#run-agent-button")).to_be_disabled()
                expect(page.locator("#agent-run-form")).to_contain_text("Run API (/api/runs)")
                # Even a scripted submit must not emit a misleading empty input.
                page.locator("#agent-run-form").evaluate("form => form.dispatchEvent(new Event('submit', {cancelable:true}))")
                assert len(posted) == 1

            schema.clear()
            schema.update({"type": "array", "items": {"type": "string"}})
            page.reload()
            expect(page.locator("#run-agent-button")).to_be_disabled()
            expect(page.locator("#agent-run-form")).to_contain_text("входной объект")
            assert not errors, errors
            browser.close()
        print("PASS: required false/true; typed defaults and enums; 7 unsupported-schema guards; no page errors; no real API writes.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
