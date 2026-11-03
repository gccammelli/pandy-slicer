# Pandy Slicer

Slices MakerWorld models with Bambu Studio, so the [Pandy](https://github.com/gccammelli/pandy) app can print them on
a Bambu Lab printer in LAN-only mode (where Bambu's cloud slicing isn't available).

## Set up

1. Start the add-on. The first start builds it, which downloads Bambu Studio (about 220 MB): give it a few minutes.
2. That's it. Pandy (with this Home Assistant added) reaches the add-on through Home Assistant: no address, port or
   token to enter. In Pandy, **Me › Settings › Slicer for MakerWorld prints › Check the add-on** confirms it answers.
   Pandy's Home Assistant user must be an administrator.

## Using it

In Pandy's **Models** tab, open a model and tap **Print**. Pandy downloads the profile, shows its plates, filaments
and options; when you print, this add-on slices the plate (about a minute), uploads it to the printer, and the print
starts. On the Prepare to Print screen, **Advanced slicer settings** lets you override quality, strength, support,
adhesion and speed for that print. Unchanged settings keep the profile's values. The slicer checks the resulting file
and refuses overrides that conflict with settings assigned to individual objects or layers, even on another plate.
Third-party object settings that cannot be checked also require resetting the advanced settings. The filament's
maximum flow can limit the requested speed.

## Configuration

| Option | |
|---|---|
| `token` | For direct access only: requests on port 8737 need it, and without a token port 8737 refuses everything. Not needed through Home Assistant. |

Port 8737 is off by default: Pandy doesn't need it. Turn it on (Network, below) only for an app that can't go through
Home Assistant, and don't forward it to the internet.

## Limits

- x86-64 only: Bambu Studio is published for x86-64 Linux, so not on a Raspberry Pi.
- It slices with the profile's settings, converted to your printer when needed, plus any advanced overrides chosen in Pandy.
- Filament temperatures, custom G-code and the full Bambu Studio editor are not available through advanced settings.
