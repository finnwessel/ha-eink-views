"""Config and options flow for E-Ink Views."""

from __future__ import annotations

import re
import secrets
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

from .const import (
    CONF_ACCESS_KEY,
    CONF_HEIGHT,
    CONF_ROTATE_KEY,
    CONF_VIEWS_DIR,
    CONF_WIDTH,
    DEFAULT_HEIGHT,
    DEFAULT_VIEWS_DIR,
    DEFAULT_WIDTH,
    DOMAIN,
    VIEWS_DIR_PATTERN,
)

_SIZE = vol.All(vol.Coerce(int), vol.Range(min=16, max=4096))


def _clean_views_dir(value: str) -> str | None:
    """Normalised directory, or None if it is not "name" or "parent/name"."""
    value = value.strip().strip("/")
    return value if re.fullmatch(VIEWS_DIR_PATTERN, value) else None


def _new_key() -> str:
    return secrets.token_urlsafe(24)


class EinkViewsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and _clean_views_dir(user_input[CONF_VIEWS_DIR]) is None:
            errors[CONF_VIEWS_DIR] = "invalid_views_dir"
        elif user_input is not None:
            views_dir = _clean_views_dir(user_input[CONF_VIEWS_DIR])
            self._async_abort_entries_match({CONF_VIEWS_DIR: views_dir})
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_VIEWS_DIR: views_dir},
                options={
                    CONF_WIDTH: user_input[CONF_WIDTH],
                    CONF_HEIGHT: user_input[CONF_HEIGHT],
                    CONF_ACCESS_KEY: _new_key(),
                },
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="E-Ink"): str,
                    vol.Required(CONF_VIEWS_DIR, default=DEFAULT_VIEWS_DIR): str,
                    vol.Required(CONF_WIDTH, default=DEFAULT_WIDTH): _SIZE,
                    vol.Required(CONF_HEIGHT, default=DEFAULT_HEIGHT): _SIZE,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point an entry at another directory. Files are not moved; the URL stays the same."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        views_dir = _clean_views_dir(user_input[CONF_VIEWS_DIR]) if user_input else None
        if user_input is not None and views_dir is None:
            errors[CONF_VIEWS_DIR] = "invalid_views_dir"
        elif user_input is not None:
            if views_dir != entry.data[CONF_VIEWS_DIR]:
                self._async_abort_entries_match({CONF_VIEWS_DIR: views_dir})
            return self.async_update_reload_and_abort(
                entry, data_updates={CONF_VIEWS_DIR: views_dir}
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_VIEWS_DIR, default=entry.data[CONF_VIEWS_DIR]): str}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EinkViewsOptionsFlow()


class EinkViewsOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = self.config_entry.options
        if user_input is not None:
            key = _new_key() if user_input[CONF_ROTATE_KEY] else options[CONF_ACCESS_KEY]
            return self.async_create_entry(
                data={
                    CONF_WIDTH: user_input[CONF_WIDTH],
                    CONF_HEIGHT: user_input[CONF_HEIGHT],
                    CONF_ACCESS_KEY: key,
                }
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_WIDTH, default=options[CONF_WIDTH]): _SIZE,
                    vol.Required(CONF_HEIGHT, default=options[CONF_HEIGHT]): _SIZE,
                    vol.Required(CONF_ROTATE_KEY, default=False): bool,
                }
            ),
            description_placeholders={
                "image_path": (
                    f"/api/eink_views/{self.config_entry.entry_id}/image.png"
                    f"?key={options[CONF_ACCESS_KEY]}"
                ),
            },
        )
