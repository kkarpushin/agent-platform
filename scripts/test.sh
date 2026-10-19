#!/bin/sh
# Отдельный Compose-проект; ни ключи модели, ни пользовательская база не используются.
set -eu
cd "$(dirname "$0")/.."
compose_test() {
    docker compose -p mayak-platform-tests -f compose.yaml -f compose.test.yaml --profile test "$@"
}
cleanup() {
    test_status=$?
    trap - EXIT
    if [ "$test_status" -ne 0 ]; then
        compose_test logs --tail=80 platform client-brief commercial-proposal
    fi
    compose_test down -v >/dev/null 2>&1 || true
    exit "$test_status"
}
trap cleanup EXIT
compose_test up --build -d --wait db client-brief commercial-proposal platform
compose_test run --build --rm tests
