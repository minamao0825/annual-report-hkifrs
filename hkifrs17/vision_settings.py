"""Keep the Step 1 vision service in browser session state across Streamlit pages."""

from __future__ import annotations

from collections.abc import MutableMapping

VISION_SETTINGS_VERSION = 2


FIELDS = {
    "base_url": ("extract_base_url", "https://api.openai.com/v1"),
    "model": ("extract_model", ""),
    "api_key": ("extract_api_key", ""),
    "fast_kimi": ("extract_fast_kimi", True),
    "timeout": ("extract_timeout", 300),
}


def _shared_key(field: str) -> str:
    return f"vision_shared_{field}"


def restore_step1_inputs(state: MutableMapping) -> None:
    """Seed Step 1 widgets from durable, non-widget session keys."""
    for field, (widget_key, default) in FIELDS.items():
        shared_key = _shared_key(field)
        if shared_key not in state:
            legacy_key = ("step2_fast_kimi" if field == "fast_kimi" else
                          "step2_timeout" if field == "timeout" else widget_key)
            state[shared_key] = state.get(widget_key, state.get(legacy_key, default))
        if widget_key not in state or state[widget_key] != state[shared_key]:
            state[widget_key] = state[shared_key]


def remember_step1_input(state: MutableMapping, field: str) -> None:
    widget_key, _ = FIELDS[field]
    state[_shared_key(field)] = state[widget_key]


def remember_page_input(state: MutableMapping, field: str, widget_key: str) -> None:
    """A later workflow page may repair a missing session setting in place."""
    if field not in FIELDS:
        raise ValueError(f"Unknown vision setting: {field}")
    state[_shared_key(field)] = state[widget_key]


def shared_vision_settings(state: MutableMapping) -> dict:
    """Read Step 1 settings, including a one-time fallback for older sessions."""
    result = {}
    for field, (widget_key, default) in FIELDS.items():
        shared_key = _shared_key(field)
        if shared_key not in state:
            legacy_key = ("step2_fast_kimi" if field == "fast_kimi" else
                          "step2_timeout" if field == "timeout" else widget_key)
            state[shared_key] = state.get(widget_key, state.get(legacy_key, default))
        result[field] = state[shared_key]
    return result
