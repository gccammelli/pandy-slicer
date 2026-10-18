# Pandy Slicer

Bambu Studio's slicer in a container, so the [Pandy](https://github.com/gccammelli/pandy) app can print MakerWorld
models on a Bambu Lab printer in **LAN-only mode**, where Bambu's cloud slicing isn't available.

```
MakerWorld (Pandy's Models tab) ──3MF──▶ Pandy ──3MF──▶ Pandy Slicer ──sliced file (FTPS)──▶ printer
                                           └──────────── start the print (MQTT or Home Assistant) ─────▶
```

It runs Bambu Studio's own command line, unmodified, and adds what printing from a phone needs:

- **Your printer, whatever the profile was made for**: a P1S or A1 profile is converted to your printer, keeping the
  designer's settings, as Bambu Studio's printer switch does.
- **Safe prints**: missing printer G-code is filled in from Bambu's preset, and a file without the printer's start
  sequence (homing, bed leveling, purge line) is refused.
- **Plate pictures** kept from the project, for Pandy's history and Skip Parts.
- **Upload** to the printer over FTPS, checking its certificate against Bambu's CAs.

x86-64 only (Bambu Studio is published for x86-64 Linux). About 2 GB of disk.

## Install: Home Assistant add-on

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fgccammelli%2Fpandy-slicer)

Or by hand: Settings › Add-ons › Add-on store › ⋮ › **Repositories**, add `https://github.com/gccammelli/pandy-slicer`.
Then install **Pandy Slicer** and start it (the first start downloads Bambu Studio: give it a few minutes). Pandy
finds it through Home Assistant by itself (Home Assistant's ingress), so there's no address to enter and no port to
open: it works wherever Pandy reaches Home Assistant. Pandy's Home Assistant user must be an administrator.

## Install: Docker, anywhere

```
git clone https://github.com/gccammelli/pandy-slicer
cd pandy-slicer
docker compose up -d
```

Then in Pandy (Me › Settings › **Slicer for MakerWorld prints**) enter `<that computer's IP>:8737`. To require a token, set `PANDY_SLICER_TOKEN` in
`docker-compose.yml` (or the add-on's **token** option) and enter the same one in Pandy. Don't expose port 8737 to the
internet.

## API

| | |
|---|---|
| `GET /health` | `{"ok": true, "version": "<Bambu Studio version>"}` |
| `POST /slice?plate=1&name=<name>` | body: the 3MF; answers the sliced `.gcode.3mf`, with a JSON summary in `X-Pandy-Result` |
| `&printer=<preset>` | re-target to that Bambu printer preset first, e.g. `Bambu Lab X1 Carbon 0.4 nozzle` |
| `&upload=1` | also put it on the printer: headers `X-Printer-Ip`, `X-Printer-Serial`, `X-Printer-Code`; answers `{"path": "cache/<name>.gcode.3mf", "plates": […]}` |

With a token set, send `Authorization: Bearer <token>` (not needed through Home Assistant's ingress, which checks who
is asking itself). One slice at a time.

## Development

```
python3 -m unittest discover tests     # the slicer's own logic, no Bambu Studio needed
docker build -t pandy-slicer pandy_slicer
```

Every Monday a workflow checks for a new Bambu Studio release. When there is one, it moves the add-on to it, checks it
builds and Bambu Studio starts, and opens a pull request with the end-to-end checks to do before merging. Merging
releases it to Home Assistant.

## Credits

[Bambu Studio](https://github.com/bambulab/BambuStudio) (AGPL-3.0), downloaded unmodified at build time. Bambu's CA
certificates from the [Home Assistant Bambu Lab integration](https://github.com/greghesp/ha-bambulab) (MIT).

Developed by Giancarlo Cammelli. MIT licence. Like it? [Buy me a coffee](https://buymeacoffee.com/cammelli).

[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/cammelli)
