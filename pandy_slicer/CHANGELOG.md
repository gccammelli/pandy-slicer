# Changelog

## 1.2.0

- A token is now required for direct access (port 8737); without one, only Home Assistant's ingress is let in.
- Uploading to the printer (`upload=1`) works only through Home Assistant, so the access code never travels in plain HTTP.
- The project's printer G-code is always replaced with Bambu's own for that printer, and sliced files with temperatures
  beyond Bambu printers' limits are refused.
- Printer presets are looked up by name only, uploads are size-checked before unpacking, and at most 4 connections are
  served at once.
- The printer's certificate is checked against Bambu's certificates only.
- Bambu Studio's download is checked against its SHA-256, and the slicer runs as an unprivileged user.

## 1.1.1

- A 3MF that isn't a Bambu Studio project gets a clear error instead of a dropped connection ("502 Bad Gateway"
  through Home Assistant).

## 1.1.0

- Pandy reaches the add-on through Home Assistant (ingress): no address or port to set up, and it works wherever
  Pandy reaches Home Assistant. Needs Pandy 1.0.8 or newer.
- Port 8737 is now off by default (turn it on under Network for direct access). The token applies only there. If you
  entered this add-on's address in Pandy, remove it there (Me › Settings › Slicer › Remove).
- "Open web UI" shows that the slicer is running.

## 1.0.1

- Installs on Home Assistant: the Ubuntu base is set in the Dockerfile (Home Assistant ignored the old build.yaml
  and built on Alpine).

## 1.0.0

- Slices 3MF projects (MakerWorld print profiles) with Bambu Studio 02.08.02.61's command line, and puts the result
  on the printer over FTPS.
- Re-targets a profile made for another Bambu printer to yours, keeping the designer's settings, as Bambu Studio's
  printer switch does.
- Fills in missing printer G-code from Bambu's preset, and refuses files without the printer's start sequence
  (homing, bed leveling, purge line).
- Keeps the project's plate pictures (the command line can't draw them without a screen).
- Optional token.
