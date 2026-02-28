.PHONY: docker-build run docker-run test-proxy test-e2e test-k8s test-lifecycle all-test

# Docker
docker-build:
	docker build -t multi-mcp .

docker-run:
	docker run -p 8085:8085 multi-mcp

# Run
run:
	uv run main.py start

# Tests
test-proxy:
	pytest -s tests/proxy_test.py

test-e2e:
	pytest -s tests/e2e_test.py

test-k8s: docker-build
	pytest -s tests/k8s_test.py

test-lifecycle:
	pytest -s tests/lifecycle_test.py

# All tests together
all-test: test-proxy test-e2e test-lifecycle test-k8s