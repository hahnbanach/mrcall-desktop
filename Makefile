.PHONY: help lint format

PYTHON := venv/bin/python

help:
	@echo "Zylch — available targets:"
	@echo "  make lint    — black --check and ruff check on zylch/"
	@echo "  make format  — black and ruff --fix on zylch/"
	@echo "  make help    — show this message"

lint:
	$(PYTHON) -m black --check zylch/
	$(PYTHON) -m ruff check zylch/

format:
	$(PYTHON) -m black zylch/
	$(PYTHON) -m ruff check --fix zylch/
