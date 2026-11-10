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
]

# Friendly mappings are limited to values established by the model-29 menu.
# Menu-derived options can override these at runtime when available.
VALUE_MAPS: dict[str, dict[str, str]] = {
    "workMode": {
        "1": "On Grid",
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
    "timePeriod1StopChargingEnergySource": {
        "0": "None",
        "1": "Grid charging",
    },
    "timePeriod2StopChargingEnergySource": {
        "0": "None",
        "1": "Grid charging",
    },
    "timePeriod3StopChargingEnergySource": {
        "0": "None",
        "1": "Grid charging",
    },
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
