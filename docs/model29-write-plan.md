# HESS-HY-S-12K-S (model 29) settings writes — plan

Status: **writes remain blocked**. Nothing here has been executed against a live inverter.

## Evidence so far (read-only)
- The native iESS web app (public JS bundle) writes with `POST /gateway/platform/deviceNew/iotSet`
  (single) and `/deviceNew/iotSets` (batch), as it reads with `/deviceNew/iotGet`.
- Observed native call shape: `{devType: "2", sn, skipCheckLock: true?, value: {<SIGNAL>: "<string>"}}`
  (e.g. `value: {DTU_RESTART: "9"}`). Whether `value` keys for settings are the iotGet keys
  (`chgSocLmt`) or signal names (`R149`) is **not yet proven**.
- `appPlat: ha` and `appPlat: iess` logins both read identical, current values.
- The generic `/app/ha/iotSet` path is not validated for model 29 and stays blocked.

## Captured native write (live, 2026-11-10)
Via the iESS UI (Energy Setup -> Set), `chgSocLmt` 98 -> 97 -> 98, both restored/verified:
- Request: `POST /gateway/platform/deviceNew/iotSet`, encrypted body decoding to
  `{"devType":"2","sn":"<SN>","value":{"chgSocLmt":97}}` — **same key names as iotGet, integer value**,
  and only the changed key was sent (single-key write, even though the UI section has many fields).
- Response: `{"code":200,"msg":"Success!","data":{"taskId":"RCT...","failCount":0,"successCount":1,
  "responseSemMap":{"chgSocLmt":"1"}},"success":true}` — asynchronous task; confirm by read-back.
- iotGet confirmed 98 under both `ha` and `iess` tokens after restore.
- The native read also returns `generatorStartChg` and `generatorMaxChgC` (not in our schema).
- The UI has a settings history ("Record") panel listing every change with operator.

- **`appPlat: ha` token CAN call `deviceNew/iotSet`** (tested with a no-change write of `chgSocLmt`=98 while
  it was already 98): code 200, successCount 1, value unchanged on read-back. No iess login needed.

## Still open (was: open questions)
1. ~~Key naming~~ answered for ints (above); still unknown: HHMM time format and enum encodings.
2. ~~ha token on iotSet~~ answered: allowed.
3. What `skipCheckLock` and the control-permission/lock check do.
4. Response shape and how success is confirmed (read-back via `iotGet`).

## Proposed approach
1. (done) Capture ONE native write of a reversible, non-export setting (`chgSocLmt` 98->97->98) using the
   user's own iESS UI with browser network capture; save under `.secrets/captures/`.
2. Add a `tools/probe.py write` subcommand that is dry-run by default and refuses export-related
   keys (batDischgManagement=3, pvChargingPriority=2, anything grid-sell).
3. With explicit user approval, replay that single write via the probe; confirm via `iotGet` read-back
   and HA Read Settings; restore the original value.
4. Only then add a model-29 write adapter: allow-list of safe keys with min/max/options from the
   menu metadata, single-key writes, mandatory read-back, visible failure, no bulk writes.
5. Keep entities read-only until step 4 passes; expose writable ones one concept at a time.

## Safety rules
Never write export/grid-sell options. One concept per write, capture original, restore after.

## Status (2026-11-10)
Implemented: allow-listed `chgSocLmt` write + read-back + Number entity; live-validated through HA
(98->97->98, ~4-6 s to confirm, 49 rejected). Time (HHMM) and enum writes are NOT captured: the iESS UI
only exposes period fields after enabling Timed Charge/Discharge, which changes inverter behaviour, so no
live capture was done. Enum encodings are derivable from menu metadata but unproven; keep refused.

## Update: timed discharge + times (live, 2026-11-10)
- `timedDischargeEnable`: integer 0/1 works (iESS UI sends the same).
- Times: **must be "HHMM" strings** (`"0300"`). Integers (`300`), which the iESS UI sent in my capture, were
  rejected by the device (`responseSemMap` value `2`, HTTP-level `code 100 / 90008 Operation failed`);
  a mixed batch partially succeeds (other keys apply, time keys don't), so always read back.
- Periods can be edited while timed discharge is On or Off; slot fields only appear in the UI when it is On.
- Implemented + live-validated through HA: Timed Discharge Control switch, Discharge Slot 1 Start/End
  Control time entities (set 03:00/04:00, restored to 00:00, switch restored Off).
- Still refused: timed CHARGE (can import from grid), slots 2/3, enums (workMode, batDischgManagement,
  pvChargingPriority, gridCharging), stop SOC/voltage/power per slot.
- Documentation link for the 12K-S: https://oss-cdn.hanchuess.com/backend/document/pcs/HESS-HY-S-12K-S.pdf
  (not downloaded or read).
