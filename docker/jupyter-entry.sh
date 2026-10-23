#!/bin/sh
# Lab notebook server. Token defaults to empty and compose publishes the port
# on 127.0.0.1 only. Set JUPYTER_TOKEN if the port is reachable by anyone else.
set -eu
token=${JUPYTER_TOKEN-}
exec jupyter notebook \
    --no-browser \
    --ServerApp.ip=0.0.0.0 \
    --ServerApp.port=8888 \
    --ServerApp.root_dir=/work \
    --ServerApp.token="$token" \
    --ServerApp.password="" \
    --ServerApp.allow_root=True \
    --ServerApp.open_browser=False
