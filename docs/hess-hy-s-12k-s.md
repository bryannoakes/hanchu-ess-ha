# HESS-HY-S-12K-S (model 29)

This page explains what the integration does differently for the Hanchu HESS-HY-S-12K-S (cloud `devModel` 29), why,
and what was and was not verified. Every model-specific behaviour is gated on `inverter_model.code == 29`, so other
models take exactly the code paths they took before. The write protocol and the full matrix of writable settings are in
[hess-hy-s-12k-s-writes.md](hess-hy-s-12k-s-writes.md).

**Tested on one installation only**: a single HESS-HY-S-12K-S (single phase, 12 kW, 48 V battery with BMS) on the
Hanchu cloud in November 2026. No other model was tested, so nothing here is claimed for them.

## Why this model needs its own path

The integration reads and writes settings through the generic HA endpoints (`/app/ha/iotGet`, `/app/ha/iotSet`) using
generic keys such as `WORK_MODE_CMB` and `CHG_PWR_LMT`. For model 29:

- `/app/ha/iotGet` answers `code 100 / data 900001` instead of values, so the generic startup read and Read Settings
  returned nothing usable.
- The model's real settings use a different key set (`workMode`, `chgSocLmt`, `timedChargeEnable`,
  `startChgTime1`, `timePeriod1MaxChgPwr`, ...), with different meanings from the generic keys. The generic
  Work Mode, number and time controls would send values the device does not interpret the same way.

The same HA-scoped token does work against the encrypted platform endpoints
`POST /gateway/platform/deviceNew/iotGet` and `.../iotSet` (AES body as in `crypto.py`, `Content-Type: text/plain`,
`version: 1.0`). That is what the model-29 path uses.

## What changes for model 29, and why

| Change | Why |
|---|---|
| Settings are read from `/platform/deviceNew/iotGet` by a dedicated on-demand coordinator (at startup and on **Read Settings**, no polling) | The generic read does not work on this model; settings change rarely and polling would add cloud load. |
| Every setting is exposed as a read-only **diagnostic** sensor, plus a "Settings Last Refresh" sensor | Visibility. `EntityCategory.CONFIG` is rejected by Home Assistant for sensors (this left all of them unavailable), so the diagnostic category is used. |
| A strict allow-list of settings is writable through switch / select / number / time entities (see the write doc) | The generic controls cannot address this model's keys. The allow-list is the single source for entities, validation and tests; anything not on it is refused. |
| The generic Work Mode, number, time and Fast Charge/Discharge entities are not created | Their keys and semantics do not match this model; a write through them would be unverified. |
| `hanchuess.device_control`, the websocket `iot_set` and `fast_charge`, and the fast-charge service are refused for a model-29 target | Defence in depth: hiding the entities is not enough while the services are still callable. The check uses the target entry's model, never the caller-supplied `dev_type`. |
| A 12K-S that was identified once is remembered in the config entry | If a later status response omits `devModel`, the model would look unknown and the generic write paths above would reopen. |
| No schedule poll for the Inverter Status sensor (added in 2.4.0) | That poll reads generic keys through `/app/ha/iotGet`, which does not answer for this model. The sensor still works from the realtime data (charging, discharging, idle); its fast/scheduled states need the generic schedule keys and are not available on model 29. The "schedule poll interval" option is not shown for this model. |
| Staged changes use the same staging buffer and Write Settings button as the other models, but are written one key at a time, each confirmed by reading it back | The cloud answers a write with "task queued" and the device applies it a few seconds later; a batch can partially succeed. Only a read-back shows what the device holds. |
| A schedule that is enabled is disabled before its times or limits change and re-enabled last, only if everything confirmed | The inverter must never run a half-edited schedule (for example a new start time with the old end time). |
| Grid-export option values (Battery to grid sell, First to grid, On Grid) are never offered or written | Export is illegal or restricted in some regions and none of these was tested on hardware. The check is in the validator, not only in the UI. |
| The failure notification uses `persistent_notification.async_create(hass, ...)` | `hass.components` no longer exists in current Home Assistant. |
| API debug logging no longer prints response bodies, and the "unexpected status" error no longer prints the payload (**applies to every model**, not only model 29) | Platform responses can contain account or station data and users paste debug logs into issues. Only the status and the response code are logged. |
| `wkLink` is redacted from diagnostics | The status response carries a link containing the serial number. |

## Settings

`PLATFORM_SETTING_KEYS` and `WRITABLE_SETTINGS` in `settings_12k.py` list the keys: the work mode and the battery, PV and
grid-charging management options, the timed charge/discharge enables, `chgSocLmt`, the generator charging settings and,
for each of the three charge and three discharge periods, start/end time, stop SOC, stop voltage, maximum power and (for
charging) the energy source. Names, ranges and option lists come from the cloud menu metadata (`/app/ha/menu`) and were
checked against live responses. Values without an established meaning are shown raw rather than guessed. Times are
`"HHMM"` strings; numbers arrive as strings and are decoded for display.

## Verification

- Automated: the suite runs against sanitised real device responses (`tests/fixtures/model29`, with placeholder
  identifiers), covering decoding, validation of every writable key, entity states, ordered flushes (validated as a whole, but written key by key, so they can partly succeed) and the
  failure paths (token expiry, a rejected or unconfirmed key, a newer edit staged mid-write, a concurrent Read Settings).
- On hardware, each applicable setting was changed, confirmed by read-back, observed in Home Assistant and restored to
  its original value. See the write doc for what was and was not exercised.

## Not covered

- Any other model.
- `batDischgManagement` 0 (Standby), charge energy source 2 and 3 (generator): no hardware test.
- The bundled Lovelace settings card: it speaks the generic keys and does not work on model 29.
- Staged edits are not kept across a Home Assistant restart (same as the other models).
- The vendor manual is the authority on inverter behaviour:
  <https://oss-cdn.hanchuess.com/backend/document/pcs/HESS-HY-S-12K-S.pdf>. This integration only mirrors what the
  cloud reports.
