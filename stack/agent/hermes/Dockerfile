# House layer over the pinned Hermes image: libopus, without which Discord voice-channel playback stays disabled.
ARG HERMES_IMAGE
FROM ${HERMES_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libopus0 && rm -rf /var/lib/apt/lists/*
