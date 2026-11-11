"""DataUpdateCoordinator for Hanchuess."""
import asyncio
import logging
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from .api import HanchuessApiClient, ReauthRequired
from .settings_12k import PLATFORM_SETTING_KEYS
from .const import (
    DOMAIN,
    CONF_REALTIME_INTERVAL,
    CONF_STATISTICS_INTERVAL,
    CONF_BATTERY_INTERVAL,
    DEFAULT_REALTIME_INTERVAL,
    DEFAULT_STATISTICS_INTERVAL,
    DEFAULT_BATTERY_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _raise_auth_failed(client: HanchuessApiClient, msg: str):
    """Raise ConfigEntryAuthFailed once, UpdateFailed for the rest."""
    if not client._reauth_triggered:
        client._reauth_triggered = True
        raise ConfigEntryAuthFailed(msg)
    raise UpdateFailed(msg)


async def _try_refresh(client, update_cb, force=False):
    """Try to refresh token. Returns True if refreshed, raises on reauth needed."""
    try:
        new_token = await client.async_refresh_token(force=force)
    except ReauthRequired:
        _raise_auth_failed(client, "Token refresh returned 90076, reauth required")
    if new_token:
        update_cb(new_token)
        return True
    return False


class HanchuessRealtimeCoordinator(DataUpdateCoordinator):
    """Realtime data coordinator (60s)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HanchuessApiClient):
        super().__init__(
            hass,
            _LOGGER,
            name="hanchuess_realtime",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_REALTIME_INTERVAL, DEFAULT_REALTIME_INTERVAL
                )
            ),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict:
        inverter_serial_number = self.entry.data["sn"]
        language = self.hass.config.language or "en"

        # Proactive refresh at 25 days
        if self.client.should_refresh_token():
            await _try_refresh(self.client, self._update_entry_token)

        data = await self.client.async_get_device_status(
            inverter_serial_number, language
        )

        # Reactive refresh on 401
        if data and data.get("_token_expired"):
            refreshed = await _try_refresh(self.client, self._update_entry_token, force=True)
            if refreshed:
                data = await self.client.async_get_device_status(
                    inverter_serial_number, language
                )

        if data and data.get("_token_expired"):
            _raise_auth_failed(self.client, "Token expired and refresh failed")

        if not data:
            raise UpdateFailed("Failed to get device status")
        return data

    def _update_entry_token(self, token: str):
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, "token": token}
            )


class HanchuessStatisticsCoordinator(DataUpdateCoordinator):
    """Statistics data coordinator (5min)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HanchuessApiClient):
        super().__init__(
            hass,
            _LOGGER,
            name="hanchuess_statistics",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_STATISTICS_INTERVAL, DEFAULT_STATISTICS_INTERVAL
                )
            ),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict:
        inverter_serial_number = self.entry.data["sn"]
        language = self.hass.config.language or "en"

        data = await self.client.async_get_device_statistics(
            inverter_serial_number, language
        )

        if data and data.get("_token_expired"):
            refreshed = await _try_refresh(self.client, self._update_entry_token, force=True)
            if refreshed:
                data = await self.client.async_get_device_statistics(
                    inverter_serial_number, language
                )

        if data and data.get("_token_expired"):
            _raise_auth_failed(self.client, "Token expired and refresh failed")

        if not data:
            raise UpdateFailed("Failed to get device statistics")
        return data

    def _update_entry_token(self, token: str):
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, "token": token}
            )


def _same(raw, sent) -> bool:
    """Compare a read-back value with what was sent (strings like '0300', '97')."""
    if raw is None:
        return False
    if isinstance(sent, str):
        return str(raw).strip() == sent
    try:
        if isinstance(sent, float):
            return abs(float(raw) - sent) < 1e-6
        return int(float(raw)) == sent
    except (TypeError, ValueError):
        return False


class HanchuessSettingsCoordinator(TimestampDataUpdateCoordinator):
    """On-demand model-29 settings coordinator.

    Settings are intentionally not polled periodically. They refresh at startup
    and whenever the Read Settings button is pressed.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HanchuessApiClient):
        super().__init__(
            hass,
            _LOGGER,
            name="hanchuess_settings",
            config_entry=entry,
            update_interval=None,
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict:
        inverter_serial_number = self.entry.data["sn"]
        language = self.hass.config.language or "en"

        data = await self.client.async_platform_iot_get(
            inverter_serial_number,
            "2",
            PLATFORM_SETTING_KEYS,
            language=language,
        )
        if not data:
            raise UpdateFailed("Failed to get model-29 settings")
        _LOGGER.info(
            "[HANCHUESS] Model-29 settings refresh returned %d keys: %s",
            len(data),
            data,
        )
        return data


    @property
    def allow_grid_export(self) -> bool:
        """True only when the user opted in to export-capable options."""
        return bool(self.entry.options.get("allow_grid_export", False))

    async def async_write_staged(self, staging) -> dict[str, str]:
        """Write every staged key through the guarded writer, one key at a time.

        Each key is validated, sent, and confirmed by read-back.  Confirmed keys
        leave the staging buffer; failed keys stay staged.  Returns {key: error}.
        """
        from homeassistant.exceptions import HomeAssistantError

        errors: dict[str, str] = {}
        for key, value in staging.snapshot().items():
            try:
                await self.async_write_setting(key, value)
            except HomeAssistantError as err:
                errors[key] = str(err)
            else:
                staging.discard([key])
        return errors

    async def async_write_setting(
        self, key: str, value, *, attempts: int = 6, delay: float = 3.0
    ):
        """Write one allow-listed setting and confirm it by reading it back.

        Raises HomeAssistantError if the write is refused, rejected, or the
        cloud never reports the new value.  Never trusts the write response.
        """
        from homeassistant.exceptions import HomeAssistantError

        from .settings_12k import SettingWriteError, validate_setting_write

        try:
            number = validate_setting_write(
                key, value, allow_export=self.allow_grid_export
            )
        except SettingWriteError as err:
            raise HomeAssistantError(str(err)) from err
        sn = self.entry.data["sn"]
        result = await self.client.async_platform_iot_set(sn, "2", {key: number})
        if not result.get("success"):
            raise HomeAssistantError(
                f"Hanchu rejected {key} write: {result.get('msg', 'unknown error')}"
            )
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(delay)
            read = await self.client.async_platform_iot_get(sn, "2", [key])
            if _same(read.get(key), number):
                self.async_set_updated_data({**(self.data or {}), key: str(number)})
                return number
        raise HomeAssistantError(
            f"{key} write was accepted but read-back did not confirm {number}"
        )


class HanchuessBatteryCoordinator(DataUpdateCoordinator):
    """Battery data coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HanchuessApiClient):
        super().__init__(
            hass,
            _LOGGER,
            name="hanchuess_battery",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_BATTERY_INTERVAL, DEFAULT_BATTERY_INTERVAL
                )
            ),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict:
        battery_serials = self.entry.data.get("battery_serials", [])
        if not battery_serials:
            return {}
        language = self.hass.config.language or "en"

        async def _fetch(serial: str):
            return serial, await self.client.async_get_battery_data(serial, language)

        results = await asyncio.gather(*(_fetch(serial) for serial in battery_serials))
        data = {}
        token_expired = False
        for serial, result in results:
            if result and result.get("_token_expired"):
                token_expired = True
                continue
            if result:
                data[serial] = result.get("data", {})

        if token_expired:
            refreshed = await _try_refresh(self.client, self._update_entry_token, force=True)
            if refreshed:
                return await self._async_update_data()
            _raise_auth_failed(self.client, "Token expired and refresh failed")

        if not data:
            raise UpdateFailed("Failed to get battery data")
        return data

    def _update_entry_token(self, token: str):
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, "token": token}
            )
