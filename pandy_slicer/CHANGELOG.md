# Changelog

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
