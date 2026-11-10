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

## Open questions (need one captured native write)
1. Exact `value` key naming and value encoding (strings vs ints, HHMM time format, enum ints).
2. Whether the ha-flavoured token may call `deviceNew/iotSet` or it is iess-only.
3. What `skipCheckLock` and the control-permission/lock check do.
4. Response shape and how success is confirmed (read-back via `iotGet`).

## Proposed approach
1. Capture ONE native write of a reversible, non-export setting (`chgSocLmt` 98->97->98) using the
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
