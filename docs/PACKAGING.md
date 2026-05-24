# Packaging

Wallmux uses standard Python packaging through `pyproject.toml` and Hatchling.

## Build Locally

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Build the wheel and source distribution:

```bash
python -m build
```

Or use the Makefile:

```bash
make build
```

The Makefile uses `python -m build --no-isolation` by default, which is convenient for local/offline testing after installing development dependencies.

For a fully isolated build, run:

```bash
python -m build
```

Build artifacts are written to `dist/`:

```text
dist/wallmux-0.1.0-py3-none-any.whl
dist/wallmux-0.1.0.tar.gz
```

## Local Install Testing

Preferred option: build and install the local wheel with `pipx`.

```bash
make pipx-install
```

This keeps Wallmux in an isolated Python environment while exposing the console entry points on your `PATH`.

Uninstall the pipx-managed app:

```bash
make pipx-uninstall
```

You can also run the equivalent commands directly:

```bash
pipx install --force dist/wallmux-0.1.0-py3-none-any.whl
pipx uninstall wallmux
```

Alternative option: build and install the local wheel into the active Python environment:

```bash
make install
```

This uses `pip install --force-reinstall --no-deps dist/wallmux-*.whl` so it tests the local package without changing already-installed dependency versions.

Uninstall Wallmux from the active Python environment:

```bash
make uninstall
```

## Validate

Run:

```bash
pytest
ruff check .
twine check dist/*
```

## Desktop Integration

Wallmux ships a desktop entry and app icon under `packaging/`.

For local pipx testing, install them into the user data directory:

```bash
make install-desktop
```

Remove them again with:

```bash
make uninstall-desktop
```

The desktop entry is:

```text
packaging/applications/wallmux-gui.desktop
```

The icon is:

```text
packaging/icons/wallmux.svg
```

The GUI Wayland app id is `wallmux-gui`, matching the desktop file basename.

## systemd User Service

The Arch package installs:

```text
/usr/lib/systemd/user/wallmux.service
```

Enable and start it:

```bash
systemctl --user enable --now wallmux.service
```

For local pipx testing, install a user-local service that points at
`~/.local/bin/wallmuxd`:

```bash
make install-service
systemctl --user enable --now wallmux.service
```

Remove it with:

```bash
make uninstall-service
```

## Hyprland Startup

Recommended Hyprland startup command:

```ini
exec-once = systemctl --user start wallmux.service
```

For Hyprland 0.55 Lua config:

```lua
hl.exec_cmd("systemctl --user start wallmux.service")
```

The daemon has retryable startup restore behavior, so it can start near
`awww-daemon` without exiting if the backend is not ready yet.

## Arch / AUR Packaging

An Arch packaging template lives at:

```text
packaging/arch/PKGBUILD
```

Before submitting to the AUR:

- Replace the placeholder GitHub `url` and `source` with the real upstream.
- Replace `sha256sums=("SKIP")` with the real release archive checksum.
- Build with `makepkg -si`.
- Run `namcap` against the package and `PKGBUILD`.

Useful local check:

```bash
cd packaging/arch
makepkg --printsrcinfo > .SRCINFO
```

## Install Built Wheel

Recommended for end users:

```bash
pipx install dist/wallmux-0.1.0-py3-none-any.whl
```

Traditional pip install:

```bash
pip install dist/wallmux-0.1.0-py3-none-any.whl
```

This installs the console entry points:

- `wallmuxctl`
- `wallmuxd`
- `wallmux-gui`

## Notes

The default config is packaged inside `wallmux.data` so installed builds can load defaults without relying on the repository checkout. The root `config/default.toml` remains as a readable project reference.

On first run, Wallmux creates the user config at:

```text
~/.config/wallmux/config.toml
```

When the packaged default config changes in future releases, Wallmux reconciles the user config automatically:

- User-changed values are kept when the key still exists.
- New default keys are added.
- Keys removed from the packaged default are removed from the user config.
