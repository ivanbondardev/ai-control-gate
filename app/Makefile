.PHONY: test test-integration

# Unit and route tests. No packages, no network, no database required.
test:
	python3 -m unittest discover -s tests -v

# Storage tests against a real PostgreSQL. Run inside the stack:
#   docker compose exec api python -m unittest discover -s tests/integration -v
test-integration:
	python3 -m unittest discover -s tests/integration -v
