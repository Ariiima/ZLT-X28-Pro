#!/usr/bin/env python3
"""ZLT X28 Pro helper: status, backup/restore, network mode, band lock, best-band scan.

  python3 zlt.py status
  python3 zlt.py backup                 # writes zlt_backup.json
  python3 zlt.py restore                # puts zlt_backup.json back
  python3 zlt.py mode 1C                # 1C = 5G SA+NSA/4G, 4 = 4G only, 40 = 4G TDD only
  python3 zlt.py lock 3,1 [n78]         # lock 4G bands (and optional 5G bands); "lock all" unlocks
  python3 zlt.py scan                   # try each visible 4G band, lock the best one (home network only)
  python3 zlt.py operator 43220         # select this network (modem then reports manual mode, see README)
  python3 zlt.py speed                  # domestic + international speed/ping, no changes
  python3 zlt.py scan --cells           # also try a cell lock on each home cell (root login)
  python3 zlt.py cells                  # list nearby LTE cells (all operators)
  python3 zlt.py celllock 325:251 | off # lock LTE to earfcn:pci pairs (root login)

The cell lock needs the root web login: ZLT_USER=root ZLT_PASS=admin.
  python3 zlt.py watch                  # live RSRP/SINR every 2 s, for placing the modem
  python3 zlt.py at 'AT+COPS?'          # send one AT command to the Quectel module
"""
import hashlib, itertools, json, os, random, re, statistics, subprocess, sys, time, urllib.request

HOST = os.environ.get("ZLT_HOST", "192.168.70.1")
USER, PASS = os.environ.get("ZLT_USER", "admin"), os.environ.get("ZLT_PASS", "admin")
IFACE = os.environ.get("ZLT_IFACE", "en0")  # interface to the modem; bypasses a VPN so tests measure the modem link
PING_IR = os.environ.get("ZLT_PING_IR", "217.218.127.127")  # TCI DNS, Tehran
PING_INT = os.environ.get("ZLT_PING", "4.2.2.4")
# Ookla servers in Tehran (plain HTTP download endpoint); Asiatech is operator-neutral.
DL_IR = os.environ.get("ZLT_DL_IR", "http://speedtest.asiatech.com.prod.hosts.ooklaserver.net:8080/download?size=500000000")
# ponytail: Cloudflare returns 403 above ~25 MB, so 4 streams x 25 MB / 10 s caps this test at ~80 Mbps.
DL_INT = os.environ.get("ZLT_DL", "https://speed.cloudflare.com/__down?bytes=25000000")
UL_IR = os.environ.get("ZLT_UL_IR", "http://speedtest.asiatech.com.prod.hosts.ooklaserver.net:8080/upload")
ALLOW_ROAMING = os.environ.get("ZLT_ALLOW_ROAMING") == "1"
REPEAT = int(os.environ.get("ZLT_REPEAT", "2"))  # runs per candidate; median is kept
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zlt_backup.json")
URL = f"http://{HOST}/cgi-bin/http.cgi"
SID = ""

# EARFCN (downlink) ranges for the bands this modem supports.
LTE_BANDS = {1: (0, 599), 3: (1200, 1949), 5: (2400, 2649), 7: (2750, 3449), 8: (3450, 3799),
             20: (6150, 6449), 28: (9210, 9659), 32: (9920, 10359), 38: (37750, 38249),
             40: (38650, 39649), 41: (39650, 41589), 42: (41590, 43589), 43: (43590, 45589)}
PLMN = {"43211": "MCI", "43220": "Rightel", "43235": "Irancell", "43214": "TKC", "43232": "Taliya"}


def call(d, timeout=30, retry=True):
    req = urllib.request.Request(URL, json.dumps({"language": "EN", "sessionId": SID, **d}).encode())
    body = urllib.request.urlopen(req, timeout=timeout).read().decode()
    # ponytail: the modem answers an unchanged band lock with an empty body; treat as success.
    r = json.loads(body) if body.strip() else {"success": True}
    if retry and r.get("message") in ("NO_AUTH", "LOGIN_TIMEOUT") and d.get("cmd") not in (100, 232):
        login()  # sessions expire during long scans
        if "token" in d:
            d = {**d, "token": call({"cmd": 233, "method": "GET"}, retry=False)["token"]}
        return call(d, timeout, retry=False)
    return r


def login():
    global SID
    tok = call({"cmd": 232, "method": "GET", "sessionId": ""})["token"]
    r = call({"cmd": 100, "method": "POST", "username": USER, "isAutoUpgrade": "0", "subcmd": 0,
              "sessionId": hashlib.md5(str(random.random()).encode()).hexdigest() * 2,
              "passwd": hashlib.sha256((tok + PASS).encode()).hexdigest()})
    if not r.get("success"):
        sys.exit(f"login failed: {r}")
    SID = r["sessionId"]


def get(cmd):
    return call({"cmd": cmd, "method": "GET"})


def post(cmd, **kw):
    tok = get(233)["token"]  # the web UI refreshes the token before every write
    r = call({"cmd": cmd, "method": "POST", "token": tok, **kw})
    if not r.get("success"):
        raise RuntimeError(f"cmd {cmd} failed: {r}")
    return r


def mask(bands):
    return format(sum(1 << (b - 1) for b in bands), "x")


def unmask(h):
    v = int(h or "0", 16)
    return [i + 1 for i in range(v.bit_length()) if v >> i & 1]


def band_of(earfcn):
    return next((b for b, (lo, hi) in LTE_BANDS.items() if lo <= earfcn <= hi), None)


def status():
    s = get(205)
    return {"plmn": s.get("PLMN"), "op": PLMN.get(s.get("PLMN"), s.get("network_operator")),
            "type": s.get("network_type_str"), "band": s.get("currentband"), "band5g": s.get("currentband_5g"),
            "pci": s.get("PCI"), "earfcn": s.get("FREQ"), "rsrp": s.get("RSRP"), "sinr": s.get("SINR"),
            "rsrq": s.get("RSRQ"), "cqi": s.get("CQI"), "bw": s.get("bandwidth"),
            "rsrp5g": s.get("RSRP_5G"), "sinr5g": s.get("SINR_5G"), "wan": get(0).get("wanIP")}


def show_status():
    st = status()
    print(json.dumps(st, ensure_ascii=False))
    lb = get(161)
    print("mode:", get(256).get("networkMode"), "| 4G lock:", unmask(lb["lock_band_4g"]) if lb["band_4g_switch"] == "1" else "off",
          "| 5G lock:", ["n%d" % b for b in unmask(lb["lock_band_5g"])] if lb["band_5g_switch"] == "1" else "off")
    print("visible LTE cells (earfcn,pci,rsrp,rsrq):", get(282).get("lte_info"), "| NR:", get(282).get("nr_info"))


def set_mode(m):
    post(256, networkMode=m.upper())


def set_bands(b4=None, b5=None):
    """b4/b5: list of band numbers, or None = no lock."""
    post(161, band4gRadio="1" if b4 else "0", lock4gBand=mask(b4) if b4 else "",
         band5gRadio="1" if b5 else "0", lock5gBand=mask(b5) if b5 else "")


def wait_online(timeout=150):
    t0 = time.time()
    time.sleep(10)
    while time.time() - t0 < timeout:
        try:
            st = status()
            if st["plmn"] and st["plmn"] != "NULL" and st["wan"] and ping(2)[0] is not None:
                return st
        except Exception:
            pass  # modem web server stalls while the radio re-attaches
        time.sleep(5)
    return None


def ping(n=20, host=PING_INT):
    """Returns (avg ms, loss %, jitter ms); jitter = ping stddev."""
    bind = "-b" if sys.platform == "darwin" else "-I"  # bind to the modem interface (macOS / Linux)
    out = subprocess.run(["ping", "-c", str(n), "-i", "0.2", bind, IFACE, host],
                         capture_output=True, text=True).stdout
    m = re.search(r"([\d.]+)% packet loss.*?= [\d.]+/([\d.]+)/[\d.]+/([\d.]+)", out, re.S)
    return (float(m[2]), float(m[1]), float(m[3])) if m else (None, 100.0, None)


def transfer(url, up=False, streams=4, secs=10):
    """Parallel streams for a fixed time, like speedtest.net; returns total Mbps."""
    extra = ["-T", "-", "-X", "POST", "-w", "%{size_upload}"] if up else ["-w", "%{size_download}"]
    ps = [subprocess.Popen(["curl", "-s", "-o", "/dev/null", "--interface", IFACE, "-m", str(secs), *extra, url],
                           stdin=open("/dev/zero", "rb") if up else None, stdout=subprocess.PIPE, text=True)
          for _ in range(streams)]
    total = sum(float(p.communicate()[0] or 0) for p in ps)
    return round(total * 8 / secs / 1e6, 1)


def measure_once():
    ir, loss, jit = ping(host=PING_IR)
    intl, _, _ = ping(host=PING_INT)
    return {"dl_ir": transfer(DL_IR), "ul_ir": transfer(UL_IR, up=True), "dl_int": transfer(DL_INT),
            "ping_ir": ir, "jitter_ir": jit, "ping_int": intl, "loss": loss}


def measure(n=REPEAT):
    """Median of n runs per metric; one run is too noisy (tower load changes by the minute)."""
    runs = [measure_once() for _ in range(n)]
    med = lambda xs: statistics.median(xs) if xs else None
    return {k: med([r[k] for r in runs if r[k] is not None]) for k in runs[0]}


def score(r):
    # ponytail: download + half upload, penalised by domestic ping and jitter; tune weights for gaming.
    if r.get("ping_ir") is None:
        return -1
    speed = (r["dl_ir"] + r["dl_int"]) / 2 + r.get("ul_ir", 0) / 2
    return speed / (1 + (r["ping_ir"] + 2 * (r.get("jitter_ir") or 0)) / 100) * (1 - r["loss"] / 100)


def home_plmn():
    return get(207).get("IMSI", "")[:5]


def set_operator(plmn, act="7"):
    """Web UI 'PLMN select' (sends AT+COPS=4). On firmware 8.5.4.3 the module then reports
    +COPS: 1 (manual), so it does not fall back to roaming. Undo with: at 'AT+COPS=0'."""
    post(228, plmn_select_cmd="4", plmn=plmn, act=act)


def do_backup():
    lb, nm = get(161), get(256)
    json.dump({"networkMode": nm["networkMode"], "lock_band": lb}, open(BACKUP, "w"), indent=1)
    print("saved", BACKUP)


def do_restore():
    b = json.load(open(BACKUP))
    lb = b["lock_band"]
    set_mode(b["networkMode"])
    post(161, band4gRadio=lb["band_4g_switch"], lock4gBand=lb["lock_band_4g"].lower(),
         band5gRadio=lb["band_5g_switch"], lock5gBand=lb["lock_band_5g"].lower())
    print("restored; online:", wait_online())


def visible_bands():
    cells = [c.split(",") for c in get(282).get("lte_info", "").split(";") if c]
    st = status()
    earfcns = [int(c[0]) for c in cells] + [int(f) for f in (st["earfcn"] or "").split("+") if f.isdigit()]
    return sorted({b for b in map(band_of, earfcns) if b})


def scan(try_cells=False):
    if not os.path.exists(BACKUP):
        do_backup()
    print("unlocking all bands to see what is around...")
    if try_cells:
        set_cell_lock(None)
    set_bands(None, None)
    st = wait_online()
    print("unlocked:", st)
    time.sleep(10)  # let the modem collect neighbour measurements
    bands = visible_bands()
    print("visible 4G bands:", bands)
    home = home_plmn()
    # every band combination: singles, pairs, ..., all (CA needs the combos, not just singles)
    combos = [list(c) for n in range(1, len(bands) + 1) for c in itertools.combinations(bands, n)]
    results = [trial("no lock", None, None, home, st)]
    results += [trial("B" + "+B".join(map(str, c)), c, None, home) for c in combos]
    best = max(results, key=score)
    if try_cells:  # then try a cell lock on each home-network cell seen above, on top of the best band set
        home_ok = [r for r in results if r["st"] and not r["roaming"]]
        cells = {c for r in home_ok for c in zip(r["st"]["earfcn"].split("+"), r["st"]["pci"].split("+"))}
        freqs = {f for f, _ in cells}
        # neighbours on the same frequencies belong to the same operator; take the 4 strongest
        nb = {(c[0], c[1]): int(c[2]) for r in home_ok for c in (x.split(",") for x in r["nb"].split(";") if x)}
        cells |= set([c for c in sorted(nb, key=nb.get, reverse=True) if c[0] in freqs and c not in cells][:4])
        results += [trial(f"{best['label']} + cell {f}:{p}", best["bands"], [(f, p)], home) for f, p in sorted(cells)]
        best = max(results, key=score)
    if score(best) <= 0:
        print("nothing usable on the home network, restoring backup")
        if try_cells:
            set_cell_lock(None)
        return do_restore()
    print("BEST:", best["label"], {k: best.get(k) for k in ("dl_ir", "ul_ir", "ping_ir", "jitter_ir", "dl_int", "ping_int")})
    set_bands(best["bands"], None)
    if try_cells:
        set_cell_lock(best["cells"])
    print("final:", wait_online(180))
    json.dump(results, open(os.path.join(os.path.dirname(BACKUP), "zlt_scan.json"), "w"), indent=1, ensure_ascii=False)


def trial(label, bands, cells, home, st=None):
    try:
        if st is None:
            set_bands(bands, None)
            if cells:
                set_cell_lock(cells)
            st = wait_online(180)
        r = {"label": label, "bands": bands, "cells": cells, "st": st, **(measure() if st else {})}
    except Exception as e:
        r = {"label": label, "bands": bands, "cells": cells, "st": None, "err": str(e)}
    s = r["st"] or {}
    r["roaming"] = bool(s) and s.get("plmn") != home
    if s and not r["roaming"]:  # neighbours of a home cell; read now, while still on the home network
        r["nb"] = get(282).get("lte_info", "")
    if r["roaming"] and not ALLOW_ROAMING:
        r["ping_ir"] = None  # score() -> -1: never pick a roaming result
    print(f"  {label}: {s.get('op')}{' ROAMING' if r['roaming'] else ''} {s.get('band')} pci={s.get('pci')} "
          f"rsrp={s.get('rsrp')} sinr={s.get('sinr')} -> IR {r.get('dl_ir')}↓ {r.get('ul_ir')}↑ Mbps "
          f"{r.get('ping_ir')}±{r.get('jitter_ir')} ms | INT {r.get('dl_int')}↓ Mbps {r.get('ping_int')} ms | "
          f"loss {r.get('loss')}% | score {score(r):.1f}", flush=True)
    return r


def scan_cells():
    """Modem cell scan (all operators). Brief radio interruption."""
    r = post(342, sccan_pci="1")
    cols = [(r.get(k) or "").split(",") for k in ("pcid_4g", "earfcn_4g", "rsrp_4g", "eci")]
    return [{"pci": p, "earfcn": int(e), "band": band_of(int(e)), "rsrp": int(s), "eci": c}
            for p, e, s, c in zip(*cols) if p]


def set_cell_lock(cells):
    """Lock LTE to (earfcn, pci) pairs, e.g. [("325", "251")]; None = off. Needs the root login."""
    post(160, subcmd=0, lte_lock_sw="1" if cells else "0",
         lte_lock_freq=",".join(f for f, _ in cells or []), lte_lock_pci=",".join(p for _, p in cells or []))


def parse_cells(arg):
    return None if arg == "off" else [tuple(c.split(":")) for c in arg.split(",")]


def watch():
    """Live signal for placing the modem: move it, watch SINR/RSRP. Ctrl+C to stop."""
    while True:
        s = status()
        print(f"{time.strftime('%H:%M:%S')} {s['op']} {s['type']} B{s['band']} pci={s['pci']} "
              f"RSRP {s['rsrp']} RSRQ {s['rsrq']} SINR {s['sinr']} CQI {s['cqi']}", flush=True)
        time.sleep(2)


def parse_lock(args):
    if not args or args[0] == "all":
        return None, None
    b4 = [int(x) for x in args[0].lower().replace("b", "").split(",") if x]
    b5 = [int(x) for x in args[1].lower().replace("n", "").split(",")] if len(args) > 1 else None
    return b4, b5


if __name__ == "__main__":
    a = sys.argv[1:] or ["status"]
    if a[0] == "test":  # offline self-check against values read from this modem
        assert mask([38, 40, 41, 42, 43]) == "7a000000000" and unmask("7A0880800D5")[:4] == [1, 3, 5, 7]
        assert band_of(39550) == 40 and band_of(1650) == 3 and band_of(300) == 1
        assert score({"ping_ir": None}) == -1 and score({"dl_ir": 40, "dl_int": 20, "ping_ir": 50, "loss": 0}) == 20
        assert parse_cells("325:251,3102:270") == [("325", "251"), ("3102", "270")] and parse_cells("off") is None
        sys.exit(print("ok"))
    login()
    if a[0] == "status":
        show_status()
    elif a[0] == "backup":
        do_backup()
    elif a[0] == "restore":
        do_restore()
    elif a[0] == "mode":
        set_mode(a[1]); print(wait_online())
    elif a[0] == "lock":
        set_bands(*parse_lock(a[1:])); print(wait_online())
    elif a[0] == "scan":
        scan(try_cells="--cells" in a)
    elif a[0] == "cells":
        for c in sorted(scan_cells(), key=lambda c: c["rsrp"], reverse=True): print(c)
    elif a[0] == "celllock":
        set_cell_lock(parse_cells(a[1])); print(wait_online(180))
    elif a[0] == "watch":
        watch()
    elif a[0] == "at":
        import base64; print(post(270, atInfo=base64.b64encode(a[1].encode()).decode()).get("flag"))
    elif a[0] == "operator":
        set_operator(a[1], a[2] if len(a) > 2 else "7"); print(wait_online(200))
    elif a[0] == "speed":
        print(status()); print(measure())
    else:
        print(__doc__)
