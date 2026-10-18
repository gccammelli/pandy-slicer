# Pandy Slicer

Slices MakerWorld models with Bambu Studio, so the [Pandy](https://github.com/gccammelli/pandy) app can print them on
a Bambu Lab printer in LAN-only mode (where Bambu's cloud slicing isn't available).

## Set up

1. Start the add-on. The first start builds it, which downloads Bambu Studio (about 220 MB): give it a few minutes.
2. Optional: set a **token** below and restart, so only Pandy can use it.
3. In Pandy: **Me › Settings › Slicer for MakerWorld prints**: your Home Assistant's address with port **8737**
   (for example `homeassistant.local:8737` or its IP), and the token if you set one. **Save** checks it answers.

## Using it

In Pandy's **Models** tab, open a model and tap **Print**. Pandy downloads the profile, shows its plates, filaments
and options; when you print, this add-on slices the plate (about a minute), uploads it to the printer, and the print
starts.

## Configuration

| Option | |
|---|---|
| `token` | Optional. When set, requests need it (Pandy sends it). |

The add-on listens on port 8737. Don't forward that port to the internet.

## Limits

- x86-64 only: Bambu Studio is published for x86-64 Linux, so not on a Raspberry Pi.
- It slices with the profile's own settings, converted to your printer when the profile was made for another one.
