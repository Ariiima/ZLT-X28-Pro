# ZLT-X28-Pro

A command-line tool for the **ZLT X28 / X28 Pro** 4G/5G router. It reads the signal and sets the network mode, band lock, and operator through the router's own web API. It can test each band combination and lock the fastest one.

- One file: `zlt.py`. Python 3 standard library only, with no `pip install` step.
- It uses the router's own web login. It does not need telnet, SSH, or an exploit.
- Most commands work with the normal login (`admin` / `admin`). The cell lock needs the higher web login `root` / `admin` (see [Logins](#logins)).
- The speed tests use servers in Iran by default. You can change them (see [Configuration](#configuration)).

## Tested on

| Item | Value |
|---|---|
| Router | ZLT X28 PRO, firmware 8.5.4.3 (`idu_dev_type: ZLT X28`) |
| Radio module | Quectel RG500L-EU |
| Computer | macOS (Linux should also work) |
| SIM cards | Rightel, Irancell, MCI (Iran) |

Other firmware versions can use different commands. Before you change a setting, run `status` and `backup`.

## Easy auto-setup (for everyone)

You do not need to know about bands or networks.

1. Connect your computer to the router (Wi-Fi or LAN cable).
2. Disconnect your VPN, if you use one. (The tool can test past a VPN on macOS, but this is easier.)
3. Download `zlt.py`, and run:
   ```
   python3 zlt.py auto
   ```
4. Answer two questions:
   - **"Can the modem also try other operators (national roaming)?"** Roaming can be much faster, but your operator can charge more for it. Ask your operator first. If you are not sure, answer **N**.
   - **"Start?"** The test takes about 15–40 minutes. The internet stops for short periods during the test.
5. Wait. The tool does these steps by itself:
   1. It saves your current settings.
   2. It measures your current speed.
   3. It tests operators (only if you said yes), network modes, and band combinations. With the `root` login, it also tests cell locks.
   4. It sets the fastest setting.
   5. It measures again. If the new setting is not faster, it puts your old setting back.
6. Read the result:
   ```
   Done.
     Before: 21 Mbps download, 25 Mbps upload, ping 35 ms (domestic); 13 Mbps download (international)
     After:  86 Mbps download, 45 Mbps upload, ping 38 ms (domestic); 80 Mbps download (international)
     Operator: MCI (national roaming)
     Network:  5G + 4G
     4G bands: B1, B7
   ```

You can also start the easy setup from the interactive menu (item 1).

## Interactive mode

1. Connect your computer to the router (Wi-Fi or LAN cable).
2. Download `zlt.py`.
3. Run it without arguments:
   ```
   python3 zlt.py
   ```
4. Enter the router address, the user, and the password. Press Enter to use the defaults (`192.168.70.1`, `admin`, `admin`). For the cell lock, use the user `root`.
5. The tool shows the current status and a menu:
   ```
    1. Easy auto-setup: find and set the fastest setting for me (recommended)
    2. Status
    3. Speed test (no changes)
    4. Live signal, to find the best position (Ctrl+C to stop)
    5. Auto scan with my own choices (advanced)
    6. Lock 4G bands
    7. Network mode
    8. Operator (stops or selects roaming)
    9. Cell lock (root login)
   10. List nearby cells of all operators
   11. Send an AT command
   12. Back up settings
   13. Restore settings
    0. Quit
   ```
6. Type a number and press Enter. The tool asks for the values that it needs, and it shows the equivalent command line.

Press Ctrl+C to stop an action and go back to the menu. Press Ctrl+D or `0` to quit.

## Quick start (command line)

1. Connect your computer to the router (Wi-Fi or LAN cable).
2. Download `zlt.py`.
3. Run the offline self-check:
   ```
   python3 zlt.py test
   ```
4. Read the current state. This command does not change anything:
   ```
   python3 zlt.py status
   ```
5. Save the current settings, so that you can restore them later:
   ```
   python3 zlt.py backup
   ```
6. Test all band combinations and lock the best one. The internet stops for short periods during the scan:
   ```
   python3 zlt.py scan
   ```

## Commands

| Command | What it does | Changes settings? |
|---|---|---|
| `status` | Shows the operator, band, PCI, RSRP, SINR, the locks, and the neighbour cells | No |
| `speed` | Tests download, upload, ping, and jitter (domestic and international) | No |
| `watch` | Shows RSRP/RSRQ/SINR every 2 s. Use it to find the best position for the router | No |
| `cells` | Scans all nearby LTE cells of all operators | No (short radio stop) |
| `at 'AT+COPS?'` | Sends one AT command to the radio module and shows the reply | Depends on the command |
| `backup` / `restore` | Saves or restores the network mode, band lock, and operator selection (`zlt_backup.json`) | `restore`: yes |
| `mode 1C` | Sets the network mode (see the table below) | Yes |
| `lock 3,7` | Locks 4G to bands B3 and B7. `lock all` removes the lock. `lock 3 78` also locks 5G to n78 | Yes |
| `operator 43235` | Selects one operator (PLMN). See [Roaming](#roaming) | Yes |
| `auto` | Easy auto-setup: asks 2 questions, tests everything, keeps the fastest, undoes it if not faster | Yes |
| `scan` | Tests "no lock", each band, and each band combination, then locks the best | Yes |
| `scan --operators 43220,43211` | First compares operators (national roaming included), and keeps the best | Yes |
| `scan --modes 1C,4` | Compares network modes, and keeps the best | Yes |
| `scan --cells` | Also tests a cell lock on each cell of the operator in use (root login) | Yes |
| `celllock 325:251` / `celllock off` | Locks LTE to one or more `EARFCN:PCI` cells (root login) | Yes |

### Network modes

| Value | Mode |
|---|---|
| `1C` | 5G (SA+NSA) / 4G, recommended |
| `4` | 4G only |
| `20` | 4G FDD only |
| `40` | 4G TDD only |
| `C` / `10` | 5G NSA only / 5G SA only |

## Logins

The web UI has more than one user. On firmware 8.5.4.3:

| User / password | Level | Access |
|---|---|---|
| `admin` / `admin` | 3 | Status, band lock, network mode, AT commands, cell scan |
| `root` / `admin` | 2 | All of the above, plus the cell lock (`cmd 160`) and the PLMN-lock setting (`cmd 219`) |

`superadmin` / `superadmin` and `Admin` / `Conf` did not work on this firmware.

To use the root login:

```
ZLT_USER=root ZLT_PASS=admin python3 zlt.py celllock 325:251
```

The router locks the login for 3 minutes after 3 wrong passwords in sequence. A correct login sets the counter back to 0. If you changed the default passwords, use your own.

## How `scan` works

Full example:

```
ZLT_USER=root ZLT_PASS=admin python3 zlt.py scan --operators 43220,43211 --modes 1C,4 --cells
```

The scan has 4 phases. Each phase keeps its best result before the next phase starts:

1. **Operators** (`--operators`): it selects each operator, measures, and keeps the best. Roaming results count in this phase, because you asked for them.
2. **Network modes** (`--modes`): it sets each mode, measures, and keeps the best.
3. **Bands:** see the steps below.
4. **Cells** (`--cells`): see step 6 below.

Test all phases, not only the bands. At one location, the operator change (Rightel → MCI national roaming) increased the speed from 21 to 86–125 Mbps. No band setting could do that.

The band phase:

1. It removes the band lock and reads the bands that the modem can see.
2. It makes a list of tests: "no lock", each band alone, each pair, and all bands together. Carrier aggregation needs band combinations, so single bands are not enough.
3. For each test, it sets the lock, waits until the modem is online, and measures 2 times. It keeps the median, because tower load changes from minute to minute.
4. Each measurement includes:
   - domestic download and upload (4 parallel connections for 10 s, like speedtest.net)
   - international download
   - domestic ping, jitter, and packet loss
   - international ping
5. It calculates a score: speed, divided by a penalty for ping and jitter. It does not use results where the SIM roams on a different operator.
6. With `--cells`, it then tests a cell lock on each cell of your operator. It uses the cells that the modem connected to, plus the 4 strongest neighbour cells on the same frequencies. Each cell lock goes on top of the best band setting.
7. It locks the best setting and saves all results in `zlt_scan.json`.

A full scan takes about 10–20 minutes. Run it at the time of day when you use the internet most, because the best band can change with network load.

## Roaming

The modem can connect to a different operator through national roaming. For example, a Rightel SIM can use the MCI network. Roaming can cost more.

- `scan` shows `ROAMING` in each result where this occurs, and it does not select those results. To allow them, set `ZLT_ALLOW_ROAMING=1`. Roaming results also count when you use `--operators`, or when you selected a roaming operator by hand with `operator`.
- Before you use roaming, find out what it costs. In one test, Rightel removed the same data volume on MCI national roaming as on its own network (1:1). Calls can cost more on roaming.
- **To stop roaming, use `operator <PLMN>`**, for example `python3 zlt.py operator 43220`. On firmware 8.5.4.3, the module then reports `+COPS: 1` (manual mode), and it does not change to roaming. If your operator's signal stops, the internet also stops.
- To set automatic selection again: `python3 zlt.py at 'AT+COPS=0'`
- The web UI also has a PLMN-lock setting (`cmd 219`, root login). It does **not** stop roaming. In our test, `lockPlmn=1, lockPlmnList=43220` was on, but with automatic selection and a B7 band lock, the modem still connected to MCI. The tool does not use this setting.

| Operator | PLMN |
|---|---|
| MCI (Hamrah-e Aval) | 43211 |
| Irancell | 43235 |
| Rightel | 43220 |

## Configuration

Set these environment variables to change the defaults:

| Variable | Default | Purpose |
|---|---|---|
| `ZLT_HOST` | `192.168.70.1` | Router address |
| `ZLT_USER` / `ZLT_PASS` | `admin` / `admin` | Web login |
| `ZLT_IFACE` | `en0` | The network interface to the router. The tests use this interface, so they skip a VPN. On Linux, use for example `wlan0` |
| `ZLT_DL_IR` / `ZLT_UL_IR` | Asiatech Ookla server, Tehran | Domestic download / upload URL |
| `ZLT_DL` | Cloudflare | International download URL |
| `ZLT_PING_IR` / `ZLT_PING` | `217.218.127.127` / `4.2.2.4` | Domestic / international ping target |
| `ZLT_REPEAT` | `2` | Measurements for each test (the median is used) |
| `ZLT_ALLOW_ROAMING` | off | Set to `1` to allow roaming results in `scan` |

Example for a different country:

```
ZLT_DL_IR="http://<your-ookla-server>:8080/download?size=500000000" \
ZLT_UL_IR="http://<your-ookla-server>:8080/upload" \
ZLT_PING_IR=<a-local-ip> python3 zlt.py scan
```

To find Ookla servers near you, open `https://www.speedtest.net/api/js/servers?engine=js&search=<city>`.

## Tips

- **Position is the most important setting.** Run `watch`, then move the router slowly near windows and high places. Look for the highest SINR. SINR is more important than RSRP.
- **Do a check of the network mode first.** One router that we tested was set to "4G TDD Only" and locked to bands B38/B40–B43. Because of this, it could not find the SIM's own operator, so it used national roaming with a poor signal. `mode 1C` and `lock all` corrected the fault.
- **Use 5 GHz Wi-Fi or a LAN cable** for the lowest ping.
- **Test more than one SIM** if you can. At one location, the three operators had 15 MHz, 60 MHz, and 5×20 MHz of bandwidth.

## Known limits

- **Cell lock needs the root login.** With `admin`, `cmd 160` gives `LIMITED_ACCESS`. The "ECGI/PCI lock" list (`cmd 341`) accepts settings, but in our tests the modem did not change cell, so the tool does not use it. The Quectel `AT+QNWLOCK` command is not available on this module (`CME ERROR: 100`).
- **A cell lock can make the speed worse.** If the locked cell has a fault or too many users, the modem cannot move to a better cell. Run `scan --cells` again from time to time, or use `celllock off`.
- **The international test can show a maximum of about 80 Mbps.** Cloudflare refuses requests above about 25 MB, and the tool uses 4 × 25 MB in 10 s.
- **The operator scan of the web UI (`cmd 228`) fails** while the data connection is on (error 502). Use `cells` instead.
- The tool does not change Wi-Fi, APN, DNS, or firewall settings.

## API notes

The router's web UI sends JSON to `POST /cgi-bin/http.cgi`. The tool uses these commands:

| cmd | Purpose |
|---|---|
| 232 → 100 | Login: get a token, then send `sha256(token + password)` |
| 233 | Get a new token. Every POST needs a token |
| 0, 113, 205, 207 | System, status, signal, and device information (`205` has RSRP/SINR/PCI/band) |
| 161 | Band lock. `lock4gBand` is a hex bitmask, where bit *n−1* = band *n* |
| 160 | Cell lock (root): `subcmd=0, lte_lock_sw, lte_lock_freq, lte_lock_pci` (comma lists). `lock_4g_flag=1` when locked |
| 219 | PLMN-lock setting (root): `lockPlmn, lockPlmnList`. It did not stop roaming in our test |
| 256 | Network mode |
| 228 | Operator (PLMN) scan and selection |
| 270 | Send AT command (`atInfo` = base64 of the command) |
| 282 | Neighbour cells (`earfcn,pci,rsrp,rsrq;…`) |
| 342 | Cell scan of all operators (`pcid_4g, earfcn_4g, rsrp_4g, eci`) |

The router sends an empty reply when a new band lock is the same as the current one. The tool accepts this as success.

## Safety

- Run `backup` before you change settings. `restore` sets the saved mode and band lock again.
- `scan` and `lock` stop the internet for about 30–60 s for each change.
- Do not publish `zlt_backup.json` or `zlt_scan.json`. They contain your WAN IP addresses and the IDs of the cells near your location. The `.gitignore` of this repository excludes them.
- You use this tool at your own risk. It changes only settings that the router's own web UI can also change.

## License

MIT
