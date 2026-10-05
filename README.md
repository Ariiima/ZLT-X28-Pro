# ZLT-X28-Pro

A command-line tool for the **ZLT X28 / X28 Pro** 4G/5G router. It reads the signal and sets the network mode, band lock, and operator through the router's own web API. It can test each band combination and lock the fastest one.

- One file: `zlt.py`. Python 3 standard library only, with no `pip install` step.
- It uses the normal web login (`admin` / `admin` by default). It does not need root, telnet, or an exploit.
- The speed tests use servers in Iran by default. You can change them (see [Configuration](#configuration)).

## Tested on

| Item | Value |
|---|---|
| Router | ZLT X28 PRO, firmware 8.5.4.3 (`idu_dev_type: ZLT X28`) |
| Radio module | Quectel RG500L-EU |
| Computer | macOS (Linux should also work) |
| SIM cards | Rightel, Irancell, MCI (Iran) |

Other firmware versions can use different commands. Before you change a setting, run `status` and `backup`.

## Quick start

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
| `backup` / `restore` | Saves or restores the network mode and band lock (`zlt_backup.json`) | `restore`: yes |
| `mode 1C` | Sets the network mode (see the table below) | Yes |
| `lock 3,7` | Locks 4G to bands B3 and B7. `lock all` removes the lock. `lock 3 78` also locks 5G to n78 | Yes |
| `operator 43235` | Selects one operator (PLMN). See [Roaming](#roaming) | Yes |
| `scan` | Tests "no lock", each band, and each band combination, then locks the best | Yes |
| `scan --cells` | Also tries a PCI lock on the strongest cells (experimental) | Yes |
| `pcilock 119` / `pcilock off` | Allows only these cells (experimental) | Yes |

### Network modes

| Value | Mode |
|---|---|
| `1C` | 5G (SA+NSA) / 4G, recommended |
| `4` | 4G only |
| `20` | 4G FDD only |
| `40` | 4G TDD only |
| `C` / `10` | 5G NSA only / 5G SA only |

## How `scan` works

1. It removes the band lock and reads the bands that the modem can see.
2. It makes a list of tests: "no lock", each band alone, each pair, and all bands together. Carrier aggregation needs band combinations, so single bands are not enough.
3. For each test, it sets the lock, waits until the modem is online, and measures 2 times. It keeps the median, because tower load changes from minute to minute.
4. Each measurement includes:
   - domestic download and upload (4 parallel connections for 10 s, like speedtest.net)
   - international download
   - domestic ping, jitter, and packet loss
   - international ping
5. It calculates a score: speed, divided by a penalty for ping and jitter. It does not use results where the SIM roams on a different operator.
6. It locks the best setting and saves all results in `zlt_scan.json`.

A full scan takes about 10–20 minutes. Run it at the time of day when you use the internet most, because the best band can change with network load.

## Roaming

The modem can connect to a different operator through national roaming. For example, a Rightel SIM can use the MCI network. Roaming can cost more.

- `scan` shows `ROAMING` in each result where this occurs, and it does not select those results. To allow them, set `ZLT_ALLOW_ROAMING=1`.
- `operator <PLMN>` tells the modem to use your own operator. On firmware 8.5.4.3, the module then reports `+COPS: 1` (manual mode). In manual mode, the modem does not change to roaming. But if your operator's signal stops, the internet also stops.
- To set automatic selection again: `python3 zlt.py at 'AT+COPS=0'`

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

- **PCI lock (`pcilock`, `scan --cells`) is experimental.** The web API accepts the setting (`cmd 341`), but in our tests the modem stayed on its old cell. The real cell lock (`cmd 160`) gives `LIMITED_ACCESS` to the `admin` user. The Quectel `AT+QNWLOCK` command is not available on this module (`CME ERROR: 100`).
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
| 256 | Network mode |
| 228 | Operator (PLMN) scan and selection |
| 270 | Send AT command (`atInfo` = base64 of the command) |
| 282 | Neighbour cells (`earfcn,pci,rsrp,rsrq;…`) |
| 341 / 342 | PCI lock list / cell scan |

The router sends an empty reply when a new band lock is the same as the current one. The tool accepts this as success.

## Safety

- Run `backup` before you change settings. `restore` sets the saved mode and band lock again.
- `scan` and `lock` stop the internet for about 30–60 s for each change.
- Do not publish `zlt_backup.json` or `zlt_scan.json`. They contain your WAN IP addresses and the IDs of the cells near your location. The `.gitignore` of this repository excludes them.
- You use this tool at your own risk. It changes only settings that the router's own web UI can also change.

## License

MIT
