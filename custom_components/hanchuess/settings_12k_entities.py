"""Data-driven writable entities for HESS-HY-S-12K-S (model 29).

Everything is generated from settings_12k.WRITABLE_SETTINGS, so the allow-list,
ranges and options exist in exactly one place.  All writes go through
HanchuessSettingsCoordinator.async_write_setting (validate -> iotSet -> read back).
"""
from __future__ import annotations

from datetime import time

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .models import inverter_model_name
from .settings_12k import WRITABLE_SETTINGS, GRID_EXPORT_REFUSED, allowed_options


class _Base(CoordinatorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, coordinator, key: str):
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        spec = WRITABLE_SETTINGS[key]
        self._spec = spec
        self._attr_name = spec["name"]
        self._attr_unique_id = f"{entry.data['sn']}_setting_write_{key}"
        # Slots 2/3 are rarely used: keep them out of the default entity list.
        if spec.get("slot", 1) > 1:
            self._attr_entity_registry_enabled_default = False

    @property
    def device_info(self) -> DeviceInfo:
        sn = self._entry.data["sn"]
        return DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name=f"Hanchuess {sn}",
            manufacturer="Hanchu",
            model=inverter_model_name(self._entry),
        )

    @property
    def _raw(self):
        return (self.coordinator.data or {}).get(self._key)

    async def _write(self, value):
        await self.coordinator.async_write_setting(self._key, value)


class SettingNumber(_Base, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, entry, coordinator, key):
        super().__init__(entry, coordinator, key)
        self._attr_native_min_value = self._spec["min"]
        self._attr_native_max_value = self._spec["max"]
        self._attr_native_step = self._spec["step"]
        self._attr_native_unit_of_measurement = self._spec.get("unit")

    @property
    def native_value(self):
        try:
            return float(self._raw)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self._write(value)


class SettingSwitch(_Base, SwitchEntity):
    @property
    def is_on(self):
        raw = self._raw
        return None if raw is None else str(raw).strip() == "1"

    async def async_turn_on(self, **kwargs) -> None:
        await self._write(1)

    async def async_turn_off(self, **kwargs) -> None:
        await self._write(0)


class SettingSelect(_Base, SelectEntity):
    def __init__(self, entry, coordinator, key):
        super().__init__(entry, coordinator, key)
        # Export-capable options are only offered when the user opted in.
        refused = GRID_EXPORT_REFUSED.get(key, set())
        self._by_label = {
            (f"{n} (grid export)" if v in refused else n): v
            for v, n in allowed_options(key, coordinator.allow_grid_export).items()
        }
        self._attr_options = list(self._by_label)

    @property
    def current_option(self):
        try:
            value = int(float(self._raw))
        except (TypeError, ValueError):
            return None
        for label, v in self._by_label.items():
            if v == value:
                return label
        return None

    async def async_select_option(self, option: str) -> None:
        await self._write(self._by_label[option])


class SettingTime(_Base, TimeEntity):
    @property
    def native_value(self):
        raw = str(self._raw or "").strip()
        if len(raw) != 4 or not raw.isdigit():
            return None
        try:
            return time(int(raw[:2]), int(raw[2:]))
        except ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        await self._write(f"{value.hour:02d}{value.minute:02d}")


_CLASSES = {
    "int": SettingNumber, "float": SettingNumber, "bool": SettingSwitch,
    "enum": SettingSelect, "hhmm": SettingTime,
}


def build_entities(entry, coordinator, kinds: tuple[str, ...]):
    """Entities for the given spec kinds (platform decides which kinds it serves)."""
    return [
        _CLASSES[spec["kind"]](entry, coordinator, key)
        for key, spec in WRITABLE_SETTINGS.items()
        if spec["kind"] in kinds
    ]
