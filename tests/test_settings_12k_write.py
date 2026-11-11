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
PLATFORM_IOT_GET = f"{BASE_URL}/gateway/platform/deviceNew/iotGet"
OK = {
    "code": 200, "success": True, "msg": "Success!",
    "data": {"taskId": "T", "failCount": 0, "successCount": 1,
             "responseSemMap": {"chgSocLmt": "1"}},
}


@pytest.mark.parametrize("key", [
    "R173", "", "enPower", "pcsRestart", "passwordRead", "time", "enNpe", "activePwrSet",
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
    entry.options = {}
    client = MagicMock()
    client.async_platform_iot_set = AsyncMock(return_value=set_result)
    client.async_platform_iot_get = AsyncMock(side_effect=reads)
    coord = HanchuessSettingsCoordinator.__new__(HanchuessSettingsCoordinator)
    coord.entry, coord.client, coord.data = entry, client, {"chgSocLmt": "98"}
    coord.async_update_listeners = MagicMock()
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


def _with_refresh(coord, client, refreshed=True):
    from types import SimpleNamespace

    client.async_refresh_token = AsyncMock(return_value="new" if refreshed else None)
    client._reauth_triggered = False
    coord.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_entries=lambda domain: [], async_update_entry=MagicMock()
        )
    )


async def test_write_refreshes_token_once_on_401_and_retries():
    coord, client = _coordinator(
        {"success": False, "msg": "token_expired"}, [{"chgSocLmt": "97"}]
    )
    client.async_platform_iot_set = AsyncMock(
        side_effect=[{"success": False, "msg": "token_expired"}, {"success": True}]
    )
    _with_refresh(coord, client)
    assert await coord.async_write_setting("chgSocLmt", 97, delay=0) == 97
    assert client.async_platform_iot_set.await_count == 2
    client.async_refresh_token.assert_awaited_once_with(force=True)


async def test_write_read_back_refreshes_on_expired_token():
    from custom_components.hanchuess.api import TokenExpired

    coord, client = _coordinator({"success": True}, [TokenExpired(), {"chgSocLmt": "97"}])
    _with_refresh(coord, client)
    assert await coord.async_write_setting("chgSocLmt", 97, delay=0) == 97
    client.async_refresh_token.assert_awaited_once_with(force=True)


async def test_write_fails_cleanly_when_refresh_fails_twice():
    coord, client = _coordinator({"success": False, "msg": "token_expired"}, [])
    _with_refresh(coord, client, refreshed=False)
    client._reauth_triggered = True  # reauth already raised once -> UpdateFailed
    with pytest.raises(HomeAssistantError):
        await coord.async_write_setting("chgSocLmt", 97, delay=0)


async def test_platform_iot_get_raises_token_expired_only_when_asked(hass):
    from custom_components.hanchuess.api import TokenExpired

    client = HanchuessApiClient(hass, BASE_URL, token="t")
    with aioresponses() as m:
        m.post(PLATFORM_IOT_GET, payload={"code": 401, "success": False})
        with pytest.raises(TokenExpired):
            await client.async_platform_iot_get("SN1", "2", ["chgSocLmt"], raise_on_expired=True)
    with aioresponses() as m:
        m.post(PLATFORM_IOT_GET, payload={"code": 401, "success": False})
        assert await client.async_platform_iot_get("SN1", "2", ["chgSocLmt"]) == {}


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
    coord = MagicMock()
    ents = build_entities(entry, coord, ("int", "float", "bool", "enum", "hhmm"))
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


@pytest.mark.parametrize("value,expected", [(2, 2), (3, 3), ("3", 3)])
def test_work_mode_accepts_only_non_export_options(value, expected):
    assert validate_setting_write("workMode", value) == expected


@pytest.mark.parametrize("value", [1, 0, 4, -1, "abc"])
def test_work_mode_refuses_on_grid_and_unknown(value):
    with pytest.raises(SettingWriteError):
        validate_setting_write("workMode", value)


# --- Grid export values are never writable ---------------------------------

@pytest.mark.parametrize("key,value", [("workMode", 1), ("batDischgManagement", 3), ("pvChargingPriority", 2)])
def test_export_values_are_always_refused(key, value):
    with pytest.raises(SettingWriteError, match="grid export"):
        validate_setting_write(key, value)


async def test_coordinator_refuses_export_values_without_sending():
    coord, client = _coordinator({"success": True}, [{"workMode": "1"}])
    with pytest.raises(HomeAssistantError, match="grid export"):
        await coord.async_write_setting("workMode", 1, delay=0)
    client.async_platform_iot_set.assert_not_awaited()


# --- Staged writes (uniform with the generic staging layer) ------------------

def _staged_entity(key, current):
    from types import SimpleNamespace
    from custom_components.hanchuess.settings_12k_entities import build_entities
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    entry = MagicMock()
    entry.data = {"sn": "SN1"}
    entry.runtime_data = SimpleNamespace(staging=SettingsStagingBuffer())
    coord = MagicMock()
    coord.data = {key: current}
    ent = next(e for e in build_entities(entry, coord, ("int", "float", "bool", "enum", "hhmm")) if e._key == key)
    ent.async_write_ha_state = MagicMock()
    return ent, entry.runtime_data.staging, coord


async def test_entity_change_is_staged_not_sent():
    ent, staging, coord = _staged_entity("gridCharging", "0")
    await ent.async_turn_on()
    assert staging.snapshot() == {"gridCharging": 1}
    assert ent.is_on is True and ent.extra_state_attributes["pending_write"] is True
    coord.async_write_setting.assert_not_called()


async def test_entity_returning_to_device_value_unstages():
    ent, staging, _ = _staged_entity("gridCharging", "0")
    await ent.async_turn_on()
    await ent.async_turn_off()
    assert staging.snapshot() == {}
    assert ent.is_on is False


async def test_entity_rejects_invalid_value_at_stage_time():
    ent, staging, _ = _staged_entity("chgSocLmt", "98")
    with pytest.raises(HomeAssistantError):
        await ent.async_set_native_value(10)
    assert staging.snapshot() == {}


async def test_entity_refuses_export_value_at_stage_time():
    ent, staging, _ = _staged_entity("batDischgManagement", "2")
    with pytest.raises(HomeAssistantError, match="grid export"):
        await ent._write(3)
    assert staging.snapshot() == {}


async def test_flush_writes_each_key_and_clears_confirmed_only():
    from custom_components.hanchuess.staging import SettingsStagingBuffer
    from unittest.mock import patch
    coord, client = _coordinator(
        {"success": True}, [{"chgSocLmt": "97"}] + [{"gridCharging": "0"}] * 6
    )
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 97)
    staging.stage("gridCharging", 1)  # read-back never confirms
    with patch("custom_components.hanchuess.coordinator.asyncio.sleep", new=AsyncMock()):
        errors = await coord.async_write_staged(staging)
    assert list(errors) == ["gridCharging"] and "did not confirm" in errors["gridCharging"]
    assert staging.snapshot() == {"gridCharging": 1}
    assert client.async_platform_iot_set.await_count == 2


# --- independent-review regressions -------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "-inf", "nan", "1e999"])
@pytest.mark.parametrize(
    "key", ["chgSocLmt", "workMode", "gridCharging", "timePeriod1StopChargingV"]
)
def test_validator_rejects_non_finite_numbers_cleanly(key, bad):
    with pytest.raises(SettingWriteError):
        validate_setting_write(key, bad)


@pytest.mark.parametrize("bad", ["²²²²", "０３００", "03:0٣"])
def test_validator_rejects_non_ascii_digit_times(bad):
    with pytest.raises(SettingWriteError):
        validate_setting_write("startChgTime1", bad)


@pytest.mark.parametrize(
    ("raw", "sent", "ok"),
    [
        ("97", 97, True),
        ("97.0", 97, True),
        (97, 97, True),
        ("97.9", 97, False),
        ("2.9", 2, False),
        ("nan", 97, False),
        ("inf", 97, False),
        (None, 97, False),
        ("57.5", 57.5, True),
        ("57.4", 57.5, False),
        ("0300", "0300", True),
    ],
)
def test_read_back_comparison_is_exact(raw, sent, ok):
    from custom_components.hanchuess.coordinator import _same

    assert _same(raw, sent) is ok


def test_plan_write_order_puts_disable_first_enable_last():
    from custom_components.hanchuess.settings_12k import plan_write_order

    plan = plan_write_order(
        {
            "timedChargeEnable": 1,
            "startChgTime1": "0300",
            "chgSocLmt": 97,
            "timedDischargeEnable": 0,
            "timePeriod1MaxChgPwr": 4000,
            "timePeriod1StopDischargingSoc": 20,
        }
    )
    keys = [k for k, _ in plan]
    assert keys[0] == "timedDischargeEnable"
    assert keys[-1] == "timedChargeEnable"
    deps = dict(plan)["timedChargeEnable"]
    assert set(deps) == {"startChgTime1", "timePeriod1MaxChgPwr"}  # charge params only


def _fake_device(client, fail=(), initial=None):
    device, order = dict(initial or {}), []

    async def iot_set(sn, dev_type, value):
        ((key, val),) = value.items()
        order.append(key)
        if key not in fail:
            device[key] = val
        return {"success": True}

    async def iot_get(sn, dev_type, keys, **kwargs):
        return {k: str(device[k]) for k in keys if k in device}

    client.async_platform_iot_set = iot_set
    client.async_platform_iot_get = iot_get
    return device, order


async def test_flush_writes_schedule_parameters_before_enabling():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    _, order = _fake_device(client, initial={"timedChargeEnable": "0"})
    staging = SettingsStagingBuffer()
    staging.stage("timedChargeEnable", 1)  # staged first on purpose
    staging.stage("startChgTime1", "0300")
    staging.stage("timedDischargeEnable", 0)
    assert await coord.async_write_staged(staging) == {}
    assert order == ["timedDischargeEnable", "startChgTime1", "timedChargeEnable"]


async def test_flush_does_not_enable_schedule_when_a_parameter_fails():
    from unittest.mock import patch

    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    _, order = _fake_device(client, fail={"startChgTime1"}, initial={"timedChargeEnable": "0"})
    staging = SettingsStagingBuffer()
    staging.stage("startChgTime1", "0300")
    staging.stage("timePeriod1MaxChgPwr", 4000)
    staging.stage("timedChargeEnable", 1)
    with patch("custom_components.hanchuess.coordinator.asyncio.sleep", new=AsyncMock()):
        errors = await coord.async_write_staged(staging)
    assert "timedChargeEnable" not in order
    assert "not written" in errors["timedChargeEnable"]
    assert "did not confirm" in errors["startChgTime1"]
    assert set(staging.snapshot()) == {"startChgTime1", "timedChargeEnable"}


async def test_flush_validates_everything_and_blocks_enable_on_invalid_parameter():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    _, order = _fake_device(client)
    staging = SettingsStagingBuffer()
    staging.stage("timePeriod1StopChargingSoc", 500)  # out of range
    staging.stage("timedChargeEnable", 1)
    errors = await coord.async_write_staged(staging)
    assert order == []
    assert set(errors) == {"timePeriod1StopChargingSoc", "timedChargeEnable"}


async def test_flush_keeps_a_newer_edit_staged_during_the_write():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    device, _ = _fake_device(client)
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 97)
    inner = client.async_platform_iot_set

    async def set_then_user_edits(sn, dev_type, value):
        result = await inner(sn, dev_type, value)
        staging.stage("chgSocLmt", 90)  # user changes it while the write is in flight
        return result

    client.async_platform_iot_set = set_then_user_edits
    assert await coord.async_write_staged(staging) == {}
    assert device["chgSocLmt"] == 97
    assert staging.snapshot() == {"chgSocLmt": 90}


async def test_concurrent_flushes_are_serialised():
    import asyncio

    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    _fake_device(client)
    inner, state = client.async_platform_iot_set, {"now": 0, "max": 0}

    async def tracked(sn, dev_type, value):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0)
        try:
            return await inner(sn, dev_type, value)
        finally:
            state["now"] -= 1

    client.async_platform_iot_set = tracked
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 97)
    staging.stage("gridCharging", 1)
    await asyncio.gather(coord.async_write_staged(staging), coord.async_write_staged(staging))
    assert state["max"] == 1


async def test_second_401_on_write_is_reported_without_a_second_refresh():
    coord, client = _coordinator({"success": False, "msg": "token_expired"}, [])
    client.async_platform_iot_set = AsyncMock(
        return_value={"success": False, "msg": "token_expired"}
    )
    _with_refresh(coord, client)
    with pytest.raises(HomeAssistantError, match="re-authentication"):
        await coord.async_write_setting("chgSocLmt", 97, delay=0)
    assert client.async_platform_iot_set.await_count == 2
    client.async_refresh_token.assert_awaited_once_with(force=True)
    coord.entry.async_start_reauth.assert_called_once()


async def test_second_401_on_read_back_is_an_auth_error_not_a_readback_failure():
    from custom_components.hanchuess.api import TokenExpired

    coord, client = _coordinator({"success": True}, [TokenExpired(), TokenExpired()])
    _with_refresh(coord, client)
    with pytest.raises(HomeAssistantError) as err:
        await coord.async_write_setting("chgSocLmt", 97, delay=0)
    assert "did not confirm" not in str(err.value)
    client.async_refresh_token.assert_awaited_once_with(force=True)
    assert client.async_platform_iot_get.await_count == 2


# --- Round 2 review regressions -------------------------------------------


async def test_flush_disables_an_enabled_schedule_before_changing_its_parameters():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    device, order = _fake_device(client, initial={"timedDischargeEnable": "1"})
    staging = SettingsStagingBuffer()
    staging.stage("startDischgTime1", "1400")
    staging.stage("endDischgTime1", "1700")
    assert await coord.async_write_staged(staging) == {}
    assert order == ["timedDischargeEnable", "startDischgTime1", "endDischgTime1", "timedDischargeEnable"]
    assert device["timedDischargeEnable"] == 1  # re-enabled last
    assert staging.count == 0


async def test_enabled_schedule_stays_disabled_and_reenable_is_staged_when_a_parameter_fails():
    from unittest.mock import patch

    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    device, order = _fake_device(
        client, fail={"endDischgTime1"}, initial={"timedDischargeEnable": "1"}
    )
    staging = SettingsStagingBuffer()
    staging.stage("startDischgTime1", "1400")
    staging.stage("endDischgTime1", "1700")
    with patch("custom_components.hanchuess.coordinator.asyncio.sleep", new=AsyncMock()):
        errors = await coord.async_write_staged(staging)
    assert order == ["timedDischargeEnable", "startDischgTime1", "endDischgTime1"]
    assert device["timedDischargeEnable"] == 0  # never left running on mixed parameters
    assert "schedule left DISABLED" in errors["timedDischargeEnable"]
    assert staging.snapshot() == {"endDischgTime1": "1700", "timedDischargeEnable": 1}


async def test_enabled_schedule_is_untouched_when_its_state_cannot_be_read():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    device, order = _fake_device(client)  # device reports no enable value
    staging = SettingsStagingBuffer()
    staging.stage("startDischgTime1", "1400")
    errors = await coord.async_write_staged(staging)
    assert order == []
    assert "could not read current timedDischargeEnable" in errors["startDischgTime1"]


async def test_flush_sends_nothing_when_any_staged_value_is_invalid():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    _, order = _fake_device(client)
    staging = SettingsStagingBuffer()
    staging.stage("timePeriod1StopChargingSoc", 101)  # invalid
    staging.stage("timePeriod1MaxChgPwr", 6000)
    staging.stage("gridCharging", 1)
    errors = await coord.async_write_staged(staging)
    assert order == []
    assert set(errors) == {"timePeriod1StopChargingSoc", "timePeriod1MaxChgPwr", "gridCharging"}
    assert staging.count == 3


async def test_second_401_during_a_flush_stops_the_flush_and_asks_for_reauth():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    _with_refresh(coord, client)
    client.async_platform_iot_set = AsyncMock(
        return_value={"success": False, "msg": "token_expired"}
    )
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 97)
    staging.stage("gridCharging", 1)
    errors = await coord.async_write_staged(staging)
    assert set(errors) == {"chgSocLmt", "gridCharging"}
    assert "authentication failed" in errors["gridCharging"] or "re-authentication" in errors["gridCharging"]
    assert client.async_platform_iot_set.await_count == 2  # one write, one retry; nothing after
    coord.entry.async_start_reauth.assert_called()
    assert staging.count == 2


async def test_read_settings_waits_for_a_flush_in_progress():
    import asyncio

    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    _fake_device(client)
    gate = asyncio.Event()
    inner = client.async_platform_iot_set

    async def slow_set(sn, dev_type, value):
        await gate.wait()
        return await inner(sn, dev_type, value)

    client.async_platform_iot_set = slow_set
    refreshed = []

    async def fake_refresh():
        refreshed.append(True)
        coord.last_update_success = True
        coord.data = {"chgSocLmt": "97"}

    coord.async_refresh = fake_refresh
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 97)
    flush = asyncio.ensure_future(coord.async_write_staged(staging))
    await asyncio.sleep(0)
    read = asyncio.ensure_future(coord.async_refresh_settings(staging))
    await asyncio.sleep(0.01)
    assert refreshed == []  # the read is held back while the flush is mid-write
    gate.set()
    assert await flush == {}
    assert await read is True
    assert refreshed == [True]


async def test_read_settings_keeps_edits_for_keys_the_response_did_not_contain():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, _ = _coordinator({"success": True}, [])

    async def partial_refresh():
        coord.last_update_success = True
        coord.data = {"chgSocLmt": "98"}  # incomplete response

    coord.async_refresh = partial_refresh
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 90)
    staging.stage("gridCharging", 1)
    assert await coord.async_refresh_settings(staging) is True
    assert staging.snapshot() == {"gridCharging": 1}


async def test_failed_read_settings_keeps_every_edit():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, _ = _coordinator({"success": True}, [])

    async def failed_refresh():
        coord.last_update_success = False

    coord.async_refresh = failed_refresh
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 90)
    assert await coord.async_refresh_settings(staging) is False
    assert staging.snapshot() == {"chgSocLmt": 90}


async def test_clear_staged_waits_for_a_flush():
    import asyncio

    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    _fake_device(client)
    gate = asyncio.Event()
    inner = client.async_platform_iot_set

    async def slow_set(sn, dev_type, value):
        await gate.wait()
        return await inner(sn, dev_type, value)

    client.async_platform_iot_set = slow_set
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 97)
    flush = asyncio.ensure_future(coord.async_write_staged(staging))
    await asyncio.sleep(0)
    clear = asyncio.ensure_future(coord.async_clear_staged(staging))
    await asyncio.sleep(0.01)
    assert not clear.done()
    gate.set()
    await flush
    await clear
    assert staging.count == 0


async def test_failed_flush_raises_a_persistent_notification(monkeypatch):
    from types import SimpleNamespace

    import custom_components.hanchuess as integration
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 97)
    settings = MagicMock()
    settings.async_write_staged = AsyncMock(return_value={"chgSocLmt": "not confirmed"})
    entry = SimpleNamespace(
        data={"sn": "SN1"},
        runtime_data=SimpleNamespace(staging=staging, settings=settings),
    )
    created = MagicMock()
    monkeypatch.setattr(integration.persistent_notification, "async_create", created)

    assert await integration._async_flush_staged_model_29(MagicMock(), entry) is False

    created.assert_called_once()
    args, kwargs = created.call_args
    assert "chgSocLmt" in args[1] and kwargs["notification_id"] == "hanchuess_write_failed_SN1"


# --- Review round 3 regressions -------------------------------------------


async def test_platform_iot_set_is_never_retried_and_reports_an_unknown_outcome(hass):
    client = HanchuessApiClient(hass, BASE_URL, token="t")
    with aioresponses() as m:
        m.post(PLATFORM_IOT_SET, exception=aiohttp.ClientError("lost"))
        result = await client.async_platform_iot_set("SN1", "2", {"chgSocLmt": 97})
        sent = [c for v in m.requests.values() for c in v]
    assert len(sent) == 1
    assert result["success"] is False and result["uncertain"] is True


async def test_uncertain_write_that_did_apply_is_confirmed_by_read_back():
    coord, client = _coordinator(
        {"success": False, "uncertain": True, "msg": "no answer"}, [{"chgSocLmt": "97"}]
    )
    assert await coord.async_write_setting("chgSocLmt", 97, delay=0) == 97
    assert client.async_platform_iot_set.await_count == 1


async def test_uncertain_write_that_did_not_apply_reports_unknown_outcome():
    coord, client = _coordinator(
        {"success": False, "uncertain": True, "msg": "no answer"}, [{"chgSocLmt": "98"}] * 6
    )
    with pytest.raises(HomeAssistantError, match="outcome is unknown"):
        await coord.async_write_setting("chgSocLmt", 97, delay=0)
    assert client.async_platform_iot_set.await_count == 1


async def test_flush_does_not_send_an_enable_changed_while_writing():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    device, order = _fake_device(client, initial={"timedChargeEnable": "0"})
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 97)
    staging.stage("timedChargeEnable", 1)
    inner = coord.async_write_setting

    async def write_and_edit(key, value, **kwargs):
        result = await inner(key, value, **kwargs)
        if key == "chgSocLmt":
            staging.stage("timedChargeEnable", 0)  # the user changes their mind mid-flush
        return result

    coord.async_write_setting = write_and_edit
    errors = await coord.async_write_staged(staging)
    assert "timedChargeEnable" not in order  # the old value 1 was never sent
    assert "changed while writing" in errors["timedChargeEnable"]
    assert staging.snapshot() == {"timedChargeEnable": 0}  # the newer edit is kept


async def test_flush_does_not_send_a_parameter_changed_while_writing_or_enable_the_schedule():
    from custom_components.hanchuess.staging import SettingsStagingBuffer

    coord, client = _coordinator({"success": True}, [])
    device, order = _fake_device(client, initial={"timedChargeEnable": "0"})
    staging = SettingsStagingBuffer()
    staging.stage("chgSocLmt", 97)
    staging.stage("startChgTime1", "0300")
    staging.stage("timedChargeEnable", 1)
    inner = coord.async_write_setting

    async def write_and_edit(key, value, **kwargs):
        result = await inner(key, value, **kwargs)
        if key == "chgSocLmt":
            staging.stage("startChgTime1", "0400")
        return result

    coord.async_write_setting = write_and_edit
    errors = await coord.async_write_staged(staging)
    assert order == ["chgSocLmt"]  # neither the old time nor the enable was sent
    assert "startChgTime1" in errors and "timedChargeEnable" in errors
    assert staging.snapshot() == {"startChgTime1": "0400", "timedChargeEnable": 1}
