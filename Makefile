.PHONY: install install-dev test test-stdlib lint demo doctor clean

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

demo:
	notion-alchemist demo

doctor:
	notion-alchemist doctor

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache output examples/demo_output _smoke_state
	find . -name __pycache__ -type d -exec rm -rf {} +
