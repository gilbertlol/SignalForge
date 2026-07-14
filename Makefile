.DEFAULT_GOAL := help
-include .env
export

.PHONY: help setup build up down restart migrate makemigrations test lint format \
        typecheck check logs shell dbshell superuser ps

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Create .env from template and build images
	@test -f .env || cp .env.example .env
	docker compose build

build: ## Build (or rebuild) all images
	docker compose build

up: ## Start the full stack in the background
	docker compose up -d

down: ## Stop the stack
	docker compose down

restart: down up ## Restart the stack

migrate: ## Apply database migrations
	docker compose run --rm web python manage.py migrate

makemigrations: ## Generate new migrations
	docker compose run --rm web python manage.py makemigrations

test: ## Run the automated test suite
	docker compose run --rm -e DJANGO_SETTINGS_MODULE=config.settings.test web pytest

lint: ## Run ruff lint checks
	docker compose run --rm web ruff check .

format: ## Apply ruff formatting
	docker compose run --rm web ruff format .

typecheck: ## Run mypy static type checks
	docker compose run --rm web mypy apps config

check: ## Run lint, typecheck, django checks, migration check, and tests
	docker compose run --rm web ruff check .
	docker compose run --rm web ruff format --check .
	docker compose run --rm web mypy apps config
	docker compose run --rm web python manage.py check
	docker compose run --rm web python manage.py makemigrations --check --dry-run
	docker compose run --rm -e DJANGO_SETTINGS_MODULE=config.settings.test web pytest

logs: ## Tail logs from all services
	docker compose logs -f

shell: ## Open a Django shell
	docker compose run --rm web python manage.py shell

dbshell: ## Open a psql shell against the local database
	docker compose exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

superuser: ## Create the first local owner account (interactive, no default password)
	docker compose run --rm web python manage.py createsuperuser

ps: ## Show running services
	docker compose ps
