"""Pick the first view whose conditions hold and render it."""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import voluptuous as vol
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers import condition as ha_condition
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util

from .const import MACROS_FILE, VIEWS_FILE
from .raster import svg_to_png

_LOGGER = logging.getLogger(__name__)
_DEFAULTS_DIR = Path(__file__).parent / "default_views"


class ViewsConfigError(HomeAssistantError):
    """views.yaml is missing or invalid."""


@dataclass(slots=True)
class View:
    name: str
    template: str
    when: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Rendered:
    view: str
    png: bytes
    etag: str


def parse_views(raw: Any) -> list[View]:
    """Validate the structure of views.yaml; the order is the priority."""
    entries = raw.get("views") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ViewsConfigError(f"{VIEWS_FILE} needs a non-empty 'views' list")
    views: list[View] = []
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name:
            raise ViewsConfigError(f"Every view in {VIEWS_FILE} needs a name")
        template = entry.get("template", f"{name}.svg.j2")
        # Templates are looked up by file name only, never outside the views directory.
        if not isinstance(template, str) or Path(template).name != template:
            raise ViewsConfigError(f"View '{name}' has an invalid template file name")
        when = entry.get("when") or []
        views.append(View(name, template, when if isinstance(when, list) else [when]))
    if len({view.name for view in views}) != len(views):
        raise ViewsConfigError(f"View names in {VIEWS_FILE} must be unique")
    return views


class ViewEngine:
    """Reads the files on every use, so an edited view shows up without a reload."""

    def __init__(self, hass: HomeAssistant, views_dir: Path, width: int, height: int) -> None:
        self.hass = hass
        self.views_dir = views_dir
        self.width = width
        self.height = height
        self.last_good: Rendered | None = None
        self.last_error: str | None = None

    def install_defaults(self) -> None:
        """Copy the bundled examples on first start; existing files are never touched."""
        if not self.views_dir.exists():
            shutil.copytree(_DEFAULTS_DIR, self.views_dir)

    def _read_views(self) -> list[View]:
        try:
            raw = yaml.safe_load((self.views_dir / VIEWS_FILE).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as err:
            raise ViewsConfigError(f"Cannot read {VIEWS_FILE}: {err}") from err
        return parse_views(raw)

    def _read_template(self, view: View) -> str:
        macros = self.views_dir / MACROS_FILE
        prefix = macros.read_text(encoding="utf-8") if macros.exists() else ""
        return prefix + (self.views_dir / view.template).read_text(encoding="utf-8")

    async def async_views(self) -> list[View]:
        return await self.hass.async_add_executor_job(self._read_views)

    async def _async_matches(self, view: View) -> bool:
        if not view.when:
            return True
        try:
            validated = await ha_condition.async_validate_conditions_config(
                self.hass, cv.CONDITIONS_SCHEMA(view.when)
            )
            check = await ha_condition.async_conditions_from_config(
                self.hass, validated, _LOGGER, f"eink_views {view.name}"
            )
            return bool(check({}))
        except (HomeAssistantError, vol.Invalid) as err:
            self._note_error(f"Conditions of view '{view.name}': {err}")
            return False

    async def async_matching(self) -> list[View]:
        return [view for view in await self.async_views() if await self._async_matches(view)]

    async def async_active_view(self) -> str | None:
        matching = await self.async_matching()
        return matching[0].name if matching else None

    async def async_render_view(self, view: View) -> Rendered:
        source = await self.hass.async_add_executor_job(self._read_template, view)
        svg = Template(source, self.hass).async_render(
            {
                "view": view.name,
                "width": self.width,
                "height": self.height,
                "rendered_at": dt_util.now(),
            },
            parse_result=False,
        )
        png = await self.hass.async_add_executor_job(
            svg_to_png, svg, self.width, self.height
        )
        return Rendered(view.name, png, hashlib.sha256(png).hexdigest())

    async def async_render_active(self) -> Rendered | None:
        """Render the first working match, or fall back to the last good image."""
        try:
            matching = await self.async_matching()
        except ViewsConfigError as err:
            self._note_error(str(err))
            return self.last_good
        for view in matching:
            try:
                rendered = await self.async_render_view(view)
            except (OSError, TemplateError, ValueError, RuntimeError) as err:
                self._note_error(f"View '{view.name}': {err}")
                continue
            self.last_good = rendered
            self.last_error = None
            return rendered
        return self.last_good

    def _note_error(self, message: str) -> None:
        self.last_error = message
        _LOGGER.error("%s", message)
