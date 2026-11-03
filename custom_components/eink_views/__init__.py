"""E-Ink Views: renders SVG templates to a 1-bit PNG, choosing the view by HA conditions.

One config entry is one display. The views live as editable files in the HA
config directory; the display only fetches a keyed image URL.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_HEIGHT, CONF_VIEWS_DIR, CONF_WIDTH, DOMAIN, MACROS_FILE
from .engine import ViewEngine
from .http import EinkViewsImageView

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type EinkViewsConfigEntry = ConfigEntry[ViewEngine]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.http.register_view(EinkViewsImageView(hass))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EinkViewsConfigEntry) -> bool:
    views_dir = entry.data[CONF_VIEWS_DIR]
    engine = ViewEngine(
        hass,
        Path(hass.config.path(views_dir)),
        entry.options[CONF_WIDTH],
        entry.options[CONF_HEIGHT],
        shared_macros=Path(hass.config.path(views_dir)).parent / MACROS_FILE
        if "/" in views_dir
        else None,
    )
    await hass.async_add_executor_job(engine.install_defaults)
    entry.runtime_data = engine
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EinkViewsConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: EinkViewsConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
