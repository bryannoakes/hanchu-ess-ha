"""Model-29 (HESS-HY-S-12K-S) tests driven by sanitised real responses.

The JSON files under ``tests/fixtures/model29/`` were captured read-only from a
real device and then stripped of every identifier (serial number, station id,
links, trace id are placeholders). Values are otherwise as the cloud returned
them, so these tests exercise the code against the real key set and value
formats rather than hand-written dictionaries.
"""
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.hanchuess.coordinator import HanchuessSettingsCoordinator
from custom_components.hanchuess.sensor import SENSORS, HanchueSensor
from custom_components.hanchuess.settings_12k import (
    PLATFORM_SETTING_KEYS,
    WRITABLE_SETTINGS,
    decode_setting_value,
    validate_setting_write,
)
from custom_components.hanchuess.staging import SettingsStagingBuffer

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "model29"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


STATUS = _load("device_status.json")["data"]
STATISTICS = _load("device_statistics.json")["data"]
SETTINGS = _load("settings.json")["data"]


class _Entry:
    entry_id = "entry1"
    data = {"sn": "TEST-SN-0000000001"}
    options = {}


def test_fixtures_contain_placeholder_identifiers_only():
    assert STATUS["sn"] == "TEST-SN-0000000001"
    assert STATUS["stationId"] == "TEST-STATION-1"
    for name in ("device_status.json", "device_statistics.json", "settings.json"):
        text = (FIXTURES / name).read_text(encoding="utf-8")
        assert "@" not in text
        assert "http" not in text.replace("https://example.invalid/", "")
    assert _load("device_status.json")["traceId"] == "test-trace-id"


def test_status_fixture_is_model_29():
    assert str(STATUS["devModel"]) == "29"


def test_settings_fixture_covers_exactly_the_requested_keys():
    assert set(SETTINGS) == set(PLATFORM_SETTING_KEYS)


def test_every_settings_value_decodes():
    assert [k for k, v in SETTINGS.items() if decode_setting_value(k, v) is None] == []


@pytest.mark.parametrize("key", sorted(WRITABLE_SETTINGS))
def test_real_device_values_pass_write_validation(key):
    # The device's own current value must always be a legal value to write back,
    # with the grid-export gate left at its default (closed).
    validate_setting_write(key, SETTINGS[key])


def test_real_device_values_never_include_an_export_option():
    assert SETTINGS["workMode"] != "1"
    assert SETTINGS["batDischgManagement"] != "3"
    assert SETTINGS["pvChargingPriority"] != "2"


def _sensor(name, data):
    coordinator = MagicMock()
    coordinator.data = data
    return HanchueSensor(coordinator, _Entry(), name, SENSORS[name])


def test_load_power_from_real_payload_uses_scaled_eps_value():
    # loadEpsPwr is reported in kW with an explicit unit; the sensor exposes W.
    sensor = _sensor("load_power", STATUS)
    expected = STATUS["loadEpsPwr"] * (1000 if STATUS["loadEpsPwrUnit"].lower() == "kw" else 1)
    assert sensor.native_value == pytest.approx(expected)


@pytest.mark.parametrize("name", sorted(n for n, c in SENSORS.items() if c.get("key") in STATUS))
def test_real_payload_yields_a_value_for_every_sensor_with_data(name):
    assert _sensor(name, STATUS).native_value is not None


def test_statistics_fixture_has_the_daily_energy_fields():
    assert {"load", "batCharge", "batDisCharge", "pv", "gridImport", "gridExport"} <= set(STATISTICS)


async def test_flushing_the_whole_real_settings_set_writes_every_key_in_safe_order():
    entry = _Entry()
    client = MagicMock()
    device, order = {}, []

    async def iot_set(sn, dev_type, value):
        ((key, val),) = value.items()
        order.append(key)
        device[key] = val
        return {"success": True}

    async def iot_get(sn, dev_type, keys, **kwargs):
        return {k: str(device[k]) for k in keys if k in device}

    client.async_platform_iot_set = iot_set
    client.async_platform_iot_get = iot_get
    coord = HanchuessSettingsCoordinator.__new__(HanchuessSettingsCoordinator)
    coord.entry, coord.client, coord.data = entry, client, dict(SETTINGS)
    coord.async_update_listeners = MagicMock()
    coord.async_set_updated_data = MagicMock(side_effect=lambda d: setattr(coord, "data", d))

    staging = SettingsStagingBuffer()
    for key in WRITABLE_SETTINGS:
        staging.stage(key, SETTINGS[key])

    with patch("custom_components.hanchuess.coordinator.asyncio.sleep", new=AsyncMock()):
        errors = await coord.async_write_staged(staging)

    assert errors == {}
    assert staging.count == 0
    assert sorted(order) == sorted(WRITABLE_SETTINGS)
    # Both schedules are Off on the real device, so their (disable) writes go first.
    assert set(order[:2]) == {"timedChargeEnable", "timedDischargeEnable"}
