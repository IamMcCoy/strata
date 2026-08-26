# Strata — 개발 명령. 런타임 의존성은 0개이므로 여기 있는 건 전부 개발/검증용이다.
.PHONY: help install test lint check redis-up redis-down redis-logs test-integration clean

# docker-compose.yml과 tests/test_memory_integration.py가 함께 읽는다.
# 주석을 값 뒤에 붙이면 공백까지 값에 들어간다 — 반드시 앞줄에.
REDIS_PORT ?= 6379
export REDIS_PORT

help:  ## 사용 가능한 명령
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## 환경 생성 (Python 3.12, dev 그룹)
	uv sync

test:  ## 단위 테스트 — 외부 의존 없음. Redis 없어도 초록이어야 한다
	uv run pytest -q

lint:  ## lint/포맷/타입 검사 전체
	uv run pre-commit run --all-files

check: lint test  ## 커밋 전 검사 전체

# --- Redis ---------------------------------------------------------------
# SQLite에는 대응 target이 없다 — 파일 하나라 올릴 서버가 없다 (그게 SQLiteMemory를 고른 이유다).

redis-up:  ## 테스트용 Redis 기동 (healthcheck 통과까지 대기)
	docker compose up -d --wait redis

redis-down:  ## 테스트용 Redis 정리
	docker compose down

redis-logs:  ## Redis 로그
	docker compose logs redis

test-integration: redis-up  ## 실제 Redis + 실제 SQLite 파일 + 실제 멀티프로세스로 검증
	uv run pytest tests/test_memory_integration.py tests/test_pipeline_integration.py -v

clean:  ## 테스트 부산물 제거
	rm -rf .pytest_cache .mypy_cache .tmp
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
