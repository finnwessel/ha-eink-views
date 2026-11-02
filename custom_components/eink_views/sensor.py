"""Shows which view the next image will be, and why rendering last failed."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .engine import ViewsConfigError

SCAN_INTERVAL = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ActiveViewSensor(entry)], True)


class ActiveViewSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "active_view"

    def __init__(self, entry) -> None:
        self._engine = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_active_view"

    async def async_update(self) -> None:
        names: list[str] = []
        try:
            names = [view.name for view in await self._engine.async_views()]
            self._attr_native_value = await self._engine.async_active_view()
        except ViewsConfigError as err:
            self._attr_native_value = None
            self._engine.last_error = str(err)
        last = self._engine.last_good
        self._attr_extra_state_attributes = {
            "views": names,
            "last_served_view": last.view if last else None,
            "last_error": self._engine.last_error,
        }
