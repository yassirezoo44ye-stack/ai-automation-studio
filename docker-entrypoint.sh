#!/bin/sh
# Starts as root only long enough to make the project-files directory
# writable, then drops to the unprivileged "axon" user for the app itself.
#
# Why: project files (generated code, uploads, images) must live on a
# persistent disk (WORKSPACES_DIR, e.g. a Render disk at /var/data), and a
# freshly attached disk is owned by root. Without this step the app, running
# as axon, could not write there.
set -e
ws="${WORKSPACES_DIR:-/app/workspaces}"
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$ws"
  # Top level only: everything below it is created by the app as axon.
  chown axon:axon "$ws" || echo "warning: could not chown $ws" >&2
  exec setpriv --reuid=axon --regid=axon --init-groups "$@"
fi
exec "$@"
