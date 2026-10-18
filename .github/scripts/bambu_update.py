"""Moves the add-on to Bambu Studio's latest release: python3 .github/scripts/bambu_update.py [release.json]

Reads the release (GitHub's API JSON; fetched when no file is given), and when it's newer than the Dockerfile's, updates
the Dockerfile, bumps the add-on's patch version and adds a changelog entry. Prints "version=<new Bambu version>" and
"addon=<new add-on version>" (for $GITHUB_OUTPUT) when it changed something, nothing when already current.
"""
import json
import re
import sys
import urllib.request

ROOT = sys.argv[2] if len(sys.argv) > 2 else "."
DOCKERFILE = f"{ROOT}/pandy_slicer/Dockerfile"
CONFIG = f"{ROOT}/pandy_slicer/config.yaml"
CHANGELOG = f"{ROOT}/pandy_slicer/CHANGELOG.md"
# The add-on's base image is Ubuntu 24.04: its AppImage is the one that runs there.
ASSET = re.compile(r"BambuStudio_ubuntu24\.04-v[\d.]+-\d+\.AppImage")


def latest(path):
    if path:
        with open(path) as f:
            return json.load(f)
    with urllib.request.urlopen("https://api.github.com/repos/bambulab/BambuStudio/releases/latest", timeout=30) as r:
        return json.load(r)


def numbers(v):
    return tuple(int(p) for p in v.split("."))


def main():
    release = latest(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "-" else None)
    if release.get("draft") or release.get("prerelease"):
        return
    version = release["tag_name"].lstrip("v")
    asset = next((a["name"] for a in release.get("assets", []) if ASSET.fullmatch(a["name"]) and f"-v{version}-" in a["name"]), None)
    docker = open(DOCKERFILE).read()
    current = re.search(r"^ARG BAMBU_VERSION=(\S+)$", docker, re.M).group(1)
    if numbers(version) <= numbers(current):
        return
    if asset is None:
        sys.exit(f"Bambu Studio {version} has no Ubuntu 24.04 AppImage: {[a['name'] for a in release.get('assets', [])]}")
    docker = re.sub(r"^ARG BAMBU_VERSION=\S+$", f"ARG BAMBU_VERSION={version}", docker, flags=re.M)
    docker = re.sub(r"^ARG BAMBU_ASSET=\S+$", f"ARG BAMBU_ASSET={asset}", docker, flags=re.M)
    open(DOCKERFILE, "w").write(docker)

    config = open(CONFIG).read()
    old = re.search(r'^version: "(\d+)\.(\d+)\.(\d+)"$', config, re.M)
    addon = f"{old.group(1)}.{old.group(2)}.{int(old.group(3)) + 1}"
    open(CONFIG, "w").write(config.replace(old.group(0), f'version: "{addon}"'))

    log = open(CHANGELOG).read()
    entry = f"## {addon}\n\n- Bambu Studio {version}.\n\n"
    open(CHANGELOG, "w").write(log.replace("# Changelog\n\n", f"# Changelog\n\n{entry}", 1))
    print(f"version={version}\naddon={addon}")


if __name__ == "__main__":
    main()
