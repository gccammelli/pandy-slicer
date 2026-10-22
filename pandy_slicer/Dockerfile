# Pandy Slicer: Bambu Studio's command-line slicer behind a small HTTP API, for Pandy's "print this MakerWorld model".
# Runs anywhere Docker does (x86-64: Bambu Studio is published for x86-64 Linux only), and as a Home Assistant add-on.
# The base is fixed here (not Home Assistant's BUILD_FROM): Bambu Studio's AppImage needs a glibc distribution.
FROM ubuntu:26.04

ARG BAMBU_VERSION=02.08.02.61
ARG BAMBU_ASSET=BambuStudio_ubuntu24.04-v02.08.02.61-20260820225108.AppImage
# The asset's SHA-256 as GitHub reports it (the release API's "digest"): a swapped download fails the build.
ARG BAMBU_SHA256=d501b103fac5424513ec0e8d6bc145fb30719de2c7d94d7320d723740c81a7fd

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl python3 \
        libgl1 libegl1 libglu1-mesa \
        libgtk-3-0t64 libwebkit2gtk-4.1-0 libsoup-3.0-0 \
        libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
        locales fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && locale-gen en_US.UTF-8

# The AppImage unpacks without FUSE.
RUN curl -fsSL -o /tmp/bs.AppImage "https://github.com/bambulab/BambuStudio/releases/download/v${BAMBU_VERSION}/${BAMBU_ASSET}" \
    && echo "${BAMBU_SHA256}  /tmp/bs.AppImage" | sha256sum -c - \
    && chmod +x /tmp/bs.AppImage && cd /opt && /tmp/bs.AppImage --appimage-extract >/dev/null \
    && mv squashfs-root bambu-studio && rm /tmp/bs.AppImage

ENV LANG=en_US.UTF-8 BAMBU_STUDIO=/opt/bambu-studio/AppRun PANDY_SLICER_PORT=8737
COPY server.py /server.py
COPY certs /certs
# Untrusted projects are parsed by Bambu Studio, so it runs as an unprivileged user. It writes the merged printer
# presets into its own profile folders, so those belong to that user.
RUN useradd --system --create-home --uid 10001 pandy && chown -R pandy /opt/bambu-studio/resources/profiles
USER pandy
EXPOSE 8737
CMD ["python3", "-u", "/server.py"]
