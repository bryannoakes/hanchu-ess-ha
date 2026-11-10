#!/usr/bin/env python3
"""Read-only Hanchu API probe. Credentials come from .secrets/hanchu.env.

Usage: python tools/probe.py [--plat ha|iess] [--token-from-login] [--out NAME]
Never prints tokens/credentials. Raw responses are saved under .secrets/captures/.
"""
from __future__ import annotations
import argparse, importlib.util, json, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import types
_pkg = types.ModuleType("hcpkg"); _pkg.__path__ = [str(ROOT / "custom_components/hanchuess")]
sys.modules["hcpkg"] = _pkg
import importlib
hcrypto = importlib.import_module("hcpkg.crypto")


def load_env():
    env = {}
    for line in (ROOT / ".secrets/hanchu.env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1); env[k.strip()] = v.strip()
    return env


def post(base, path, body, plat="ha", token=None, encrypted=False):
    h = {"appPlat": plat, "locale": "en"}
    if token: h["access-token"] = token
    if encrypted:
        h["Content-Type"] = "text/plain"; h["version"] = "1.0"
        data = hcrypto._encrypt_payload(body).encode()
    else:
        h["Content-Type"] = "application/json"; data = json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read()[:200].decode(errors="replace")}


KEYS = ["workMode","gridCharging","batDischgManagement","pvChargingPriority","timedChargeEnable",
        "timedDischargeEnable","chgSocLmt","startChgTime1","endChgTime1","timePeriod1MaxChgPwr",
        "timePeriod1StopChargingSoc","startDischgTime1","endDischgTime1","timePeriod1MaxDisChgPwr"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="probe")
    a = ap.parse_args()
    env = load_env(); base = env["HANCHU_BASE_URL"].rstrip("/"); sn = env["HANCHU_SERIAL"]
    st, r = post(base, "/gateway/identify/auth/token", {"account": env["HANCHU_ACCOUNT"], "pwd": env["HANCHU_PASSWORD"]})
    print("login", st, r.get("code"), r.get("success"))
    token = r.get("data") if r.get("success") else None
    if not token: sys.exit(1)
    out = {"ts": time.time()}
    st, r = post(base, "/gateway/app/ha/getDeviceStatus", {"sn": sn}, token=token); out["status"] = r
    print("status", st, r.get("code"))
    st, r = post(base, "/gateway/platform/deviceNew/iotGet", {"sn": sn, "devType": "2", "keys": KEYS}, token=token, encrypted=True)
    out["platform_iotGet_ha"] = r; print("platform iotGet(ha)", st, r.get("code"))
    d = r.get("data")
    if isinstance(d, dict): print({k: d.get(k) for k in KEYS})
    else: print("data:", str(d)[:200])
    cap = ROOT / ".secrets/captures"; cap.mkdir(exist_ok=True)
    (cap / f"{a.out}-{int(time.time())}.json").write_text(json.dumps(out, indent=1))

if __name__=='__main__':
    main()
