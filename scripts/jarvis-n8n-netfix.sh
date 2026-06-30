#!/bin/bash
# Watchdog: ensure n8n-n8n-1 stays on jarvis-net after restarts.
# Installed as cron: * * * * * /usr/local/bin/jarvis-n8n-netfix.sh
CONTAINER="n8n-n8n-1"
NETWORK="jarvis-net"

if ! docker inspect "$CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q "true"; then
    exit 0
fi

if docker network inspect "$NETWORK" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | grep -q "$CONTAINER"; then
    exit 0
fi

docker network connect "$NETWORK" "$CONTAINER" 2>/dev/null && \
    echo "$(date): reconnected $CONTAINER to $NETWORK" >> /var/log/jarvis-netfix.log
