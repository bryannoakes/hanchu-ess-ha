"""Unit tests for pure entity logic (no live API, no hass instance required).

Importing the platform modules requires the `homeassistant` package, so the whole
module skips if it is unavailable.
"""
from datetime import time as dt_time
import math
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.hanchuess import time as time_mod
from custom_components.hanchuess.const import DEFAULT_FAST_CHARGE_DURATION
from custom_components.hanchuess.battery import (
    extract_battery_serials,
    merge_battery_serials,
)
from custom_components.hanchuess.sensor import (
    SENSORS,
    HanchueSensor,
    _parse_energy_menu,
)
from custom_components.hanchuess.switch import _fast_charge_duration
from custom_components.hanchuess.time import TIME_SLOTS, HanchuessTimeSlot
from custom_components.hanchuess.sensor import (
    BatterySensor,
    BATTERY_SENSORS,
    _battery_temperature_count,
    HanchuessReadOnlySettingSensor,
    HanchuessSettingsLastRefreshSensor,
)


class _FakeEntry:
    def __init__(self, inverter_serial_number="SN1"):
        self.data = {"sn": inverter_serial_number, "stationId": "ST2503268043IE"}


class _FakeBatteryCoordinator:
    def __init__(self, battery_serial_number="B1", data=None):
        self.data = {
            battery_serial_number: data
            or {"tBat1": "23.5", "socPack": "62.9", "vPack": "52.71", "iPack": "-4.14"}
        }


class _FakeOptionsEntry:
    def __init__(self, options=None):
        self.options = options or {}


class _FakeEntryWithStaging:
    """Fake config entry that carries a real SettingsStagingBuffer."""

    def __init__(self, sn="SN1"):
        from custom_components.hanchuess.staging import SettingsStagingBuffer as _SSB
        self.data = {"sn": sn}
        self.runtime_data = MagicMock()
        self.runtime_data.staging = _SSB()
        self.runtime_data.control_registry = {}


def _make_sensor(config, value, unit=None):
    """Build a HanchueSensor backed by a fake coordinator carrying one value.

    When ``unit`` is given it is stored under the config's ``unit_key`` so the
    sibling-unit scaling path can be exercised.
    """
    coordinator = MagicMock()
    data = {config["key"]: value}
    if unit is not None and config.get("unit_key"):
        data[config["unit_key"]] = unit
    coordinator.data = data
    return HanchueSensor(coordinator, _FakeEntry(), "test_sensor", config)


def _make_battery_sensor(key, value="23.5", battery_serial_number="B1"):
    coordinator = _FakeBatteryCoordinator(
        battery_serial_number, {BATTERY_SENSORS[key]["key"]: value}
    )
    return BatterySensor(coordinator, _FakeEntry(), battery_serial_number, key, BATTERY_SENSORS[key])


def _make_battery_temperature_sensor(index, value="23.5", battery_serial_number="B1"):
    sensor_key = f"battery_temperature_{index}"
    config = {
        "key": f"tBat{index}",
        "name": f"Battery Temperature {index}",
        "device_class": "temperature",
        "state_class": "measurement",
        "unit": "degC",
    }
    coordinator = _FakeBatteryCoordinator(
        battery_serial_number, {config["key"]: value}
    )
    return BatterySensor(coordinator, _FakeEntry(), battery_serial_number, sensor_key, config)


def test_extract_battery_serials_reads_bms_list():
    station_detail = {
        "data": {
            "bmsList": [
                {"sn": "B1"},
                {"sn": ""},
                {"sn": "B2"},
                {},
            ]
        }
    }
    assert extract_battery_serials(station_detail) == ["B1", "B2"]


def test_merge_battery_serials_keeps_existing_and_adds_new():
    station_detail = {"data": {"bmsList": [{"sn": "B2"}, {"sn": "B3"}]}}
    assert merge_battery_serials(["B1", "B2"], station_detail) == ["B1", "B2", "B3"]


# ---------------------------------------------------------------------------
# auto_watt scaling
#
# Scaling now trusts the API's per-field `<field>Unit` sibling. The magnitude
# heuristic below is only the fallback for readings that arrive without a unit.
# ---------------------------------------------------------------------------

# --- unit-driven path: scale on the explicit `<field>Unit` field --------------

def test_auto_watt_unit_kw_scaled_to_watts():
    s = _make_sensor(SENSORS["battery_power"], 2.01, unit="kW")
    assert s.native_value == 2010.0


def test_auto_watt_unit_w_left_as_watts():
    s = _make_sensor(SENSORS["battery_power"], 623, unit="W")
    assert s.native_value == 623.0


def test_auto_watt_unit_w_small_value_not_misscaled():
    # P0-06 hazard resolved: with an explicit "W" unit, a genuine 8 W reading
    # stays 8 W instead of being scaled to 8000 W.
    s = _make_sensor(SENSORS["battery_power"], 8, unit="W")
    assert s.native_value == 8.0


def test_auto_watt_unit_kw_fractional_value():
    s = _make_sensor(SENSORS["pv_power"], 0.5, unit="kW")
    assert s.native_value == 500.0


def test_auto_watt_unit_lowercase_kw_scaled():
    s = _make_sensor(SENSORS["grid_power"], 2.0, unit="kw")
    assert s.native_value == 2000.0


# --- fallback path: no unit field, legacy magnitude heuristic -----------------

def test_auto_watt_small_value_scaled_to_watts():
    s = _make_sensor({"key": "batP", "auto_watt": True}, 5)
    assert s.native_value == 5000.0


def test_auto_watt_large_value_unchanged():
    s = _make_sensor({"key": "batP", "auto_watt": True}, 1500)
    assert s.native_value == 1500.0


def test_auto_watt_boundary_ten_treated_as_watts():
    # abs(10) < 10 is False, so 10 is treated as already-watts.
    s = _make_sensor({"key": "batP", "auto_watt": True}, 10)
    assert s.native_value == 10.0


def test_auto_watt_negative_small_value_scaled():
    s = _make_sensor({"key": "batP", "auto_watt": True}, -5)
    assert s.native_value == -5000.0


def test_auto_watt_small_value_misscaled_only_without_unit():
    # The misscale is now confined to the fallback path: a small reading that
    # arrives WITHOUT a unit field is still assumed to be kW (8 -> 8000 W).
    # Compare test_auto_watt_unit_w_small_value_not_misscaled.
    s = _make_sensor({"key": "batP", "auto_watt": True}, 8)
    assert s.native_value == 8000.0


def test_load_power_uses_combined_eps_load_with_explicit_unit():
    # HESS-HY-S-12K-S can report loadPwr=0 while loadEpsPwr carries the actual
    # backed-house load. Use loadEpsPwr and its explicit unit so the live power
    # balance matches battery + grid input.
    s = _make_sensor(SENSORS["load_power"], 903.3, unit="W")
    assert s.native_value == 903.3


def test_load_power_falls_back_to_load_pwr_when_eps_field_absent():
    # Responses without loadEpsPwr (other models/firmware) keep the raw watts field.
    coordinator = MagicMock()
    coordinator.data = {"loadPwr": 687.3}
    s = HanchueSensor(coordinator, _FakeEntry(), "load_power", SENSORS["load_power"])
    assert s.native_value == 687.3


def test_load_power_prefers_eps_field_over_zero_load_pwr():
    coordinator = MagicMock()
    coordinator.data = {"loadPwr": 0.0, "loadEpsPwr": 2.02, "loadEpsPwrUnit": "kW"}
    s = HanchueSensor(coordinator, _FakeEntry(), "load_power", SENSORS["load_power"])
    assert s.native_value == 2020.0


def test_load_power_never_hides_a_load_behind_a_zero_eps_field():
    # If loadEpsPwr reads 0 but loadPwr reports a load, show the load.
    coordinator = MagicMock()
    coordinator.data = {"loadPwr": 450.0, "loadEpsPwr": 0.0, "loadEpsPwrUnit": "kW"}
    s = HanchueSensor(coordinator, _FakeEntry(), "load_power", SENSORS["load_power"])
    assert s.native_value == 450.0


def test_load_power_both_zero_reads_zero():
    coordinator = MagicMock()
    coordinator.data = {"loadPwr": 0.0, "loadEpsPwr": 0.0, "loadEpsPwrUnit": "kW"}
    s = HanchueSensor(coordinator, _FakeEntry(), "load_power", SENSORS["load_power"])
    assert s.native_value == 0


def test_auto_watt_non_numeric_returns_none():
    s = _make_sensor({"key": "batP", "auto_watt": True}, "not-a-number")
    assert s.native_value is None


def test_battery_charge_power_uses_positive_side():
    s = _make_sensor(SENSORS["battery_charge_power"], 1.2, unit="kW")
    assert s.native_value == 1200.0


def test_battery_charge_power_negative_side_is_zero():
    s = _make_sensor(SENSORS["battery_charge_power"], -1.2, unit="kW")
    assert s.native_value == 0.0


def test_battery_discharge_power_negative_side_becomes_positive():
    s = _make_sensor(SENSORS["battery_discharge_power"], -1.2, unit="kW")
    assert s.native_value == 1200.0


def test_battery_discharge_power_positive_side_is_zero():
    s = _make_sensor(SENSORS["battery_discharge_power"], 1.2, unit="kW")
    assert s.native_value == 0.0


def test_grid_import_power_uses_positive_side():
    s = _make_sensor(SENSORS["grid_import_power"], 800, unit="W")
    assert s.native_value == 800.0


def test_grid_export_power_negative_side_becomes_positive():
    s = _make_sensor(SENSORS["grid_export_power"], -800, unit="W")
    assert s.native_value == 800.0


def test_derived_directional_power_zero_stays_zero():
    s = _make_sensor(SENSORS["grid_import_power"], 0, unit="W")
    assert s.native_value == 0.0
    assert math.copysign(1.0, s.native_value) == 1.0
    s = _make_sensor(SENSORS["grid_export_power"], 0, unit="W")
    assert s.native_value == 0.0
    assert math.copysign(1.0, s.native_value) == 1.0


def test_derived_directional_power_negative_zero_is_canonical_zero():
    s = _make_sensor(SENSORS["grid_import_power"], -0.0, unit="W")
    assert s.native_value == 0.0
    assert math.copysign(1.0, s.native_value) == 1.0
    s = _make_sensor(SENSORS["grid_export_power"], -0.0, unit="W")
    assert s.native_value == 0.0
    assert math.copysign(1.0, s.native_value) == 1.0


def test_auto_watt_missing_value_returns_none():
    coordinator = MagicMock()
    coordinator.data = {}
    s = HanchueSensor(coordinator, _FakeEntry(), "x", {"key": "batP", "auto_watt": True})
    assert s.native_value is None


def test_scale_factor_applied():
    s = _make_sensor({"key": "batSoc", "scale": 100}, 0.55)
    assert s.native_value == 55.0


def test_battery_temperature_sensor_uses_device_data():
    s = _make_battery_temperature_sensor(1, "23.5")
    assert s.native_value == 23.5


def test_battery_soc_sensor_uses_device_data():
    s = _make_battery_sensor("battery_soc_pack", "62.9")
    assert s.native_value == 62.9


def test_battery_voltage_sensor_uses_device_data():
    s = _make_battery_sensor("battery_voltage", "52.71")
    assert s.native_value == 52.71


def test_battery_soh_sensor_uses_device_data():
    s = _make_battery_sensor("battery_soh_pack", "100")
    assert s.native_value == 100.0


def test_battery_design_capacity_sensor_uses_device_data():
    s = _make_battery_sensor("battery_design_capacity", "9.40")
    assert s.native_value == 9.4


def test_battery_full_capacity_sensor_uses_device_data():
    s = _make_battery_sensor("battery_full_capacity", "184.00")
    assert s.native_value == 184.0


def test_battery_remaining_capacity_sensor_uses_device_data():
    s = _make_battery_sensor("battery_remaining_capacity", "129.72")
    assert s.native_value == 129.72


def test_battery_temperature_count_uses_num_bat_t():
    assert _battery_temperature_count({"numBatT": 4}) == 4
    assert _battery_temperature_count({"numBatT": "3"}) == 3
    assert _battery_temperature_count({"numBatT": "0"}) == 0


def test_battery_temperature_count_falls_back_to_legacy_default():
    assert _battery_temperature_count({}) == 4
    assert _battery_temperature_count({"numBatT": "bad"}) == 4


# ---------------------------------------------------------------------------
# Fast-charge duration option
#
# The option is stored in minutes; the switch passes seconds to the API.
# ---------------------------------------------------------------------------

def test_fast_charge_duration_defaults_to_60_minutes():
    # No option set -> default 60 minutes -> 3600 seconds.
    assert _fast_charge_duration(_FakeOptionsEntry()) == DEFAULT_FAST_CHARGE_DURATION * 60
    assert _fast_charge_duration(_FakeOptionsEntry()) == 3600


def test_fast_charge_duration_converts_minutes_to_seconds():
    assert _fast_charge_duration(_FakeOptionsEntry({"fast_charge_duration": 45})) == 2700


def test_fast_charge_duration_min_bound():
    # 5 minutes (configured minimum) -> 300 seconds.
    assert _fast_charge_duration(_FakeOptionsEntry({"fast_charge_duration": 5})) == 300


def test_fast_charge_duration_max_bound():
    # 240 minutes (configured maximum, 4 h) -> 14400 seconds.
    assert _fast_charge_duration(_FakeOptionsEntry({"fast_charge_duration": 240})) == 14400


# ---------------------------------------------------------------------------
# _parse_energy_menu
# ---------------------------------------------------------------------------

def test_parse_energy_menu_empty_returns_defaults():
    assert _parse_energy_menu({}) == {"work_mode_options": [], "fields": []}
    assert _parse_energy_menu({"data": {}}) == {"work_mode_options": [], "fields": []}


def test_parse_energy_menu_extracts_work_mode_options():
    menu = {
        "data": {
            "energy": {
                "items": [
                    [
                        {
                            "itemCode": "WORK_MODE_CMB",
                            "itemType": "3",
                            "itemCodeSignal": "WORK_MODE_CMB",
                            "optVal": '[{"name": "Self Use", "value": "1"},'
                                      ' {"name": "Backup", "value": "2"}]',
                        }
                    ]
                ]
            }
        }
    }
    result = _parse_energy_menu(menu)
    assert result["work_mode_options"] == [
        {"label": "Self Use", "value": "1", "signal": "WORK_MODE_CMB"},
        {"label": "Backup", "value": "2", "signal": "WORK_MODE_CMB"},
    ]


def test_parse_energy_menu_numeric_field_with_step():
    menu = {
        "data": {
            "energy": {
                "items": [
                    [
                        {
                            "itemCode": "CHG_PWR_LMT",
                            "itemType": "1",
                            "itemName": "Charge Power Limit",
                            "minVal": "0",
                            "maxVal": "5000",
                            "defFmt": "0.0",
                        }
                    ]
                ]
            }
        }
    }
    fields = _parse_energy_menu(menu)["fields"]
    assert len(fields) == 1
    field = fields[0]
    assert field["code"] == "CHG_PWR_LMT"
    assert field["min"] == "0"
    assert field["max"] == "5000"
    assert field["step"] == 0.1


def test_parse_energy_menu_bad_work_mode_json_is_tolerated():
    menu = {
        "data": {
            "energy": {
                "items": [
                    [
                        {
                            "itemCode": "WORK_MODE_CMB",
                            "itemType": "3",
                            "itemCodeSignal": "WORK_MODE_CMB",
                            "optVal": "{not-valid-json",
                        }
                    ]
                ]
            }
        }
    }
    # Should not raise; work_mode_options stays empty.
    assert _parse_energy_menu(menu)["work_mode_options"] == []


# ---------------------------------------------------------------------------
# Time-slot seconds-since-midnight encode/decode
# ---------------------------------------------------------------------------

def _make_slot(startup_values, client=None):
    config = TIME_SLOTS["charge_slot_1_start"]  # control_key TCT_START_1
    entry = _FakeEntryWithStaging()
    slot = HanchuessTimeSlot(entry, "charge_slot_1_start", config, startup_values)
    # If a client was supplied by an older test, stash it for reference but
    # it is no longer used by the entity (writes go to staging).
    if client is not None:
        slot._test_client = client
    return slot


def test_time_slot_decodes_seconds_to_time():
    slot = _make_slot({"TCT_START_1": 3661})  # 01:01:01 -> 01:01
    assert slot.native_value == dt_time(1, 1)


def test_time_slot_decodes_string_seconds():
    slot = _make_slot({"TCT_START_1": "9000"})  # 02:30
    assert slot.native_value == dt_time(2, 30)


def test_time_slot_invalid_value_falls_back_to_midnight():
    slot = _make_slot({"TCT_START_1": "garbage"})
    assert slot.native_value == dt_time(0, 0)


def test_time_slot_missing_value_defaults_to_midnight():
    slot = _make_slot({})
    assert slot.native_value == dt_time(0, 0)


async def test_time_slot_encodes_time_to_seconds_on_send(monkeypatch):
    monkeypatch.setattr(time_mod, "DEBOUNCE_SECONDS", 0)
    slot = _make_slot({})
    slot.hass = MagicMock()
    slot.async_write_ha_state = MagicMock()
    slot._pending_value = dt_time(2, 30)  # 9000 seconds

    await slot._send_after_delay()

    # Under staged writes, value goes into staging buffer, not direct API call.
    assert slot._entry.runtime_data.staging.pending == {"TCT_START_1": 9000}



# ---------------------------------------------------------------------------
# SettingsStagingBuffer
# ---------------------------------------------------------------------------

from custom_components.hanchuess.staging import SettingsStagingBuffer


def test_staging_stage_adds_entry():
    buf = SettingsStagingBuffer()
    buf.stage("CHG_PWR_LMT", 2000)
    assert buf.pending == {"CHG_PWR_LMT": 2000}


def test_staging_stage_updates_existing_entry():
    buf = SettingsStagingBuffer()
    buf.stage("CHG_PWR_LMT", 2000)
    buf.stage("CHG_PWR_LMT", 3000)
    assert buf.pending == {"CHG_PWR_LMT": 3000}


def test_staging_stage_triggers_on_change():
    buf = SettingsStagingBuffer()
    calls = []
    buf.set_on_change(lambda: calls.append(1))
    buf.stage("CHG_PWR_LMT", 2000)
    assert calls == [1]


def test_staging_clear_empties_buffer():
    buf = SettingsStagingBuffer()
    buf.stage("CHG_PWR_LMT", 2000)
    buf.stage("WORK_MODE_CMB", "1")
    buf.clear()
    assert buf.pending == {}


def test_staging_clear_triggers_on_change():
    buf = SettingsStagingBuffer()
    buf.stage("CHG_PWR_LMT", 2000)
    calls = []
    buf.set_on_change(lambda: calls.append(1))
    buf.clear()
    assert calls == [1]


def test_staging_snapshot_returns_copy():
    buf = SettingsStagingBuffer()
    buf.stage("CHG_PWR_LMT", 2000)
    snap = buf.snapshot()
    snap["CHG_PWR_LMT"] = 9999  # mutate copy
    assert buf.pending["CHG_PWR_LMT"] == 2000  # original unchanged


def test_staging_snapshot_contains_all_entries():
    buf = SettingsStagingBuffer()
    buf.stage("A", 1)
    buf.stage("B", 2)
    assert buf.snapshot() == {"A": 1, "B": 2}


def test_staging_count_reflects_pending():
    buf = SettingsStagingBuffer()
    assert buf.count == 0
    buf.stage("A", 1)
    assert buf.count == 1
    buf.stage("B", 2)
    assert buf.count == 2
    buf.clear()
    assert buf.count == 0


def test_staging_no_on_change_does_not_raise():
    """Calling stage/clear without registering on_change must not raise."""
    buf = SettingsStagingBuffer()
    buf.stage("X", 42)
    buf.clear()


# ---------------------------------------------------------------------------
# Task 2 — entity staging: entities call staging.stage(), not async_device_control
# ---------------------------------------------------------------------------

from custom_components.hanchuess.number import HanchuessNumber, NUMBERS, _decode_number_value
from custom_components.hanchuess.select import WorkModeSelect, _decode_work_mode
from custom_components.hanchuess.time import HanchuessTimeSlot as _TimeSlot2, _decode_time_value


def _make_number(control_key="CHG_PWR_LMT", entry=None):
    if entry is None:
        entry = _FakeEntryWithStaging()
    config = next(c for c in NUMBERS.values() if c["control_key"] == control_key)
    number_key = next(k for k, c in NUMBERS.items() if c["control_key"] == control_key)
    return HanchuessNumber(entry, number_key, config, {control_key: {"min": 0, "max": 5000}}, {})


def _make_select(entry=None):
    if entry is None:
        entry = _FakeEntryWithStaging()
    return WorkModeSelect(entry, {})


def _make_time_slot_v2(startup_values=None, entry=None):
    if entry is None:
        entry = _FakeEntryWithStaging()
    config = TIME_SLOTS["charge_slot_1_start"]
    return _TimeSlot2(entry, "charge_slot_1_start", config, startup_values or {})


# -- _decode_number_value --

def test_decode_number_value_float_string():
    assert _decode_number_value("2000") == 2000.0


def test_decode_number_value_int():
    assert _decode_number_value(3000) == 3000.0


def test_decode_number_value_none_returns_none():
    assert _decode_number_value(None) is None


def test_decode_number_value_bad_string_returns_none():
    assert _decode_number_value("bad") is None


# -- _decode_work_mode --

def test_decode_work_mode_known_value():
    assert _decode_work_mode("1") == "Self-consumption"


def test_decode_work_mode_unknown_returns_none():
    assert _decode_work_mode("99") is None


def test_decode_work_mode_none_returns_none():
    assert _decode_work_mode(None) is None


# -- _decode_time_value --

def test_decode_time_value_seconds():
    assert _decode_time_value(3600) == dt_time(1, 0)


def test_decode_time_value_string():
    assert _decode_time_value("9000") == dt_time(2, 30)


def test_decode_time_value_none_returns_midnight():
    assert _decode_time_value(None) == dt_time(0, 0)


def test_decode_time_value_bad_returns_midnight():
    assert _decode_time_value("garbage") == dt_time(0, 0)


# -- HanchuessNumber staging --

async def test_number_stages_value_not_calls_api():
    entry = _FakeEntryWithStaging()
    number = _make_number(entry=entry)
    number.hass = MagicMock()
    number.async_write_ha_state = MagicMock()

    await number.async_set_native_value(2500.0)

    assert entry.runtime_data.staging.pending == {"CHG_PWR_LMT": 2500}
    assert number._attr_native_value == 2500.0


async def test_number_does_not_call_async_device_control():
    entry = _FakeEntryWithStaging()
    number = _make_number(entry=entry)
    number.hass = MagicMock()
    number.async_write_ha_state = MagicMock()
    client = AsyncMock()

    await number.async_set_native_value(1000.0)

    client.async_device_control.assert_not_awaited()


# -- WorkModeSelect staging --

async def test_select_stages_work_mode_not_calls_api():
    entry = _FakeEntryWithStaging()
    sel = _make_select(entry=entry)
    sel.hass = MagicMock()
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option("Backup Energy")

    assert entry.runtime_data.staging.pending == {"WORK_MODE_CMB": "2"}
    assert sel._attr_current_option == "Backup Energy"


async def test_select_unknown_option_does_not_stage():
    entry = _FakeEntryWithStaging()
    sel = _make_select(entry=entry)
    sel.hass = MagicMock()
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option("NonExistent")

    assert entry.runtime_data.staging.pending == {}


# -- HanchuessTimeSlot staging --

async def test_time_slot_stages_value_after_debounce(monkeypatch):
    import custom_components.hanchuess.time as time_mod2
    monkeypatch.setattr(time_mod2, "DEBOUNCE_SECONDS", 0)
    entry = _FakeEntryWithStaging()
    slot = _make_time_slot_v2(entry=entry)
    slot.hass = MagicMock()
    slot.async_write_ha_state = MagicMock()

    slot._pending_value = dt_time(2, 30)  # 9000 seconds
    await slot._send_after_delay()

    assert entry.runtime_data.staging.pending == {"TCT_START_1": 9000}


async def test_time_slot_does_not_call_async_device_control(monkeypatch):
    import custom_components.hanchuess.time as time_mod2
    monkeypatch.setattr(time_mod2, "DEBOUNCE_SECONDS", 0)
    entry = _FakeEntryWithStaging()
    slot = _make_time_slot_v2(entry=entry)
    slot.hass = MagicMock()
    slot.async_write_ha_state = MagicMock()
    client = AsyncMock()

    slot._pending_value = dt_time(1, 0)
    await slot._send_after_delay()

    client.async_device_control.assert_not_awaited()

# ---------------------------------------------------------------------------
# Task 3 — HanchuessSettingsPendingSensor
# ---------------------------------------------------------------------------

from custom_components.hanchuess.sensor import HanchuessSettingsPendingSensor


def _make_pending_sensor(sn="SN1"):
    entry = _FakeEntryWithStaging(sn)
    sensor = HanchuessSettingsPendingSensor(entry)
    # Simulate async_added_to_hass registration inline.
    entry.runtime_data.staging.set_on_change(sensor._on_staging_change)
    sensor.async_write_ha_state = MagicMock()
    return sensor, entry


def test_pending_sensor_initial_value_is_zero():
    sensor, _ = _make_pending_sensor()
    assert sensor.native_value == 0


def test_pending_sensor_reflects_staged_count():
    sensor, entry = _make_pending_sensor()
    entry.runtime_data.staging.stage("CHG_PWR_LMT", 2000)
    assert sensor.native_value == 1
    entry.runtime_data.staging.stage("DSCHG_PWR_LMT", 3000)
    assert sensor.native_value == 2


def test_pending_sensor_on_change_triggers_write_ha_state():
    sensor, entry = _make_pending_sensor()
    entry.runtime_data.staging.stage("CHG_PWR_LMT", 2000)
    sensor.async_write_ha_state.assert_called()


def test_pending_sensor_resets_to_zero_after_clear():
    sensor, entry = _make_pending_sensor()
    entry.runtime_data.staging.stage("CHG_PWR_LMT", 2000)
    entry.runtime_data.staging.clear()
    assert sensor.native_value == 0


def test_pending_sensor_unique_id():
    sensor, _ = _make_pending_sensor("MYSERIAL")
    assert sensor.unique_id == "MYSERIAL_pending_settings_changes"


# ---------------------------------------------------------------------------
# HESS-HY-S-12K-S read-only settings decoder
# ---------------------------------------------------------------------------

from custom_components.hanchuess.settings_12k import decode_setting_value


def test_12k_setting_decodes_hhmm():
    assert decode_setting_value("startChgTime1", "0730") == "07:30"


def test_12k_setting_decodes_zero_hhmm():
    assert decode_setting_value("startDischgTime1", "0000") == "00:00"


def test_12k_setting_decodes_known_mode():
    assert decode_setting_value("batDischgManagement", "2") == "Battery to home load"


def test_12k_setting_decodes_numeric_units():
    assert decode_setting_value("chgSocLmt", "98") == 98
    assert decode_setting_value("timePeriod1MaxChgPwr", "6600") == 6600


def test_12k_setting_decodes_work_mode_options():
    assert decode_setting_value("workMode", "2") == "Limit power to UPS load"


def test_12k_setting_preserves_unknown_enum_value():
    assert decode_setting_value("workMode", "9") == "9"


# ---------------------------------------------------------------------------
# Model-29 settings refresh coordinator wiring
# ---------------------------------------------------------------------------

from custom_components.hanchuess.button import HanchuessReadSettingsButton
from custom_components.hanchuess.settings_12k import SETTING_SENSORS


async def test_12k_read_settings_button_refreshes_settings_coordinator():
    entry = _FakeEntryWithStaging()
    entry.runtime_data.inverter_model = SimpleNamespace(code=29)
    entry.runtime_data.realtime = SimpleNamespace(client=AsyncMock())
    settings = MagicMock()
    settings.async_refresh = AsyncMock()
    settings.last_update_success = True
    settings.data = {"chgSocLmt": "95"}
    entry.runtime_data.settings = settings

    button = HanchuessReadSettingsButton(MagicMock(), entry)
    await button.async_press()

    settings.async_refresh.assert_awaited_once()


def test_12k_setting_sensor_reads_current_coordinator_data():
    coordinator = MagicMock()
    coordinator.data = {"chgSocLmt": "98"}
    entry = _FakeEntryWithStaging()
    sensor = HanchuessReadOnlySettingSensor(
        coordinator,
        entry,
        "chgSocLmt",
        SETTING_SENSORS["chgSocLmt"],
    )

    assert sensor.native_value == 98

    coordinator.data = {"chgSocLmt": "95"}
    assert sensor.native_value == 95


def test_12k_settings_last_refresh_sensor_exposes_coordinator_timestamp():
    from datetime import datetime, timezone

    coordinator = MagicMock()
    coordinator.last_update_success_time = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)
    coordinator.last_update_success = True
    coordinator.last_exception = None
    coordinator.data = {"workMode": "3", "chgSocLmt": "98"}
    entry = _FakeEntryWithStaging()

    sensor = HanchuessSettingsLastRefreshSensor(coordinator, entry)

    assert sensor.native_value == coordinator.last_update_success_time
    assert sensor.extra_state_attributes["key_count"] == 2
    assert sensor.extra_state_attributes["last_update_success"] is True


def test_read_only_setting_sensor_category_is_valid_for_sensors():
    """HA rejects sensor entities with entity_category=config at add time."""
    from homeassistant.const import EntityCategory
    from custom_components.hanchuess.sensor import HanchuessReadOnlySettingSensor

    assert HanchuessReadOnlySettingSensor._attr_entity_category is not EntityCategory.CONFIG


async def test_12k_read_settings_failure_keeps_pending_edits():
    entry = _FakeEntryWithStaging()
    entry.runtime_data.inverter_model = SimpleNamespace(code=29)
    entry.runtime_data.realtime = SimpleNamespace(client=AsyncMock())
    settings = MagicMock()
    settings.async_refresh = AsyncMock()
    settings.last_update_success = False  # cloud read failed
    entry.runtime_data.settings = settings
    entry.runtime_data.staging.stage("chgSocLmt", 90)

    await HanchuessReadSettingsButton(MagicMock(), entry).async_press()

    assert entry.runtime_data.staging.snapshot() == {"chgSocLmt": 90}


async def test_12k_read_settings_success_discards_pending_edits():
    entry = _FakeEntryWithStaging()
    entry.runtime_data.inverter_model = SimpleNamespace(code=29)
    entry.runtime_data.realtime = SimpleNamespace(client=AsyncMock())
    settings = MagicMock()
    settings.async_refresh = AsyncMock()
    settings.last_update_success = True
    settings.data = {"chgSocLmt": "95"}
    entry.runtime_data.settings = settings
    entry.runtime_data.staging.stage("chgSocLmt", 90)

    await HanchuessReadSettingsButton(MagicMock(), entry).async_press()

    assert entry.runtime_data.staging.snapshot() == {}


def test_load_power_fallback_value_is_numeric_when_the_field_is_a_string():
    coordinator = MagicMock()
    coordinator.data = {"loadPwr": "450"}
    s = HanchueSensor(coordinator, _FakeEntry(), "load_power", SENSORS["load_power"])
    assert s.native_value == 450.0


def test_load_power_zero_rule_returns_numeric_for_a_string_legacy_value():
    coordinator = MagicMock()
    coordinator.data = {"loadPwr": "450", "loadEpsPwr": 0.0, "loadEpsPwrUnit": "kW"}
    s = HanchueSensor(coordinator, _FakeEntry(), "load_power", SENSORS["load_power"])
    assert s.native_value == 450.0


def test_load_power_non_numeric_fallback_is_none():
    coordinator = MagicMock()
    coordinator.data = {"loadPwr": "n/a"}
    s = HanchueSensor(coordinator, _FakeEntry(), "load_power", SENSORS["load_power"])
    assert s.native_value is None
