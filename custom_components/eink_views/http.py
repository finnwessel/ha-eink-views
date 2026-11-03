"""Image endpoint. The device has no HA login, so a per-entry key opens this one image only."""

from __future__ import annotations

import hmac

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError

from .const import CONF_ACCESS_KEY, DOMAIN
from .engine import Rendered, ViewsConfigError
from .raster import LAYERS


class EinkViewsImageView(HomeAssistantView):
    url = "/api/eink_views/{entry_id}/image.png"
    name = "api:eink_views:image"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        # Unknown entry and wrong key look the same, so ids cannot be probed.
        key = request.query.get("key", "")
        if (
            entry is None
            or entry.domain != DOMAIN
            or not hmac.compare_digest(key.encode(), entry.options[CONF_ACCESS_KEY].encode())
        ):
            raise web.HTTPForbidden
        if not hasattr(entry, "runtime_data"):
            raise web.HTTPServiceUnavailable
        engine = entry.runtime_data

        # all: one black-and-white image. black + red: the two planes of a black/white/red
        # display, fetched in that order; red reuses the render of the black request.
        layer = request.query.get("layer", "all")
        if layer not in LAYERS:
            raise web.HTTPBadRequest(text=f"layer must be one of: {', '.join(LAYERS)}")

        preview = request.query.get("view")
        if preview is not None:
            rendered = await self._async_preview(engine, preview)
        else:
            rendered = await engine.async_render_active(reuse_recent=layer == "red")
        if rendered is None:
            raise web.HTTPServiceUnavailable

        etag = f'"{rendered.etag(layer)}"'
        headers = {
            "ETag": etag,
            "X-Eink-View": rendered.view,
            "X-Eink-Layer": layer,
            "Cache-Control": "no-store",
        }
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers=headers)
        return web.Response(body=rendered.png(layer), content_type="image/png", headers=headers)

    async def _async_preview(self, engine, name: str) -> Rendered:
        """Render a named view regardless of its conditions, for designing it."""
        try:
            views = await engine.async_views()
        except ViewsConfigError as err:
            raise web.HTTPInternalServerError(text=str(err)) from err
        view = next((view for view in views if view.name == name), None)
        if view is None:
            raise web.HTTPNotFound(text=f"Unknown view: {name}")
        try:
            return await engine.async_render_view(view)
        except (OSError, TemplateError, ValueError, RuntimeError) as err:
            raise web.HTTPInternalServerError(text=f"{name}: {err}") from err
