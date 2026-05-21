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

If you have already installed the development dependencies and want to avoid build isolation:

```bash
python -m build --no-isolation
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
