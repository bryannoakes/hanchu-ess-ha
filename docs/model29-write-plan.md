# HESS-HY-S-12K-S (model 29): settings write protocol

Reference for how settings are read and written for `devModel` 29, what was verified on hardware and what was not.
Everything model-specific is gated on `inverter_model.code == 29`. No other model was tested.

## Cloud interface

- Read: `POST /gateway/platform/deviceNew/iotGet`. Write: `POST /gateway/platform/deviceNew/iotSet`.
  Both take the AES-encrypted body (see `crypto.py`) with `Content-Type: text/plain` and `version: 1.0`, and work with the
  existing HA-scoped token (`appPlat: ha`). The generic `/app/ha/iotGet` answers code 100 / data 900001 on this model.
- Body: `{"devType": "2", "sn": "<serial>", "value": {"<key>": <value>}}`. Key names are the same as in iotGet.
- Response: `{"code":200,"success":true,"data":{"taskId":"...","failCount":0,"successCount":1,...}}`. This only means the
  task was queued. The device applies it asynchronously (typically 4-6 s), so a read-back is mandatory.
- Value types matter: times must be `"HHMM"` strings (integers are rejected by the device); stop voltages and
  `generatorMaxChgC` are numbers (sent as floats); the rest are integers.
- A multi-key batch can partially succeed, so the integration writes one key at a time.

## Write allow-list

Source of truth: `WRITABLE_SETTINGS` in `settings_12k.py` (ranges and options come from the cloud menu metadata,
`/app/ha/menu`). Entities, validation and tests are all generated from it. Anything not listed is refused
(power on/off, restart, password, Wi-Fi, date/time, N-PE, gradients, P-PF curve).

| Setting (cloud key) | Wire value | Live-tested | Notes |
|---|---|---|---|
| `chgSocLmt` | int 50-100 | yes | |
| `gridCharging` | 0/1 | yes | |
| `timedChargeEnable`, `timedDischargeEnable` | 0/1 | yes | |
| `generatorStartChg` | 0/1 | yes | |
| `generatorMaxChgC` | number 0-60 | yes | |
| `batDischgManagement` | 0, 1, 2 | 2<->1 only; 0 not tested | 3 (grid sell) needs the export option |
| `pvChargingPriority` | 0, 1 | 0<->1 | 2 (first to grid) needs the export option |
| `workMode` | 2, 3 | 3->2->3 | 1 (On Grid) needs the export option |
| charge/discharge slot 1-3 start/end | `"HHMM"` string | all 12 | slot 1 via HA, slots 2-3 via the API |
| `timePeriodN` stop SOC | int 0-100 | all 6 | |
| `timePeriodN` stop voltage | number 40-59.5 | all 6 | |
| `timePeriodN` max charge / discharge power | int 0-12000 | all 6 | |
| `timePeriodNStopChargingEnergySource` | 0 none, 1 grid, 2 generator, 3 grid+generator | 0 and 1 | 2 and 3 not tested |

Slot 2/3 entities are disabled by default in the entity registry. Every live test restored the original value.

## Write semantics

1. Entities validate the value and stage it in the shared `SettingsStagingBuffer` (the same layer the other models
   use). The entity shows the pending value and a `pending_write` attribute; the cloud is not touched yet.
2. Write Settings / `hanchuess.write_settings` calls `HanchuessSettingsCoordinator.async_write_staged` under a lock
   shared with Read Settings and the staging clear, so none of them interleave. The whole snapshot is validated first;
   if any staged value is invalid nothing is sent. A schedule that is currently enabled (read live) is disabled and
   confirmed before any of its parameters change, and re-enabled only after every staged parameter confirmed; if one
   fails it is left disabled and the re-enable is staged. Keys are written in a safe order (`plan_write_order`):
   schedule disables first, then ordinary keys and schedule parameters, then schedule enables last. An enable
   (`timedChargeEnable` / `timedDischargeEnable` = 1) is not written if any staged parameter of that schedule failed.
3. For each key: `iotSet`, then poll `iotGet` (up to 6 x 3 s) until the value matches exactly (`"97.9"` does not confirm
   97). Confirmed keys leave staging unless the user staged a newer value meanwhile. Unconfirmed or rejected keys stay
   staged and a persistent notification lists them.
4. On a 401 the token is refreshed once and the call retried; if the retry is also rejected it is an authentication
   error without a second refresh (reads raise the usual auth failure; writes stop the flush and start reauthentication).
5. Read Settings waits for any flush, re-reads, and on success discards only the staged edits whose key was actually
   returned (and not changed meanwhile). A failed or partial read keeps the rest.
6. The export gate fails closed: only the literal boolean `True` opens it.
7. A 12K-S identified once is remembered (`dev_model` in the config entry), so a status response that omits `devModel`
   cannot make it look like an unknown model and re-open the generic write paths.

## Grid export is an opt-in

`GRID_EXPORT_REFUSED` values (`workMode` 1, `batDischgManagement` 3, `pvChargingPriority` 2) are refused by
`validate_setting_write` and hidden from the selects unless the model-29 option `allow_grid_export` is on (options flow,
default off). The gate is in the validator, not only the UI. With the option on, those choices appear labelled
"(grid export)". No export value was ever written to hardware; that path is covered by unit tests only.

## Load power

Upstream samples for `devModel` 2 and 4 (June 2026) show `loadPwr` (W) equal to `loadEpsPwr` (kW) x 1000. On model 29
(Nov 2026) `loadPwr` is 0 while `loadEpsPwr` carries the load, and PV + grid = load + battery closes. It cannot be told
from the data whether that is model-specific or a later Hanchu change, so the sensor prefers `loadEpsPwr` (with its unit)
and falls back to `loadPwr` when `loadEpsPwr` is absent, and also when it reads zero while `loadPwr` reports a load.

## Not covered

Any other model; export values; `batDischgManagement` 0; energy source 2 and 3; staging across restarts; the bundled
Lovelace settings card (it speaks the generic keys and does not work on model 29).
