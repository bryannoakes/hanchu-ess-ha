"""Model-29 (HESS-HY-S-12K-S) guarded write path."""
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.exceptions import HomeAssistantError

from custom_components.hanchuess.api import HanchuessApiClient
from custom_components.hanchuess.const import BASE_URL
from custom_components.hanchuess.coordinator import HanchuessSettingsCoordinator
from custom_components.hanchuess.crypto import _decrypt_payload
from custom_components.hanchuess.settings_12k import (
    SettingWriteError,
    validate_setting_write,
)

@pytest.fixture
def hass():
    return object()


@pytest.fixture(autouse=True)
def _mock_ha_session(monkeypatch):
    monkeypatch.setattr(
        "custom_components.hanchuess.api.async_get_clientsession",
        lambda hass: aiohttp.ClientSession(),
    )


PLATFORM_IOT_SET = f"{BASE_URL}/gateway/platform/deviceNew/iotSet"
OK = {
    "code": 200, "success": True, "msg": "Success!",
    "data": {"taskId": "T", "failCount": 0, "successCount": 1,
             "responseSemMap": {"chgSocLmt": "1"}},
}


@pytest.mark.parametrize("key", [
    "R173", "workMode", "", "enPower", "pcsRestart", "passwordRead", "time", "enNpe", "activePwrSet",
    "stPLdSped", "reconPLdSped", "BAT_CLE_PWD", "DTU_RESTART", "devType",
])
def test_everything_but_allowlisted_key_is_refused(key):
    with pytest.raises(SettingWriteError):
        validate_setting_write(key, 1)


@pytest.mark.parametrize("value", [49, 101, -1, "abc", None, 97.5])
def test_chg_soc_lmt_rejects_bad_values(value):
    with pytest.raises(SettingWriteError):
        validate_setting_write("chgSocLmt", value)


@pytest.mark.parametrize("value,expected", [(50, 50), ("97", 97), (98.0, 98), (100, 100)])
def test_chg_soc_lmt_accepts_valid_values(value, expected):
    assert validate_setting_write("chgSocLmt", value) == expected


async def test_platform_iot_set_sends_native_payload(hass):
    client = HanchuessApiClient(hass, BASE_URL, token="t")
    with aioresponses() as m:
        m.post(PLATFORM_IOT_SET, payload=OK)
        result = await client.async_platform_iot_set("SN1", "2", {"chgSocLmt": 97})
        (call,) = [c for k, v in m.requests.items() for c in v]
    assert result["success"] is True
    assert _decrypt_payload(call.kwargs["data"]) == {
        "sn": "SN1", "devType": "2", "value": {"chgSocLmt": 97}
    }


async def test_platform_iot_set_partial_failure_is_failure(hass):
    client = HanchuessApiClient(hass, BASE_URL, token="t")
    bad = {**OK, "data": {"failCount": 1, "successCount": 0}}
    with aioresponses() as m:
        m.post(PLATFORM_IOT_SET, payload=bad)
        result = await client.async_platform_iot_set("SN1", "2", {"chgSocLmt": 97})
    assert result["success"] is False


def _coordinator(set_result, reads):
    entry = MagicMock()
    entry.data = {"sn": "SN1"}
    client = MagicMock()
    client.async_platform_iot_set = AsyncMock(return_value=set_result)
    client.async_platform_iot_get = AsyncMock(side_effect=reads)
    coord = HanchuessSettingsCoordinator.__new__(HanchuessSettingsCoordinator)
    coord.entry, coord.client, coord.data = entry, client, {"chgSocLmt": "98"}
    coord.async_set_updated_data = MagicMock(
        side_effect=lambda d: setattr(coord, "data", d)
    )
    return coord, client


async def test_write_confirmed_by_read_back_updates_data():
    coord, client = _coordinator({"success": True}, [{"chgSocLmt": "98"}, {"chgSocLmt": "97"}])
    assert await coord.async_write_setting("chgSocLmt", 97, delay=0) == 97
    assert coord.data["chgSocLmt"] == "97"
    assert client.async_platform_iot_get.await_count == 2


async def test_write_not_confirmed_raises_and_keeps_old_value():
    coord, _ = _coordinator({"success": True}, [{"chgSocLmt": "98"}] * 3)
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await coord.async_write_setting("chgSocLmt", 97, attempts=3, delay=0)
    assert coord.data["chgSocLmt"] == "98"


async def test_rejected_write_raises_without_readback():
    coord, client = _coordinator({"success": False, "msg": "nope"}, [])
    with pytest.raises(HomeAssistantError, match="rejected"):
        await coord.async_write_setting("chgSocLmt", 97, delay=0)
    client.async_platform_iot_get.assert_not_awaited()


async def test_disallowed_key_never_reaches_network():
    coord, client = _coordinator({"success": True}, [])
    with pytest.raises(HomeAssistantError):
        await coord.async_write_setting("batDischgManagement", 3, delay=0)
    client.async_platform_iot_set.assert_not_awaited()


@pytest.mark.parametrize("value,expected", [("03:00", "0300"), ("0400", "0400"), ("2359", "2359")])
def test_hhmm_is_sent_as_string(value, expected):
    sent = validate_setting_write("startDischgTime1", value)
    assert sent == expected and isinstance(sent, str)


@pytest.mark.parametrize("value", ["2400", "0360", "300", "ab:cd", None, ""])
def test_hhmm_rejects_bad_times(value):
    with pytest.raises(SettingWriteError):
        validate_setting_write("endDischgTime1", value)


@pytest.mark.parametrize("value,expected", [(0, 0), (1, 1), ("1", 1)])
def test_timed_discharge_enable_bool(value, expected):
    assert validate_setting_write("timedDischargeEnable", value) == expected


@pytest.mark.parametrize("value", [2, -1, "x", 0.5])
def test_timed_discharge_enable_rejects_non_bool(value):
    with pytest.raises(SettingWriteError):
        validate_setting_write("timedDischargeEnable", value)


async def test_time_write_confirmed_with_string_readback():
    coord, client = _coordinator({"success": True}, [{"startDischgTime1": "0300"}])
    assert await coord.async_write_setting("startDischgTime1", "03:00", delay=0) == "0300"
    assert coord.data["startDischgTime1"] == "0300"
    client.async_platform_iot_set.assert_awaited_once_with("SN1", "2", {"startDischgTime1": "0300"})


@pytest.mark.parametrize("key,value", [
    ("batDischgManagement", 3), ("pvChargingPriority", 2),
    ("batDischgManagement", 4), ("pvChargingPriority", 9), ("batDischgManagement", -1),
])
def test_export_and_invalid_enum_values_refused(key, value):
    with pytest.raises(SettingWriteError):
        validate_setting_write(key, value)


@pytest.mark.parametrize("key,value,expected", [
    ("batDischgManagement", 0, 0),
    ("batDischgManagement", 2, 2), ("pvChargingPriority", 0, 0), ("pvChargingPriority", 1, 1),
    ("timePeriod1StopChargingEnergySource", 3, 3), ("gridCharging", 1, 1),
    ("timedChargeEnable", 0, 0),
])
def test_safe_enum_and_bool_values_accepted(key, value, expected):
    assert validate_setting_write(key, value) == expected


def test_allowed_options_never_include_export():
    from custom_components.hanchuess.settings_12k import allowed_options
    assert allowed_options("workMode") == {2: "Limit power to UPS load", 3: "Limit power to home load"}
    assert 3 not in allowed_options("batDischgManagement")
    assert 2 not in allowed_options("pvChargingPriority")


@pytest.mark.parametrize("key,value,expected", [
    ("timePeriod2StopDischargingV", 45, 45.0), ("timePeriod1StopChargingV", "57.6", 57.6),
    ("timePeriod3MaxChgPwr", 6600, 6600), ("timePeriod2MaxDisChgPwr", 0, 0),
    ("timePeriod1StopChargingSoc", 52, 52), ("generatorMaxChgC", 40, 40.0),
])
def test_slot_numeric_ranges_accept(key, value, expected):
    assert validate_setting_write(key, value) == expected


@pytest.mark.parametrize("key,value", [
    ("timePeriod1StopChargingV", 39.9), ("timePeriod1StopChargingV", 60),
    ("timePeriod1MaxChgPwr", 12001), ("timePeriod1MaxChgPwr", -1),
    ("timePeriod1StopDischargingSoc", 101), ("generatorMaxChgC", 60.5),
    ("startChgTime3", "2460"), ("endDischgTime2", "9"),
])
def test_slot_numeric_ranges_reject(key, value):
    with pytest.raises(SettingWriteError):
        validate_setting_write(key, value)


def test_every_writable_key_exists_in_platform_keys():
    from custom_components.hanchuess.settings_12k import PLATFORM_SETTING_KEYS, WRITABLE_SETTINGS
    extra = {"generatorStartChg", "generatorMaxChgC"}
    assert set(WRITABLE_SETTINGS) - extra <= set(PLATFORM_SETTING_KEYS)


async def test_float_write_confirmed_by_read_back():
    coord, _ = _coordinator({"success": True}, [{"timePeriod1StopChargingV": "57.6"}])
    assert await coord.async_write_setting("timePeriod1StopChargingV", 57.6, delay=0) == 57.6


def test_entities_built_from_allow_list_and_select_hides_export():
    from custom_components.hanchuess.settings_12k import WRITABLE_SETTINGS
    from custom_components.hanchuess.settings_12k_entities import build_entities

    entry = MagicMock()
    entry.data = {"sn": "SN1"}
    ents = build_entities(entry, MagicMock(), ("int", "float", "bool", "enum", "hhmm"))
    assert {e._key for e in ents} == set(WRITABLE_SETTINGS)
    assert len({e.unique_id for e in ents}) == len(ents)
    selects = {e._key: e for e in ents if e._key in ("batDischgManagement", "pvChargingPriority")}
    assert "Battery to grid sell" not in selects["batDischgManagement"].options
    assert "First to grid" not in selects["pvChargingPriority"].options
    slot2 = [e for e in ents if e._spec.get("slot") == 2]
    assert slot2 and all(e.entity_registry_enabled_default is False for e in slot2)


@pytest.mark.parametrize("platform", ["number", "switch", "select", "time", "sensor", "button"])
def test_platform_modules_import(platform):
    """Catches NameError-style wiring mistakes in platform setup code."""
    import importlib
    mod = importlib.import_module(f"custom_components.hanchuess.{platform}")
    assert hasattr(mod, "async_setup_entry")
    if platform in ("number", "switch", "select", "time"):
        assert hasattr(mod, "build_entities")
