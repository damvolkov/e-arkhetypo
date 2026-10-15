# openhuman-core:house — the layer over the core image build.sh makes from the source tree. It only adds
# what running against the host's own files needs: the host's user (no chown ever — the entrypoint skips
# its heal when it starts non-root) owning the bundled modules (the loader refuses a module dir another
# user owns) and a writable cache, git (the git_operations tool), and the desktop's way of finding its config.
ARG BASE=openhuman-core:demian
FROM ${BASE}
ARG HOST_USER=openhuman
ARG HOST_HOME=/home/openhuman
ARG HOST_UID=1000
ARG HOST_GID=1000
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && (getent group ${HOST_GID} || groupadd -g ${HOST_GID} ${HOST_USER}) \
 && (getent passwd ${HOST_UID} || useradd -u ${HOST_UID} -g ${HOST_GID} -M -d ${HOST_HOME} -s /bin/bash ${HOST_USER}) \
 && install -d -o ${HOST_UID} -g ${HOST_GID} ${HOST_HOME} ${HOST_HOME}/.cache \
 && chown -R ${HOST_UID}:${HOST_GID} /opt/openhuman/bundled-modules
USER ${HOST_UID}:${HOST_GID}
# The flows' code nodes inherit this PATH: python3 is the host's uv interpreter, mounted :ro from ~/.local.
ENV HOME=${HOST_HOME} \
    PATH=${HOST_HOME}/.local/bin:$PATH \
    OPENHUMAN_KEYRING_BACKEND=file
# The base pins OPENHUMAN_WORKSPACE to its own dir; set, it bypasses active_user.toml and the core boots
# signed out on an empty config. Unset, it resolves like the desktop: $HOME/.openhuman → users/<id>/.
ENTRYPOINT ["/usr/bin/env", "-u", "OPENHUMAN_WORKSPACE", "/usr/local/bin/docker-entrypoint-core.sh"]
CMD ["serve"]
