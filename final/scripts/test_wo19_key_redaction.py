"""
WO-19 offline test: the Sharadar key never reaches stdout/stderr/exception text,
and a successful (mocked) response parses exactly as before.

    python final/scripts/test_wo19_key_redaction.py                    # scripts in this checkout
    python final/scripts/test_wo19_key_redaction.py --root /tmp/before  # flat dir of old copies
    python final/scripts/test_wo19_key_redaction.py --compare /tmp/before  # success parity old vs new

No network: requests.get is replaced and socket.connect raises. A fake key
(FAKEKEY123) is forced into SHARADAR_API_KEY before any target is imported, so
the real key in the calling shell is never read, printed, or sent. main() of
the target scripts is never called (sf1_eps_live_pull's MAIN points at the live
checkout); only the fetch/get functions are exercised.
Exit 0 = pass, 1 = fail.
"""
import argparse
import contextlib
import importlib.util
import io
import os
import pickle
import socket
import sys
import time
import traceback
from pathlib import Path

FAKE = "FAKEKEY123"
os.environ["SHARADAR_API_KEY"] = FAKE  # before any target import; never unset
os.environ.pop("SHARADAR_PANEL_DIR", None)


def _no_net(*a, **k):
    raise OSError("WO-19 test: network disabled")


socket.socket.connect = _no_net
socket.create_connection = _no_net

import requests  # noqa: E402

FINAL = Path(__file__).resolve().parents[1]
# module name -> path relative to final/
TARGETS = {
    "sharadar_pull_pit_panel": "src/sharadar_pull_pit_panel.py",
    "sharadar_pull_fundamentals": "src/sharadar_pull_fundamentals.py",
    "sharadar_splits_pull": "scripts/sharadar_splits_pull.py",
    "sharadar_data_pull": "scripts/sharadar_data_pull.py",
    "sharadar_universe_probe": "src/sharadar_universe_probe.py",
    "sharadar_universe_probe2": "src/sharadar_universe_probe2.py",
    "sharadar_universe_probe3": "src/sharadar_universe_probe3.py",
    "sharadar_pull_shares": "src/sharadar_pull_shares.py",
    "diagnose_marketcap_units": "src/diagnose_marketcap_units.py",
    "sharadar_build_identity_map": "src/sharadar_build_identity_map.py",
    "sharadar_downcap_pull": "scripts/sharadar_downcap_pull.py",
    "sf1_topup": "src/reset2026/sf1_topup.py",
    "sf1_eps_live_pull": "src/sue/sf1_eps_live_pull.py",
}


def load(name, root, flat, tag):
    path = Path(root) / (name + ".py" if flat else TARGETS[name])
    spec = importlib.util.spec_from_file_location(f"wo19_{tag}_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -------- mocks --------
def _path_url(url, params):
    return requests.Request("GET", url, params=params).prepare().path_url


def failing_get(url, params=None, **kw):
    path = _path_url(url, params)
    raise requests.ConnectionError(
        "HTTPSConnectionPool(host='api.sharadar.com', port=443): Max retries exceeded "
        f"with url: {path} (Caused by NameResolutionError(\"Failed to resolve "
        "'api.sharadar.com'\"))")


COLS = ["ticker", "dimension", "date", "reportperiod", "calendardate", "eps",
        "lastupdated", "marketcap", "close", "action", "value"]
ROWS = [[f"T{i:02d}", "ARQ", f"2026-0{1 + i % 9}-1{i % 9}", "2026-06-30", "2026-06-30",
         f"{0.1 * i:.2f}", "2026-09-20", str(1000 + i), f"{10 + i}.5", "split", "2"]
        for i in range(8)]


class OkResp:
    status_code = 200

    def __init__(self, text):
        self.text = text


def ok_get(url, params=None, **kw):
    p = dict(params or {})
    assert p.get("api_key") == FAKE
    off, lim = int(p.get("offset", 0)), p.get("limit")
    sel = ROWS[off: off + int(lim)] if lim is not None else ROWS
    return OkResp(",".join(COLS) + "\n" + "".join(",".join(r) + "\n" for r in sel))


# -------- calls exercised per module (fail + success use the same calls) --------
def calls(m):
    n = m.__name__.split("_", 2)[2]
    return {
        "sharadar_pull_pit_panel": lambda: m.pull_month("daily", "2026-08"),
        "sharadar_pull_fundamentals": lambda: m.get({"dimension": "ARQ", "limit": 3, "offset": 0}),
        "sharadar_splits_pull": lambda: m.fetch_table("actions", "AAPL"),
        "sharadar_data_pull": lambda: m.fetch_table("sep", "AAPL"),
        "sharadar_universe_probe": lambda: m.get("tickers", {"table": "SEP"}),
        "sharadar_universe_probe2": lambda: m.get("tickers", {"table": "SEP"}),
        "sharadar_universe_probe3": lambda: (lambda r: (r[0].text if r[0] is not None else None, r[1]))(
            m.raw("tickers", {"table": "SEP"})),
        "sharadar_pull_shares": lambda: m.get({"dimension": "ARQ"}),
        "diagnose_marketcap_units": lambda: m.get("daily", {"date": "2015-06-30"}),
        "sharadar_build_identity_map": lambda: m.get_all("tickers", {"table": "SEP"}),
        "sharadar_downcap_pull": lambda: m.fetch("sep", {"ticker": "AAPL"}, FAKE),
        "sf1_topup": lambda: m.Puller(m.api_key()).pull("ARQ", {"lastupdated.gte": "2026-09-01"}),
        "sf1_eps_live_pull": lambda: m.pull(FAKE, "2022-09-27"),
    }[n]


def run(fn):
    out, err = io.StringIO(), io.StringIO()
    res, exc_txt = None, ""
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            res = fn()
        except BaseException as e:  # noqa: BLE001
            exc_txt = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    return res, out.getvalue(), err.getvalue(), exc_txt


def setup(mod):
    for attr, v in (("PAGE", 3), ("DELAY", 0), ("RETRIES", 2), ("TRIES", 2)):
        if hasattr(mod, attr):
            setattr(mod, attr, v)
    if hasattr(mod, "API_KEY"):
        mod.API_KEY = FAKE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(FINAL))
    ap.add_argument("--compare", help="flat dir of pre-WO-19 copies for success parity")
    a = ap.parse_args()
    flat = Path(a.root) != FINAL
    time.sleep = lambda s: None
    time.strftime = lambda *x: "00:00:00"

    ok = True
    print(f"[leak test] root={a.root}")
    requests.get = failing_get
    for name in TARGETS:
        mod = load(name, a.root, flat, "fail")
        setup(mod)
        res, out, err, exc = run(calls(mod))
        blob = out + err + exc + repr(res)
        leaked = FAKE in blob
        ok &= not leaked
        what = (exc.strip().splitlines() or [""])[-1] or (out + err).strip().splitlines()[-1:] or res
        print(f"  {'LEAK' if leaked else 'ok  '} {name}: {str(what)[:110].replace(FAKE, '<FAKE>')}")

    if a.compare:
        print(f"[success parity] new={a.root} old={a.compare}")
        requests.get = ok_get
        for name in TARGETS:
            got = []
            for tag, root, fl in (("new", a.root, flat), ("old", a.compare, True)):
                mod = load(name, root, fl, "ok" + tag)
                setup(mod)
                res, out, err, exc = run(calls(mod))
                got.append((pickle.dumps(res, protocol=4), out, err, exc))
            same = got[0] == got[1] and not got[0][3]
            ok &= same
            print(f"  {'same' if same else 'DIFF'} {name}: {len(got[0][0])} pickled bytes"
                  + (f"  exc={got[0][3].strip().splitlines()[-1][:80]}" if got[0][3] else ""))

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
