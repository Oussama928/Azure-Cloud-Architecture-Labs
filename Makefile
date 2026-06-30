.PHONY: help install test lint typecheck build clean docker-build docker-up docker-down infra-plan infra-apply

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies
	pip install -e ".[dev]"
	cd dashboard && npm install

test: test-python test-dashboard ## Run all tests

test-python: ## Run Python tests
	python -m pytest tests/ services/*/tests/ -v --tb=short

test-dashboard: ## Run dashboard tests
	cd dashboard && npm test

lint: lint-python lint-dashboard ## Run all linters

lint-python: ## Run Python linter
	ruff check services/ tests/ functions/ ml/

lint-dashboard: ## Run dashboard linter
	cd dashboard && npm run lint

typecheck: ## Run type checking
	mypy services/ --ignore-missing-imports

build: build-dashboard ## Build all artifacts

build-dashboard: ## Build dashboard for production
	cd dashboard && npm run build

clean: ## Remove build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	rm -rf dashboard/dist dashboard/build ml/models/*.pkl ml/models/*.joblib

docker-build: ## Build all Docker images
	docker compose build

docker-up: ## Start all services
	docker compose up -d

docker-down: ## Stop all services
	docker compose down

infra-plan: ## Run Terraform plan
	cd terraform && terraform plan -var-file=environments/dev/terraform.tfvars

infra-apply: ## Run Terraform apply (requires approval)
	cd terraform && terraform apply -var-file=environments/dev/terraform.tfvars
