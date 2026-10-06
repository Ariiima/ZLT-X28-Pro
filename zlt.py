#!/usr/bin/env python3
"""ZLT X28 Pro helper: status, backup/restore, network mode, band lock, best-band scan.

  python3 zlt.py                        # interactive menu (asks for address, user, password)
  python3 zlt.py auto                   # easy auto-setup: 2 questions, tests everything, keeps the fastest
  python3 zlt.py status
  python3 zlt.py speed                  # domestic + international speed/ping, no changes
  python3 zlt.py watch                  # live RSRP/SINR every 2 s, for placing the modem
  python3 zlt.py backup | restore       # zlt_backup.json
  python3 zlt.py mode 1C                # 1C = 5G SA+NSA/4G, 4 = 4G only, 40 = 4G TDD only
  python3 zlt.py lock 3,1 [78]          # lock 4G bands (and optional 5G bands); "lock all" unlocks
  python3 zlt.py operator 43220         # select this network (modem then reports manual mode, see README)
  python3 zlt.py cells                  # list nearby LTE cells (all operators)
  python3 zlt.py celllock 325:251 | off # lock LTE to earfcn:pci pairs (root login)
  python3 zlt.py at 'AT+COPS?'          # send one AT command to the Quectel module
  python3 zlt.py scan [--operators 43220,43211] [--modes 1C,4] [--cells] [--fast]
                                        # test operators, then modes, then every band combo, then cells;
                                        # each phase keeps its winner; locks the best result

The cell lock needs the root web login: ZLT_USER=root ZLT_PASS=admin.
"""
import base64, getpass, hashlib, itertools, json, os, random, re, statistics, subprocess, sys, time, urllib.request

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
BACKUP = os.path.join(os.path.dirname(os.path.realpath(__file__)), "zlt_backup.json")  # realpath: works via the `zlt` symlink
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


def measure(n=None):
    """Median of n runs per metric; one run is too noisy (tower load changes by the minute)."""
    runs = [measure_once() for _ in range(n or REPEAT)]
    med = lambda xs: statistics.median(xs) if xs else None
    return {k: med([r[k] for r in runs if r[k] is not None]) for k in runs[0]}


def score(r):
    # ponytail: download + half upload, penalised by domestic ping and jitter; tune weights for gaming.
    if r.get("ping_ir") is None:
        return -1
    speed = (r["dl_ir"] + r["dl_int"]) / 2 + r.get("ul_ir", 0) / 2
    return speed / (1 + (r["ping_ir"] + 2 * (r.get("jitter_ir") or 0)) / 100) * (1 - r["loss"] / 100)


def at(cmd):
    """Send one AT command to the radio module; returns its reply text."""
    return post(270, atInfo=base64.b64encode(cmd.encode()).decode()).get("flag", "")


def home_plmn():
    return get(207).get("IMSI", "")[:5]


def set_operator(plmn, act="7"):
    """Web UI 'PLMN select' (sends AT+COPS=4). On firmware 8.5.4.3 the module then reports
    +COPS: 1 (manual), so it does not fall back to roaming. Undo with: at 'AT+COPS=0'."""
    post(228, plmn_select_cmd="4", plmn=plmn, act=act)


def snapshot():
    """Current network mode, band lock and operator selection (manual PLMN or automatic)."""
    m = re.search(r"\+COPS:\s*(\d)(?:,\d,'(\d+)')?", at("AT+COPS?"))
    return {"networkMode": get(256)["networkMode"], "lock_band": get(161),
            "cops": {"mode": m[1], "plmn": m[2]} if m else None}


def do_backup():
    json.dump(snapshot(), open(BACKUP, "w"), indent=1)
    print("saved", BACKUP)


def do_restore(snap=None):
    b = snap or json.load(open(BACKUP))
    lb = b["lock_band"]
    set_mode(b["networkMode"])
    post(161, band4gRadio=lb["band_4g_switch"], lock4gBand=lb["lock_band_4g"].lower(),
         band5gRadio=lb["band_5g_switch"], lock5gBand=lb["lock_band_5g"].lower())
    c = b.get("cops")  # older backup files have no operator entry
    if c and c["mode"] == "1" and c["plmn"]:
        set_operator(c["plmn"])
    elif c:
        at("AT+COPS=0")
    print("restored; online:", wait_online(200))


def visible_bands():
    cells = [c.split(",") for c in get(282).get("lte_info", "").split(";") if c]
    st = status()
    earfcns = [int(c[0]) for c in cells] + [int(f) for f in (st["earfcn"] or "").split("+") if f.isdigit()]
    return sorted({b for b in map(band_of, earfcns) if b})


def scan(try_cells=False, modes=(), operators=()):
    """Phases: operators -> network modes -> band combos -> cells. Each phase keeps its winner.
    ponytail: greedy per phase, not the full cross product (that would take hours)."""
    global ALLOW_ROAMING
    snap = snapshot()  # fresh copy; an old zlt_backup.json can hold a bad setting
    if not os.path.exists(BACKUP):
        do_backup()
    home = home_plmn()
    m = re.search(r"\+COPS:\s*1,\d,'(\d+)'", at("AT+COPS?"))
    if m and m[1] != home and not ALLOW_ROAMING:  # the user chose this network by hand, so allow it
        print(f"manual operator {PLMN.get(m[1], m[1])} (roaming) is set: roaming results count")
        ALLOW_ROAMING = True
    print("unlocking all bands to see what is around...")
    if try_cells:
        set_cell_lock(None)
    set_bands(None, None)
    results = []
    if operators:
        ALLOW_ROAMING = True  # the user asked to compare operators, so roaming results count
        phase = []
        for p in operators:
            set_operator(p)
            r = trial(f"operator {PLMN.get(p, p)}", None, None, home, wait_online(200))
            r["operator"] = p
            phase.append(r)
        results += phase
        win = max(phase, key=score)["operator"]
        print("-> operator:", PLMN.get(win, win))
        set_operator(win)
    if modes:
        phase = []
        for m in modes:
            set_mode(m)
            r = trial(f"mode {m}", None, None, home, wait_online())
            r["mode"] = m
            phase.append(r)
        results += phase
        win = max(phase, key=score)["mode"]
        print("-> mode:", win)
        set_mode(win)
    st = wait_online()
    print("unlocked:", st)
    time.sleep(10)  # let the modem collect neighbour measurements
    bands = visible_bands()
    print("visible 4G bands:", bands)
    # every band combination: singles, pairs, ..., all (CA needs the combos, not just singles)
    combos = [list(c) for n in range(1, len(bands) + 1) for c in itertools.combinations(bands, n)]
    phase = [trial("no lock", None, None, home, st)]
    phase += [trial("B" + "+B".join(map(str, c)), c, None, home) for c in combos]
    results += phase
    best = max(phase, key=score)
    if try_cells:  # then try a cell lock on each home-network cell seen above, on top of the best band set
        op = best["st"]["plmn"] if best["st"] else None  # cells of the operator in use now
        ok = [r for r in phase if r["st"] and r["st"]["plmn"] == op]
        cells = {c for r in ok for c in zip(r["st"]["earfcn"].split("+"), r["st"]["pci"].split("+"))}
        freqs = {f for f, _ in cells}
        # neighbours on the same frequencies belong to the same operator; take the 4 strongest
        nb = {(c[0], c[1]): int(c[2]) for r in ok for c in (x.split(",") for x in r.get("nb", "").split(";") if x)}
        cells |= set([c for c in sorted(nb, key=nb.get, reverse=True) if c[0] in freqs and c not in cells][:4])
        phase += [trial(f"{best['label']} + cell {f}:{p}", best["bands"], [(f, p)], home) for f, p in sorted(cells)]
        results += phase[len(combos) + 1:]
        best = max(phase, key=score)
    json.dump(results, open(os.path.join(os.path.dirname(BACKUP), "zlt_scan.json"), "w"), indent=1, ensure_ascii=False)
    if score(best) <= 0:
        print("nothing usable, putting back the settings from before the scan")
        if try_cells:
            set_cell_lock(None)
        do_restore(snap)
        return None
    print("BEST:", best["label"], {k: best.get(k) for k in ("dl_ir", "ul_ir", "ping_ir", "jitter_ir", "dl_int", "ping_int")})
    set_bands(best["bands"], None)
    if try_cells:
        set_cell_lock(best["cells"])
    print("final:", wait_online(180))
    return best


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
    if s:  # neighbours of the serving cell; read now, while still on this network
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


def opt(a, name):
    """'--modes 1C,4' -> ['1C', '4']; missing -> []."""
    return a[a.index(name) + 1].split(",") if name in a and a.index(name) + 1 < len(a) else []


def run(a):
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
        global REPEAT
        if "--fast" in a:
            REPEAT = 1  # ponytail: fast = one speed run per candidate instead of the median of REPEAT
        scan(try_cells="--cells" in a, modes=opt(a, "--modes"), operators=opt(a, "--operators"))
    elif a[0] == "auto":
        easy_setup()
    elif a[0] == "cells":
        for c in sorted(scan_cells(), key=lambda c: c["rsrp"], reverse=True): print(c)
    elif a[0] == "celllock":
        set_cell_lock(parse_cells(a[1])); print(wait_online(180))
    elif a[0] == "watch":
        watch()
    elif a[0] == "at":
        print(at(a[1]))
    elif a[0] == "operator":
        set_operator(a[1], a[2] if len(a) > 2 else "7"); print(wait_online(200))
    elif a[0] == "speed":
        print(status()); print(measure())
    else:
        print(__doc__)


def ask(prompt, default=""):
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or default


def yes(prompt, default=False):
    v = ask(prompt + (" (Y/n)" if default else " (y/N)")).lower()
    return v.startswith("y") if v else default


MODE_NAMES = {"1C": "5G + 4G", "4": "4G only", "20": "4G FDD only", "40": "4G TDD only", "C": "5G NSA only", "10": "5G SA only"}
IR_OPERATORS = ["43211", "43235", "43220"]  # MCI, Irancell, Rightel: candidates for national roaming


def fmt(r):
    if r.get("ping_ir") is None:
        return "no connection"
    return (f"{r['dl_ir']:.0f} Mbps download, {r['ul_ir']:.0f} Mbps upload, ping {r['ping_ir']:.0f} ms (domestic); "
            f"{r['dl_int']:.0f} Mbps download (international)")


def describe(home):
    s, lb, m = status(), get(161), get(256)["networkMode"].upper()
    bands = ", ".join(f"B{b}" for b in unmask(lb["lock_band_4g"])) if lb["band_4g_switch"] == "1" else "all (no lock)"
    return (f"  Operator: {s['op']}{' (national roaming)' if s['plmn'] != home else ''}\n"
            f"  Network:  {MODE_NAMES.get(m, m)}\n  4G bands: {bands}\n  Signal:   RSRP {s['rsrp']} dBm, SINR {s['sinr']} dB")


def easy_setup():
    """For non-technical users: two questions, then test everything, keep the best, undo if not better."""
    home = home_plmn()
    name = PLMN.get(home, home)
    print("\nEasy auto-setup")
    print("The tool tests different settings, keeps the fastest one, and sets it for you.")
    print("If the new setting is not faster, it puts your old setting back.\n")
    others = [p for p in IR_OPERATORS if p != home] if home in IR_OPERATORS else []
    roam = bool(others) and yes(
        f"Your SIM card is {name}. Can the modem also try {' and '.join(PLMN[p] for p in others)} "
        f"(national roaming)?\nThis can be much faster, but {name} can charge more for it. Ask {name} first.")
    n = 1 + (len(others) if roam else 0) + 2 + 7 + (5 if USER == "root" else 0)  # rough test count
    if not yes(f"\nThe test takes about {n * 2}-{n * 3} minutes. The internet stops for short periods. Start?", True):
        return
    snap = snapshot()
    print("\nStep 1 of 3: measuring your current speed...")
    before = measure()
    print("  Now:", fmt(before))
    if not roam and status()["plmn"] != home:
        set_operator(home)  # the user said no roaming: go back to the own network before the test
    print("\nStep 2 of 3: testing settings. This takes a while (technical details below)...")
    best = scan(try_cells=USER == "root", modes=["1C", "4"], operators=[home] + others if roam else ())
    print("\nStep 3 of 3: measuring the new speed...")
    after = measure()
    # ponytail: 10% margin, so measurement noise does not undo a real improvement
    if best is None or score(after) < 0.9 * score(before):
        print("\nThe new setting is not faster than your old setting. Putting your old setting back...")
        if USER == "root":
            set_cell_lock(None)  # ponytail: an old cell lock is not restored, only removed
        do_restore(snap)
        after = measure()
    print("\nDone.")
    print("  Before:", fmt(before))
    print("  After: ", fmt(after))
    print(describe(home))


def ask_scan():
    print("Operators to compare (PLMN codes). " + ", ".join(f"{k}={v}" for k, v in PLMN.items()))
    ops = ask("Operators, comma-separated (Enter = keep the current one)")
    modes = ask("Network modes to compare, e.g. 1C,4 (Enter = keep the current mode)")
    cells = ask("Also test a cell lock on each cell? Needs the root login (y/N)", "n").lower().startswith("y")
    print("The internet stops for short periods. A full scan takes 10-40 minutes.")
    return ["scan"] + (["--operators", ops] if ops else []) + (["--modes", modes] if modes else []) + (["--cells"] if cells else [])


MENU = [
    ("Easy auto-setup: find and set the fastest setting for me (recommended)", lambda: ["auto"]),
    ("Fast scan: current operator and mode, test band locks, 1 run each (~5 min)", lambda: ["scan", "--fast"]),
    ("Full scan: compare MCI, Irancell, Rightel, 5G/4G modes, band locks (+cells as root) (~30-60 min)",
     lambda: ["scan", "--operators", ",".join(IR_OPERATORS), "--modes", "1C,4"] + (["--cells"] if USER == "root" else [])),
    ("Status", lambda: ["status"]),
    ("Speed test (no changes)", lambda: ["speed"]),
    ("Live signal, to find the best position (Ctrl+C to stop)", lambda: ["watch"]),
    ("Auto scan with my own choices (advanced)", ask_scan),
    ("Lock 4G bands", lambda: ["lock", ask("4G bands, e.g. 1,3,7 (all = no lock)", "all")]),
    ("Network mode", lambda: ["mode", ask(", ".join(f"{k} = {v}" for k, v in MODE_NAMES.items()), "1C")]),
    ("Operator (stops or selects roaming)", lambda: ["operator", ask(", ".join(f"{k}={v}" for k, v in PLMN.items()))]),
    ("Cell lock (root login)", lambda: ["celllock", ask("EARFCN:PCI, e.g. 325:251 (off = no lock)", "off")]),
    ("List nearby cells of all operators", lambda: ["cells"]),
    ("Send an AT command", lambda: ["at", ask("AT command", "AT+COPS?")]),
    ("Back up settings", lambda: ["backup"]),
    ("Restore settings", lambda: ["restore"]),
]


def interactive():
    global HOST, USER, PASS, URL
    print("ZLT X28 / X28 Pro tool. Press Ctrl+C to stop an action, or Ctrl+D to quit.\n")
    HOST = ask("Router address", HOST)
    URL = f"http://{HOST}/cgi-bin/http.cgi"
    while True:
        USER = ask("User (admin, or root for the cell lock)", USER)
        PASS = getpass.getpass(f"Password for {USER} (Enter = default 'admin'): ") or PASS
        try:
            login()
            break
        except SystemExit as e:
            print(f"{e}\nWrong user or password. After 3 wrong tries, the router locks the login for 3 minutes.")
    run(["status"])
    while True:
        print()
        for i, (name, _) in enumerate(MENU, 1):
            print(f"{i:2}. {name}")
        print(" 0. Quit")
        try:
            c = ask("Select")
            if c in ("0", "q"):
                return
            if not c.isdigit() or not 1 <= int(c) <= len(MENU):
                continue
            args = MENU[int(c) - 1][1]()
            print("$ zlt " + " ".join(args))
            run(args)
        except KeyboardInterrupt:
            print("\nstopped")
        except EOFError:
            return print()
        except Exception as e:
            print("error:", e, "(the cell lock needs the root login)" if "LIMITED_ACCESS" in str(e) else "")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "test":  # offline self-check against values read from this modem
        assert mask([38, 40, 41, 42, 43]) == "7a000000000" and unmask("7A0880800D5")[:4] == [1, 3, 5, 7]
        assert band_of(39550) == 40 and band_of(1650) == 3 and band_of(300) == 1
        assert score({"ping_ir": None}) == -1 and score({"dl_ir": 40, "dl_int": 20, "ping_ir": 50, "loss": 0}) == 20
        assert parse_cells("325:251,3102:270") == [("325", "251"), ("3102", "270")] and parse_cells("off") is None
        assert opt(["scan", "--modes", "1C,4", "--cells"], "--modes") == ["1C", "4"] and opt(["scan"], "--modes") == []
        assert fmt({"ping_ir": None}) == "no connection" and fmt(
            {"dl_ir": 86.4, "ul_ir": 44.7, "dl_int": 80, "ping_ir": 37.9}).startswith("86 Mbps download, 45 Mbps upload, ping 38 ms")
        sys.exit(print("ok"))
    if not a:
        try:
            interactive()
        except (KeyboardInterrupt, EOFError):
            print()
    else:
        login()
        run(a)
