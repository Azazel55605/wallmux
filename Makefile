PYTHON ?= python
PIP ?= $(PYTHON) -m pip
PIPX ?= pipx
PACKAGE_NAME ?= wallmux
BUILD_FLAGS ?= --no-isolation

.PHONY: build check clean install install-desktop install-service lint pipx-install pipx-uninstall test uninstall uninstall-desktop uninstall-service

check: lint test

lint:
	ruff check .

test:
	pytest

build: clean check
	$(PYTHON) -m build $(BUILD_FLAGS)

install: build
	$(PIP) install --force-reinstall --no-deps dist/$(PACKAGE_NAME)-*.whl

uninstall:
	$(PIP) uninstall -y $(PACKAGE_NAME)

pipx-install: build
	$(PIPX) install --force dist/$(PACKAGE_NAME)-*.whl

pipx-uninstall:
	$(PIPX) uninstall $(PACKAGE_NAME)

install-desktop:
	install -Dm644 packaging/applications/wallmux-gui.desktop $(HOME)/.local/share/applications/wallmux-gui.desktop
	install -Dm644 packaging/icons/wallmux.svg $(HOME)/.local/share/icons/hicolor/scalable/apps/wallmux.svg
	install -Dm644 packaging/icons/wallmux.svg $(HOME)/.local/share/icons/hicolor/scalable/apps/wallmux-gui.svg
	install -Dm644 packaging/icons/wallmux.svg $(HOME)/.local/share/pixmaps/wallmux-gui.svg
	@if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database $(HOME)/.local/share/applications; fi
	@if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -f $(HOME)/.local/share/icons/hicolor/index.theme ]; then gtk-update-icon-cache $(HOME)/.local/share/icons/hicolor; fi

uninstall-desktop:
	rm -f $(HOME)/.local/share/applications/wallmux-gui.desktop
	rm -f $(HOME)/.local/share/icons/hicolor/scalable/apps/wallmux.svg
	rm -f $(HOME)/.local/share/icons/hicolor/scalable/apps/wallmux-gui.svg
	rm -f $(HOME)/.local/share/pixmaps/wallmux-gui.svg
	@if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database $(HOME)/.local/share/applications; fi
	@if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -f $(HOME)/.local/share/icons/hicolor/index.theme ]; then gtk-update-icon-cache $(HOME)/.local/share/icons/hicolor; fi

install-service:
	install -Dm644 packaging/systemd/wallmux.service $(HOME)/.config/systemd/user/wallmux.service
	sed -i 's|ExecStart=/usr/bin/wallmuxd|ExecStart=$(HOME)/.local/bin/wallmuxd|' $(HOME)/.config/systemd/user/wallmux.service
	systemctl --user daemon-reload

uninstall-service:
	-systemctl --user disable --now wallmux.service
	rm -f $(HOME)/.config/systemd/user/wallmux.service
	systemctl --user daemon-reload

clean:
	rm -rf build dist *.egg-info src/*.egg-info
