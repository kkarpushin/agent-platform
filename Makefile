.PHONY: up test stop logs
up:
	docker compose up --build -d --wait
test:
	sh scripts/test.sh
stop:
	docker compose stop
logs:
	docker compose logs --tail=80 platform task-intake daily-brief work-assistant
