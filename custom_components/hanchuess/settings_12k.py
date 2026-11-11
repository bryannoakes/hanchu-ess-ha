"""Read-only HESS-HY-S-12K-S platform settings schema.

The 48 V 12K-S exposes a different settings model from the generic HA iotGet
schema used by older Hanchu inverters.  The keys below come from the model-29
HA menu and were validated against /gateway/platform/deviceNew/iotGet.

Writes are intentionally not implemented here.  The platform values are exposed
read-only until the model-specific write semantics have been verified safely.
"""
from __future__ import annotations

from homeassistant.const import PERCENTAGE, UnitOfElectricPotential, UnitOfPower

MODEL_CODE = 29

PLATFORM_SETTING_KEYS: list[str] = [
    "workMode",
    "gridCharging",
    "batDischgManagement",
    "pvChargingPriority",
    "timedChargeEnable",
    "timedDischargeEnable",
    "chgSocLmt",
    "startChgTime1", "endChgTime1",
    "timePeriod1StopChargingSoc", "timePeriod1StopChargingV",
    "timePeriod1MaxChgPwr", "timePeriod1StopChargingEnergySource",
    "startChgTime2", "endChgTime2",
    "timePeriod2StopChargingSoc", "timePeriod2StopChargingV",
    "timePeriod2MaxChgPwr", "timePeriod2StopChargingEnergySource",
    "startChgTime3", "endChgTime3",
    "timePeriod3StopChargingSoc", "timePeriod3StopChargingV",
    "timePeriod3MaxChgPwr", "timePeriod3StopChargingEnergySource",
    "startDischgTime1", "endDischgTime1",
    "timePeriod1StopDischargingSoc", "timePeriod1StopDischargingV",
    "timePeriod1MaxDisChgPwr",
    "startDischgTime2", "endDischgTime2",
    "timePeriod2StopDischargingSoc", "timePeriod2StopDischargingV",
    "timePeriod2MaxDisChgPwr",
    "startDischgTime3", "endDischgTime3",
    "timePeriod3StopDischargingSoc", "timePeriod3StopDischargingV",
    "timePeriod3MaxDisChgPwr",
    # Returned by the native iESS read; writable via WRITABLE_SETTINGS.
    "generatorStartChg", "generatorMaxChgC",
]

# Friendly mappings are limited to values established by the model-29 menu.
# Menu-derived options can override these at runtime when available.
VALUE_MAPS: dict[str, dict[str, str]] = {
    "workMode": {
        "1": "On Grid",
        "2": "Limit power to UPS load",
        "3": "Limit power to home load",
    },
    "gridCharging": {"0": "Off", "1": "On"},
    "batDischgManagement": {
        "0": "Standby",
        "1": "Battery to UPS load",
        "2": "Battery to home load",
        "3": "Battery to grid sell",
    },
    "pvChargingPriority": {
        "0": "First to Load",
        "1": "First to charging",
        "2": "First to grid",
    },
    "timedChargeEnable": {"0": "Off", "1": "On"},
    "timedDischargeEnable": {"0": "Off", "1": "On"},
}

SETTING_SENSORS: dict[str, dict] = {
    "workMode": {"name": "Hybrid Grid Mode", "icon": "mdi:transmission-tower"},
    "gridCharging": {"name": "Grid Charging", "icon": "mdi:transmission-tower"},
    "batDischgManagement": {"name": "Battery Energy Manage", "icon": "mdi:battery-sync"},
    "pvChargingPriority": {"name": "PV Energy Manage", "icon": "mdi:solar-power"},
    "timedChargeEnable": {"name": "Timed Charge Enabled", "icon": "mdi:battery-clock"},
    "timedDischargeEnable": {"name": "Timed Discharge Enabled", "icon": "mdi:battery-clock-outline"},
    "chgSocLmt": {"name": "Battery SOC Stop Charge", "unit": PERCENTAGE, "icon": "mdi:battery-high"},
}

for slot in (1, 2, 3):
    SETTING_SENSORS.update({
        f"startChgTime{slot}": {
            "name": f"Charge Slot {slot} Start",
            "kind": "hhmm",
            "icon": "mdi:battery-clock",
        },
        f"endChgTime{slot}": {
            "name": f"Charge Slot {slot} End",
            "kind": "hhmm",
            "icon": "mdi:battery-clock",
        },
        f"timePeriod{slot}StopChargingSoc": {
            "name": f"Charge Slot {slot} Stop SOC",
            "unit": PERCENTAGE,
            "icon": "mdi:battery-high",
        },
        f"timePeriod{slot}StopChargingV": {
            "name": f"Charge Slot {slot} Stop Voltage",
            "unit": UnitOfElectricPotential.VOLT,
            "icon": "mdi:sine-wave",
        },
        f"timePeriod{slot}MaxChgPwr": {
            "name": f"Charge Slot {slot} Max Power",
            "unit": UnitOfPower.WATT,
            "icon": "mdi:battery-charging",
        },
        f"timePeriod{slot}StopChargingEnergySource": {
            "name": f"Charge Slot {slot} Energy Source",
            "icon": "mdi:transmission-tower",
        },
        f"startDischgTime{slot}": {
            "name": f"Discharge Slot {slot} Start",
            "kind": "hhmm",
            "icon": "mdi:battery-clock-outline",
        },
        f"endDischgTime{slot}": {
            "name": f"Discharge Slot {slot} End",
            "kind": "hhmm",
            "icon": "mdi:battery-clock-outline",
        },
        f"timePeriod{slot}StopDischargingSoc": {
            "name": f"Discharge Slot {slot} Stop SOC",
            "unit": PERCENTAGE,
            "icon": "mdi:battery-low",
        },
        f"timePeriod{slot}StopDischargingV": {
            "name": f"Discharge Slot {slot} Stop Voltage",
            "unit": UnitOfElectricPotential.VOLT,
            "icon": "mdi:sine-wave",
        },
        f"timePeriod{slot}MaxDisChgPwr": {
            "name": f"Discharge Slot {slot} Max Power",
            "unit": UnitOfPower.WATT,
            "icon": "mdi:battery-arrow-down",
        },
    })


def is_12k_s(entry) -> bool:
    """Return True when the configured inverter is HESS-HY-S-12K-S/model 29."""
    data = getattr(entry, "runtime_data", None)
    model = getattr(data, "inverter_model", None) if data is not None else None
    return getattr(model, "code", None) == MODEL_CODE


def decode_setting_value(key: str, raw, dynamic_options: dict | None = None):
    """Decode one model-29 platform setting into a safe read-only HA state."""
    if raw is None:
        return None

    raw_text = str(raw).strip()
    options = (dynamic_options or {}).get(key) or VALUE_MAPS.get(key)
    if options and raw_text in options:
        return options[raw_text]

    config = SETTING_SENSORS.get(key, {})
    if config.get("kind") == "hhmm":
        digits = raw_text.zfill(4)
        if len(digits) == 4 and digits.isdigit():
            hours = int(digits[:2])
            minutes = int(digits[2:])
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                return f"{hours:02d}:{minutes:02d}"
        return raw_text

    if config.get("unit"):
        try:
            value = float(raw_text)
        except (TypeError, ValueError):
            return raw_text
        return int(value) if value.is_integer() else value

    return raw_text


# ---------------------------------------------------------------------------
# Writes.  Strict allow-list built from the model-29 HA menu metadata
# (/gateway/app/ha/menu: min_val/max_val/optVal) and live iESS captures.
# Anything not listed here (power on/off, restart, password, N-PE, P-PF curve,
# date/time, ...) is refused.  See docs/model29-write-plan.md.
#
# Wire format (captured from the native iESS app and live-validated):
#   POST /platform/deviceNew/iotSet  {"devType":"2","sn":..,"value":{key: v}}
#   bool/int/enum -> JSON integer; voltages -> JSON number; times -> "HHMM" STRING
#   (integer times are rejected by the device).
# ---------------------------------------------------------------------------
GRID_EXPORT_REFUSED: dict[str, set[int]] = {
    # Export is disabled for this installation: never allow these option values.
    "workMode": {1},               # On Grid (allows export)
    "batDischgManagement": {3},    # Battery to grid sell
    "pvChargingPriority": {2},     # First to grid
}

ENUM_OPTIONS: dict[str, dict[int, str]] = {
    "workMode": {1: "On Grid", 2: "Limit power to UPS load", 3: "Limit power to home load"},
    "batDischgManagement": {
        0: "Standby", 1: "Battery to UPS load", 2: "Battery to home load",
        3: "Battery to grid sell",
    },
    "pvChargingPriority": {0: "First to Load", 1: "First to charging", 2: "First to grid"},
}
for _slot in (1, 2, 3):
    ENUM_OPTIONS[f"timePeriod{_slot}StopChargingEnergySource"] = {
        0: "None", 1: "Grid charging", 2: "GEN charging", 3: "Grid GEN charging",
    }

WRITABLE_SETTINGS: dict[str, dict] = {
    "chgSocLmt": {"kind": "int", "min": 50, "max": 100, "step": 1,
                  "name": "Battery SOC Stop Charge Limit", "unit": "%"},
    "gridCharging": {"kind": "bool", "name": "Grid Charging Control"},
    "timedChargeEnable": {"kind": "bool", "name": "Timed Charge Control"},
    "timedDischargeEnable": {"kind": "bool", "name": "Timed Discharge Control"},
    "generatorStartChg": {"kind": "bool", "name": "Generator Charging Control"},
    "generatorMaxChgC": {"kind": "float", "min": 0.0, "max": 60.0, "step": 1,
                               "name": "Generator Max Charging Current Control", "unit": "A"},
    # Hybrid grid mode: option 1 (On Grid, allows export) is refused by GRID_EXPORT_REFUSED.
    "workMode": {"kind": "enum", "name": "Hybrid Grid Mode Control"},
    "batDischgManagement": {"kind": "enum", "name": "Battery Energy Manage Control"},
    "pvChargingPriority": {"kind": "enum", "name": "PV Energy Manage Control"},
}
for _slot in (1, 2, 3):
    for _dir, _label, _soc, _v, _pwr in (
        ("Chg", "Charge", "StopChargingSoc", "StopChargingV", "MaxChgPwr"),
        ("Dischg", "Discharge", "StopDischargingSoc", "StopDischargingV", "MaxDisChgPwr"),
    ):
        _n = f"{_label} Slot {_slot}"
        WRITABLE_SETTINGS.update({
            f"start{_dir}Time{_slot}": {"kind": "hhmm", "name": f"{_n} Start Control", "slot": _slot},
            f"end{_dir}Time{_slot}": {"kind": "hhmm", "name": f"{_n} End Control", "slot": _slot},
            f"timePeriod{_slot}{_soc}": {"kind": "int", "min": 0, "max": 100, "step": 1,
                                         "name": f"{_n} Stop SOC Control", "unit": "%", "slot": _slot},
            f"timePeriod{_slot}{_v}": {"kind": "float", "min": 40.0, "max": 59.5, "step": 0.1,
                                       "name": f"{_n} Stop Voltage Control", "unit": "V", "slot": _slot},
            f"timePeriod{_slot}{_pwr}": {"kind": "int", "min": 0, "max": 12000, "step": 100,
                                         "name": f"{_n} Max Power Control", "unit": "W", "slot": _slot},
        })
    WRITABLE_SETTINGS[f"timePeriod{_slot}StopChargingEnergySource"] = {
        "kind": "enum", "name": f"Charge Slot {_slot} Energy Source Control", "slot": _slot,
    }


def allowed_options(key: str, allow_export: bool = False) -> dict[int, str]:
    """Selectable options for an enum key.

    Options that allow grid export are only included when the user has opted in
    (config-entry option ``allow_grid_export``, default off).
    """
    refused = set() if allow_export else GRID_EXPORT_REFUSED.get(key, set())
    return {v: n for v, n in ENUM_OPTIONS.get(key, {}).items() if v not in refused}


class SettingWriteError(ValueError):
    """Raised when a model-29 setting write is refused before any request."""


def _to_number(key: str, value) -> float:
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SettingWriteError(f"{key}: {value!r} is not a number") from None


def validate_setting_write(key: str, value, allow_export: bool = False):
    """Return the value to send (int, float or "HHMM" str), or raise SettingWriteError.

    Grid-export option values are refused unless ``allow_export`` is True.
    """
    spec = WRITABLE_SETTINGS.get(key)
    if spec is None:
        raise SettingWriteError(f"Writing {key} is not enabled for HESS-HY-S-12K-S")
    kind = spec["kind"]
    if kind == "hhmm":
        text = str(value).strip().replace(":", "")
        if len(text) != 4 or not text.isdigit():
            raise SettingWriteError(f"{key}: {value!r} is not a time (HHMM)")
        if int(text[:2]) > 23 or int(text[2:]) > 59:
            raise SettingWriteError(f"{key}: {value!r} is not a valid time")
        return text
    number = _to_number(key, value)
    if kind == "float":
        if not spec["min"] <= number <= spec["max"]:
            raise SettingWriteError(
                f"{key}: {number} outside allowed range {spec['min']}-{spec['max']}"
            )
        return round(number, 1)
    if number != int(number):
        raise SettingWriteError(f"{key}: {value!r} must be a whole number")
    number = int(number)
    if kind == "bool":
        if number not in (0, 1):
            raise SettingWriteError(f"{key}: must be 0 or 1")
        return number
    if kind == "enum":
        if not allow_export and number in GRID_EXPORT_REFUSED.get(key, set()):
            raise SettingWriteError(
                f"{key}={number} is refused: it allows grid export, which is disabled "
                "(enable \"Allow grid export settings\" in the integration options)"
            )
        if number not in ENUM_OPTIONS.get(key, {}):
            raise SettingWriteError(f"{key}: {number} is not a valid option")
        return number
    if not spec["min"] <= number <= spec["max"]:
        raise SettingWriteError(
            f"{key}: {number} outside allowed range {spec['min']}-{spec['max']}"
        )
    return number
