.PHONY: install install-dev test test-stdlib lint preflight demo doctor clean

install:
	pip install .

install-dev:
	pip install -e ".[dev]"

# primary runner (needs dev extras)
test:
	pytest

# zero-dependency fallback: runs the same suite with the stdlib alone
test-stdlib:
	python scripts/run_tests.py

lint:
	ruff check src tests scripts

# SkillHub pre-flight self-check (12 items, exit 0/1/2)
preflight:
	python scripts/skillhub_preflight.py

demo:
	page-alchemist demo

doctor:
	page-alchemist doctor

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache output examples/demo_output _smoke_state
	find . -name __pycache__ -type d -exec rm -rf {} +
