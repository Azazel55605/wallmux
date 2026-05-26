"""Wallpaper profile selection and effective config helpers."""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any

from platformdirs import user_state_path

from wallmux.core.config import load_config, user_config_file, write_config

APP_NAME = "wallmux"
PROFILE_PLACEHOLDERS = {
    "profile",
    "category",
    "subcategory",
    "color",
    "label",
    "wallpaper_dirs",
}


@dataclass(frozen=True)
class Profile:
    name: str
    category: str = ""
    subcategory: str = ""
    color: str = ""
    wallpaper_dirs: tuple[str, ...] = ()
    backend_rules: Mapping[str, str] | None = None
    autoswitch_mode: str = ""
    filter_query: str = ""
    filter_types: tuple[str, ...] = ()
    before_switch: tuple[str, ...] = ()
    after_switch: tuple[str, ...] = ()
    include_parent_hooks: bool = False

    @property
    def label(self) -> str:
        if self.category and self.name == self.subcategory:
            return f"{self.category} / {self.name}"
        parts = [self.category, self.subcategory, self.name]
        return " / ".join(part for part in parts if part)


def profiles_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    profiles = config.get("profiles", {})
    return profiles if isinstance(profiles, Mapping) else {}


def active_profile_name(config: Mapping[str, Any]) -> str:
    return str(profiles_config(config).get("active", ""))


def list_profiles(config: Mapping[str, Any]) -> list[Profile]:
    entries = profiles_config(config).get("entries", [])
    if not isinstance(entries, list):
        return []
    profiles = [_profile_from_mapping(entry) for entry in entries if isinstance(entry, Mapping)]
    profiles = [profile for profile in profiles if profile.name]
    return sorted(profiles, key=lambda profile: profile.label.casefold())


def get_active_profile(config: Mapping[str, Any]) -> Profile | None:
    profiles = profiles_config(config)
    name = active_profile_name(config)
    if not name:
        return None
    return find_profile(
        config,
        name=name,
        category=str(profiles.get("active_category", "")),
        subcategory=str(profiles.get("active_subcategory", "")),
    )


def find_profile(
    config: Mapping[str, Any],
    *,
    name: str,
    category: str = "",
    subcategory: str = "",
) -> Profile | None:
    normalized_name = name.casefold()
    normalized_category = category.casefold()
    normalized_subcategory = subcategory.casefold()
    matches = [
        profile
        for profile in list_profiles(config)
        if profile.name.casefold() == normalized_name
        and (not category or profile.category.casefold() == normalized_category)
        and (not subcategory or profile.subcategory.casefold() == normalized_subcategory)
    ]
    return matches[0] if matches else None


def effective_config_for_profile(
    config: Mapping[str, Any],
    profile: Profile | None = None,
) -> dict[str, Any]:
    effective = deepcopy(dict(config))
    selected_profile = profile or get_active_profile(config)
    if selected_profile is None:
        return effective

    if selected_profile.wallpaper_dirs:
        effective.setdefault("general", {})["wallpaper_dirs"] = list(
            selected_profile.wallpaper_dirs
        )
    if selected_profile.backend_rules:
        backend_rules = effective.setdefault("backend_rules", {})
        backend_rules.update(dict(selected_profile.backend_rules))
    if selected_profile.autoswitch_mode:
        effective.setdefault("autoswitch", {})["mode"] = selected_profile.autoswitch_mode
    return effective


def switch_profile(
    name: str,
    *,
    category: str = "",
    subcategory: str = "",
    config_path: Path | None = None,
    config: dict[str, Any] | None = None,
    after_write: Callable[[Profile], None] | None = None,
) -> Profile:
    path = config_path or user_config_file()
    loaded_config = load_config(path) if config is None else config
    profile = find_profile(
        loaded_config,
        name=name,
        category=category,
        subcategory=subcategory,
    )
    if profile is None:
        raise ValueError(f"profile not found: {name}")

    run_profile_hooks("before_switch", loaded_config, profile)
    profiles = loaded_config.setdefault("profiles", {})
    profiles["active"] = profile.name
    profiles["active_category"] = profile.category
    profiles["active_subcategory"] = profile.subcategory
    write_config(loaded_config, path)
    if after_write is not None:
        after_write(profile)
    run_profile_hooks("after_switch", loaded_config, profile)
    return profile


def profile_entries_from_category_root(
    root: Path,
    *,
    category: str | None = None,
) -> list[dict[str, Any]]:
    expanded_root = root.expanduser()
    if not expanded_root.exists() or not expanded_root.is_dir():
        raise ValueError(f"profile category folder does not exist: {root}")

    category_name = category or expanded_root.name
    entries = [
        {
            "name": category_name,
            "category": "",
            "subcategory": "",
            "color": "",
            "wallpaper_dirs": [str(expanded_root)],
            "backend_rules": {},
            "autoswitch_mode": "",
            "filter_query": "",
            "filter_types": [],
            "before_switch": [],
            "after_switch": [],
            "include_parent_hooks": False,
        }
    ]
    for child in sorted(expanded_root.iterdir(), key=lambda path: path.name.casefold()):
        if not child.is_dir():
            continue
        entries.append(
            {
                "name": child.name,
                "category": category_name,
                "subcategory": child.name,
                "color": "",
                "wallpaper_dirs": [str(child)],
                "backend_rules": {},
                "autoswitch_mode": "",
                "filter_query": "",
                "filter_types": [],
                "before_switch": [],
                "after_switch": [],
                "include_parent_hooks": False,
            }
        )
    return entries


def profile_matches_filters(profile: Profile | None, item: Any) -> bool:
    if profile is None:
        return True
    if profile.filter_query and profile.filter_query.casefold() not in item.path.name.casefold():
        return False
    if profile.filter_types and item.wallpaper_type.value not in profile.filter_types:
        return False
    return True


def run_profile_hooks(stage: str, config: Mapping[str, Any], profile: Profile) -> None:
    profiles = _profiles_for_hook_stage(config, profile)
    commands: list[tuple[Profile, str]] = []
    for selected_profile in profiles:
        profile_commands = (
            selected_profile.before_switch
            if stage == "before_switch"
            else selected_profile.after_switch
        )
        commands.extend((selected_profile, command) for command in profile_commands)
    if not commands:
        return
    timeout = float(config.get("hooks", {}).get("timeout_seconds", 30))
    logger = get_profile_logger()
    for selected_profile, command in commands:
        values = {
            "profile": selected_profile.name,
            "category": selected_profile.category,
            "subcategory": selected_profile.subcategory,
            "color": selected_profile.color,
            "label": selected_profile.label,
            "wallpaper_dirs": " ".join(selected_profile.wallpaper_dirs),
        }
        try:
            formatted = format_profile_hook(command, values)
            result = subprocess.run(
                formatted,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_profile_hook_env(selected_profile, values),
            )
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            logger.warning("%s profile hook failed before execution: %s", stage, error)
            continue
        if result.returncode != 0:
            output = result.stderr.strip() or result.stdout.strip() or "no output"
            logger.warning(
                "%s profile hook exited %s: %s\n%s",
                stage,
                result.returncode,
                formatted,
                output,
            )


def format_profile_hook(command: str, values: Mapping[str, str]) -> str:
    fields = {
        field_name
        for _, field_name, _, _ in Formatter().parse(command)
        if field_name is not None
    }
    unsupported = fields - PROFILE_PLACEHOLDERS
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(f"unsupported profile hook placeholder(s): {names}")
    return command.format(**values)


def _profile_hook_env(profile: Profile, values: Mapping[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "WALLMUX_PROFILE": profile.name,
            "WALLMUX_PROFILE_NAME": profile.name,
            "WALLMUX_PROFILE_CATEGORY": profile.category,
            "WALLMUX_PROFILE_SUBCATEGORY": profile.subcategory,
            "WALLMUX_PROFILE_COLOR": profile.color,
            "WALLMUX_PROFILE_LABEL": profile.label,
            "WALLMUX_PROFILE_WALLPAPER_DIRS": values["wallpaper_dirs"],
        }
    )
    return env


def _profiles_for_hook_stage(config: Mapping[str, Any], profile: Profile) -> list[Profile]:
    if not profile.include_parent_hooks or not profile.category:
        return [profile]
    parent = find_profile(config, name=profile.category)
    if parent is None:
        return [profile]
    return [parent, profile]


def profile_log_file() -> Path:
    return user_state_path(APP_NAME) / "profiles.log"


def get_profile_logger() -> logging.Logger:
    logger = logging.getLogger("wallmux.profiles")
    if logger.handlers:
        return logger

    log_file = profile_log_file()
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(log_file, encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _profile_from_mapping(entry: Mapping[str, Any]) -> Profile:
    backend_rules = entry.get("backend_rules", {})
    return Profile(
        name=str(entry.get("name", "")),
        category=str(entry.get("category", "")),
        subcategory=str(entry.get("subcategory", "")),
        color=str(entry.get("color", "")),
        wallpaper_dirs=tuple(str(item) for item in entry.get("wallpaper_dirs", [])),
        backend_rules=backend_rules if isinstance(backend_rules, Mapping) else {},
        autoswitch_mode=str(entry.get("autoswitch_mode", "")),
        filter_query=str(entry.get("filter_query", "")),
        filter_types=tuple(str(item) for item in entry.get("filter_types", [])),
        before_switch=tuple(str(item) for item in entry.get("before_switch", [])),
        after_switch=tuple(str(item) for item in entry.get("after_switch", [])),
        include_parent_hooks=bool(entry.get("include_parent_hooks", False)),
    )
