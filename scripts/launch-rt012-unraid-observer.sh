#!/bin/sh
set -eu

OUTPUT=$1
OBSERVER_SCRIPT=$2
ADB_PATH=$3
SERIAL=${4:-192.168.122.79:5555}
VM_NAME=${5:-PnS-BlissOS-PoC}
DURATION_HOURS=${6:-4}
INTERVAL_SECONDS=${7:-300}
IMAGE=${8:-monarch-gpt-wrapper-api:latest}
CONTAINER_NAME=${9:-rt012-observer}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)

mkdir -p "$OUTPUT" "$OUTPUT/host"
if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
    echo "refusing to reuse existing container name: $CONTAINER_NAME" >&2
    exit 1
fi
chown 65534:65534 "$OUTPUT"

STARTED_AT=$(date -Iseconds)
IMAGE_ID=$(docker image inspect --format '{{.Id}}' "$IMAGE")
cat > "$OUTPUT/supervisor-identity.json" <<EOF
{"supervisor_pid":$$,"started_at":"$STARTED_AT","expected_end_at":"$(date -d "+$DURATION_HOURS hours" -Iseconds)","output":"$OUTPUT","container_name":"$CONTAINER_NAME","image":"$IMAGE","image_id":"$IMAGE_ID","observer_script":"$OBSERVER_SCRIPT","adb_path":"$ADB_PATH","serial":"$SERIAL","vm_name":"$VM_NAME","duration_hours":$DURATION_HOURS,"interval_seconds":$INTERVAL_SECONDS,"evidence_quota_mib":512}
EOF

CONTAINER_ID=$(docker run -d \
    --name "$CONTAINER_NAME" \
    --network host \
    --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
    --user 65534:65534 \
    --cap-drop=ALL \
    --security-opt no-new-privileges \
    --pids-limit 128 \
    --memory 512m \
    --cpus 1 \
    --stop-timeout 30 \
    --mount "type=bind,source=$OUTPUT,target=/evidence" \
    --mount "type=bind,source=$OBSERVER_SCRIPT,target=/tmp/rt012_observer.py,readonly" \
    --mount "type=bind,source=$ADB_PATH,target=/opt/adb,readonly" \
    --env ADB_SERVER_SOCKET=tcp:127.0.0.1:5037 \
    --env HOME=/tmp \
    --entrypoint python3 \
    "$IMAGE" \
    /tmp/rt012_observer.py \
    --output /evidence \
    --adb /opt/adb \
    --serial "$SERIAL" \
    --duration-hours "$DURATION_HOURS" \
    --interval-seconds "$INTERVAL_SECONDS" \
    --max-evidence-mib 512 \
    --vm-name "$VM_NAME" \
    --launch-game)

cat > "$OUTPUT/container-identity.json" <<EOF
{"container_id":"$CONTAINER_ID","container_name":"$CONTAINER_NAME","started_at":"$STARTED_AT","user":"65534:65534","network":"host (loopback ADB only; no published listener)","image":"$IMAGE","image_id":"$IMAGE_ID","observer_script":"$OBSERVER_SCRIPT"}
EOF
docker inspect "$CONTAINER_ID" > "$OUTPUT/container-inspect-start.json"

setsid "$SCRIPT_DIR/rt012_unraid_host_metrics.sh" "$OUTPUT" "$VM_NAME" "$DURATION_HOURS" "$INTERVAL_SECONDS" </dev/null >> "$OUTPUT/host-metrics-launch.log" 2>&1 &
METRICS_PID=$!
printf '%s\n' "$METRICS_PID" > "$OUTPUT/host-metrics.pid"

set +e
docker wait "$CONTAINER_ID" > "$OUTPUT/container-exit.txt" 2>&1
CONTAINER_WAIT_EXIT=$?
wait "$METRICS_PID"
METRICS_WAIT_EXIT=$?
set -e

docker inspect "$CONTAINER_ID" > "$OUTPUT/container-inspect-end.json" 2>&1 || true
docker rm "$CONTAINER_ID" > "$OUTPUT/container-remove.txt" 2>&1 || true
printf '%s\n' "{\"ended_at\":\"$(date -Iseconds)\",\"container_wait_exit\":$CONTAINER_WAIT_EXIT,\"metrics_wait_exit\":$METRICS_WAIT_EXIT}" > "$OUTPUT/supervisor-summary.json"
