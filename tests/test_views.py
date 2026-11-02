"""End-to-end through the real HA template engine, condition helpers and HTTP view."""

import io
import os
import shutil
from pathlib import Path

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from PIL import Image
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eink_views.const import (
    CONF_ACCESS_KEY,
    CONF_HEIGHT,
    CONF_VIEWS_DIR,
    CONF_WIDTH,
    DOMAIN,
)
from custom_components.eink_views.engine import ViewsConfigError, parse_views

KEY = "test-key"
PREVIEW_STATES = {
    "sensor.living_room_temperature": "19.17",
    "sensor.living_room_humidity": "68.28",
    "plant.monstera": "ok",
    "plant.ficus": "ok",
    "plant.cactus": "ok",
    "plant.basil": "problem",
    "sensor.monstera_soil_moisture": "27",
    "sensor.ficus_soil_moisture": "17",
    "sensor.cactus_soil_moisture": "45",
    "sensor.basil_soil_moisture": "55",
    "number.monstera_min_soil_moisture": "15",
    "number.monstera_max_soil_moisture": "60",
    "number.ficus_min_soil_moisture": "15",
    "number.ficus_max_soil_moisture": "60",
    "number.cactus_min_soil_moisture": "7",
    "number.cactus_max_soil_moisture": "50",
    "number.basil_min_soil_moisture": "7",
    "number.basil_max_soil_moisture": "50",
    "sensor.pollenflug_graeser_region": "2",
    "sensor.pollenflug_birke_region": "1.5",
    "sensor.pollenflug_hasel_region": "3",
    "sensor.pollenflug_beifuss_region": "0",
}


@pytest.fixture
async def entry(hass: HomeAssistant, tmp_path: Path):
    hass.config.config_dir = str(tmp_path)
    await hass.config.async_set_time_zone("Europe/Berlin")
    assert await async_setup_component(hass, "http", {})
    hass.states.async_set("weather.home", "cloudy", {"temperature": 7.8})
    hass.states.async_set("sensor.living_room_temperature", "19.17")
    hass.states.async_set("plant.monstera", "problem")
    # Renders other views (e.g. the private ones) instead of the bundled examples.
    if source := os.environ.get("EINK_PREVIEW_VIEWS"):
        shutil.copytree(source, tmp_path / "eink_views")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_VIEWS_DIR: "eink_views"},
        options={CONF_WIDTH: 800, CONF_HEIGHT: 480, CONF_ACCESS_KEY: KEY},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _url(entry, **query) -> str:
    query = {"key": KEY, **query}
    args = "&".join(f"{name}={value}" for name, value in query.items())
    return f"/api/eink_views/{entry.entry_id}/image.png?{args}"


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        ("2026-11-02 12:00:00+01:00", "standard"),
        ("2026-05-02 12:00:00+02:00", "pollen"),
        ("2026-05-02 22:00:00+02:00", "abend"),
    ],
)
async def test_first_matching_view_wins(hass, entry, hass_client_no_auth, moment, expected):
    client = await hass_client_no_auth()
    with freeze_time(moment):
        response = await client.get(_url(entry))
    assert response.status == 200
    assert response.headers["X-Eink-View"] == expected
    with Image.open(io.BytesIO(await response.read())) as image:
        assert image.size == (800, 480)
        assert image.mode == "1"


@pytest.mark.parametrize("view", ["standard", "pollen", "abend"])
async def test_preview_ignores_conditions(hass, entry, hass_client_no_auth, view):
    client = await hass_client_no_auth()
    response = await client.get(_url(entry, view=view))
    assert response.status == 200, await response.text()
    assert response.headers["X-Eink-View"] == view


async def test_wrong_key_is_forbidden(hass, entry, hass_client_no_auth):
    client = await hass_client_no_auth()
    assert (await client.get(_url(entry, key="nope"))).status == 403
    assert (await client.get(f"/api/eink_views/{entry.entry_id}/image.png")).status == 403
    assert (await client.get(f"/api/eink_views/other/image.png?key={KEY}")).status == 403


async def test_etag_returns_304(hass, entry, hass_client_no_auth):
    client = await hass_client_no_auth()
    with freeze_time("2026-11-02 12:00:00+01:00"):
        first = await client.get(_url(entry))
        second = await client.get(
            _url(entry), headers={"If-None-Match": first.headers["ETag"]}
        )
    assert second.status == 304


async def test_broken_view_falls_through_to_next(hass, entry, hass_client_no_auth, tmp_path):
    (tmp_path / "eink_views" / "standard.svg.j2").write_text("{{ states( }")
    views = tmp_path / "eink_views" / "views.yaml"
    views.write_text(
        "views:\n  - name: standard\n  - name: rest\n    template: pollen.svg.j2\n"
    )
    client = await hass_client_no_auth()
    response = await client.get(_url(entry))
    assert response.status == 200
    assert response.headers["X-Eink-View"] == "rest"


async def test_broken_config_serves_last_good_image(hass, entry, hass_client_no_auth, tmp_path):
    client = await hass_client_no_auth()
    good = await client.get(_url(entry))
    assert good.status == 200
    (tmp_path / "eink_views" / "views.yaml").write_text("views: [")
    response = await client.get(_url(entry))
    assert response.status == 200
    assert response.headers["ETag"] == good.headers["ETag"]


async def test_edited_views_apply_without_reload(hass, entry, hass_client_no_auth, tmp_path):
    views = tmp_path / "eink_views" / "views.yaml"
    views.write_text(
        "views:\n"
        "  - name: warn\n    template: abend.svg.j2\n    when:\n"
        "      - condition: state\n        entity_id: plant.monstera\n        state: problem\n"
        "  - name: standard\n"
    )
    client = await hass_client_no_auth()
    assert (await client.get(_url(entry))).headers["X-Eink-View"] == "warn"
    hass.states.async_set("plant.monstera", "ok")
    assert (await client.get(_url(entry))).headers["X-Eink-View"] == "standard"


@pytest.mark.parametrize("view", ["standard", "pollen", "abend"])
async def test_write_preview(hass, entry, hass_client_no_auth, view):
    """Writes the images to EINK_PREVIEW_DIR when set, for looking at them."""
    target = os.environ.get("EINK_PREVIEW_DIR")
    if not target:
        pytest.skip("EINK_PREVIEW_DIR not set")
    for entity, value in PREVIEW_STATES.items():
        hass.states.async_set(entity, value)
    client = await hass_client_no_auth()
    response = await client.get(_url(entry, view=view))
    Path(target, f"{view}.png").write_bytes(await response.read())


async def test_plant_entities_come_from_its_device(hass, entry, hass_client_no_auth, tmp_path):
    """Moisture sensors named unlike the plant entity are found through the device."""
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", "plant1")}
    )
    for domain, object_id, value in [
        ("plant", "p1", "ok"),
        ("sensor", "plant_p1_soil_moisture", "42"),
        ("number", "plant_p1_min_soil_moisture", "10"),
        ("number", "plant_p1_max_soil_moisture", "60"),
    ]:
        entities.async_get_or_create(
            domain, "test", object_id, suggested_object_id=object_id, device_id=device.id
        )
        hass.states.async_set(f"{domain}.{object_id}", value)
    (tmp_path / "eink_views" / "probe.svg.j2").write_text(
        '{{ svg_open() }}{{ plant(10, 10, "P", "plant.p1") }}</svg>'
    )
    (tmp_path / "eink_views" / "views.yaml").write_text("views:\n  - name: probe\n")
    engine = entry.runtime_data
    view = (await engine.async_views())[0]
    source = await hass.async_add_executor_job(engine._read_template, view)
    svg = Template(source, hass).async_render({"width": 800, "height": 480}, parse_result=False)
    assert ">42%<" in svg


async def test_active_view_sensor(hass, entry):
    state = hass.states.get("sensor.e_ink_active_view") or next(
        s for s in hass.states.async_all("sensor") if s.entity_id.endswith("active_view")
    )
    assert state.state in {"standard", "pollen", "abend"}
    assert state.attributes["views"] == ["abend", "pollen", "standard"]


async def test_existing_files_survive_setup(hass, entry, tmp_path):
    views = tmp_path / "eink_views" / "views.yaml"
    views.write_text("views:\n  - name: standard\n")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert views.read_text() == "views:\n  - name: standard\n"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {"views": []},
        {"views": [{"template": "x.svg.j2"}]},
        {"views": [{"name": "a", "template": "../../secrets.yaml"}]},
        {"views": [{"name": "a"}, {"name": "a"}]},
    ],
)
def test_parse_views_rejects(raw):
    with pytest.raises(ViewsConfigError):
        parse_views(raw)
