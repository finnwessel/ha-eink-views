"""End-to-end through the real HA template engine, condition helpers and HTTP view."""

import io
import os
import shutil
from pathlib import Path
from unittest.mock import patch

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
from custom_components.eink_views.raster import svg_to_layers

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


# Black square left, red square right, on white.
TWO_COLOURS = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
    '<rect x="0" y="0" width="20" height="20" fill="#000"/>'
    '<rect x="20" y="0" width="20" height="20" fill="#f00"/></svg>'
)


def _inked(png: bytes) -> tuple[bool, bool]:
    """Whether the left and the right square are black in a layer."""
    with Image.open(io.BytesIO(png)) as image:
        return image.getpixel((10, 10)) == 0, image.getpixel((30, 10)) == 0


def test_layers_split_black_and_red():
    layers = svg_to_layers(TWO_COLOURS, 40, 20)
    assert _inked(layers["all"]) == (True, True)
    assert _inked(layers["black"]) == (True, False)
    assert _inked(layers["red"]) == (False, True)


async def test_layer_query(hass, entry, hass_client_no_auth):
    client = await hass_client_no_auth()
    for layer in ("all", "black", "red"):
        response = await client.get(_url(entry, layer=layer))
        assert response.status == 200
        assert response.headers["X-Eink-Layer"] == layer
    assert (await client.get(_url(entry, layer="blue"))).status == 400


async def test_red_layer_comes_from_the_same_render(hass, entry, hass_client_no_auth, tmp_path):
    views = tmp_path / "eink_views" / "views.yaml"
    views.write_text(
        "views:\n"
        "  - name: warn\n    template: abend.svg.j2\n    when:\n"
        "      - condition: state\n        entity_id: plant.monstera\n        state: problem\n"
        "  - name: standard\n"
    )
    client = await hass_client_no_auth()
    black = await client.get(_url(entry, layer="black"))
    hass.states.async_set("plant.monstera", "ok")
    red = await client.get(_url(entry, layer="red"))
    assert black.headers["X-Eink-View"] == red.headers["X-Eink-View"] == "warn"


async def _nested_entry(hass, tmp_path, views_dir: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_VIEWS_DIR: views_dir},
        options={CONF_WIDTH: 40, CONF_HEIGHT: 20, CONF_ACCESS_KEY: KEY},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_displays_share_parent_macros(hass, entry, hass_client_no_auth, tmp_path):
    """eink_views/<name>: shared macros from the parent, the display's own override them."""
    shared = tmp_path / "eink_views" / "_macros.svg.j2"
    shared.write_text(
        '{%- macro box() -%}<rect x="0" y="0" width="20" height="20" fill="#000"/>{%- endmacro -%}'
        '{%- macro dot() -%}<rect x="20" y="0" width="20" height="20" fill="#000"/>{%- endmacro -%}'
    )
    desk = tmp_path / "eink_views" / "desk"
    desk.mkdir()
    (desk / "views.yaml").write_text("views:\n  - name: main\n")
    (desk / "_macros.svg.j2").write_text("{%- macro dot() -%}{%- endmacro -%}")
    (desk / "main.svg.j2").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
        "{{ box() }}{{ dot() }}</svg>"
    )
    desk_entry = await _nested_entry(hass, tmp_path, "eink_views/desk")
    client = await hass_client_no_auth()
    response = await client.get(_url(desk_entry))
    assert response.status == 200, await response.text()
    assert _inked(await response.read()) == (True, False)


async def test_new_nested_dir_gets_examples(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    assert await async_setup_component(hass, "http", {})
    await _nested_entry(hass, tmp_path, "eink_views/desk")
    assert (tmp_path / "eink_views" / "desk" / "views.yaml").exists()


@pytest.mark.parametrize(
    ("views_dir", "ok"),
    [
        ("eink_views/desk", True),
        ("/eink_views/desk/", True),
        ("flat", True),
        ("eink_views/../secrets", False),
        ("a/b/c", False),
        ("..", False),
    ],
)
async def test_config_flow_views_dir(hass, views_dir, ok):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    user_input = {"name": "Desk", "views_dir": views_dir, "width": 800, "height": 480}
    if not ok:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
        assert result["type"] == "form"
        assert result["errors"] == {"views_dir": "invalid_views_dir"}
        return
    with patch("custom_components.eink_views.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_VIEWS_DIR: views_dir.strip("/")}


async def test_reconfigure_moves_entry_to_new_dir(hass, entry, hass_client_no_auth, tmp_path):
    """The XIAO case: same entry and URL, views now under eink_views/hallway."""
    shutil.copytree(tmp_path / "eink_views", tmp_path / "moved" / "hallway")
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"views_dir": "moved/hallway"}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_VIEWS_DIR] == "moved/hallway"
    assert entry.runtime_data.views_dir == tmp_path / "moved" / "hallway"
    client = await hass_client_no_auth()
    assert (await client.get(_url(entry))).status == 200


async def test_forms_serialize_over_http(hass, entry, hass_client):
    """The UI fetches flows over HTTP, which needs schemas HA can serialise."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    response = await client.post("/api/config/config_entries/flow", json={"handler": DOMAIN})
    assert response.status == 200, await response.text()
    assert (await response.json())["step_id"] == "user"
    response = await client.post(
        "/api/config/config_entries/flow",
        json={"handler": DOMAIN, "entry_id": entry.entry_id, "source": "reconfigure"},
    )
    assert response.status == 200, await response.text()
    assert (await response.json())["step_id"] == "reconfigure"
    response = await client.post(
        "/api/config/config_entries/options/flow", json={"handler": entry.entry_id}
    )
    assert response.status == 200, await response.text()
