PYTHON ?= python
PIP ?= $(PYTHON) -m pip
PIPX ?= pipx
PACKAGE_NAME ?= wallmux

.PHONY: build check clean install lint pipx-install pipx-uninstall test uninstall

check: lint test

lint:
	ruff check .

test:
	pytest

build: clean check
	$(PYTHON) -m build

install: build
	$(PIP) install --force-reinstall --no-deps dist/$(PACKAGE_NAME)-*.whl

uninstall:
	$(PIP) uninstall -y $(PACKAGE_NAME)

pipx-install: build
	$(PIPX) install --force dist/$(PACKAGE_NAME)-*.whl

pipx-uninstall:
	$(PIPX) uninstall $(PACKAGE_NAME)

clean:
	rm -rf build dist *.egg-info src/*.egg-info
