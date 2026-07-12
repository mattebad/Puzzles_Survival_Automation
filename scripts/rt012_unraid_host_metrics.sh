#!/bin/sh
set -eu

OUTPUT=$1
VM_NAME=$2
DURATION_HOURS=${3:-4}
INTERVAL_SECONDS=${4:-300}

mkdir -p "$OUTPUT/host"
START_EPOCH=$(date +%s)
DEADLINE=$((START_EPOCH + DURATION_HOURS * 3600))
SAMPLE=0
ERRORS=0

printf '%s\n' "{\"collector\":\"rt012_unraid_host_metrics.sh\",\"pid\":$$,\"uid\":$(id -u),\"user\":\"$(id -un)\",\"started_at\":\"$(date -Iseconds)\",\"expected_end_epoch\":$DEADLINE,\"output\":\"$OUTPUT\",\"interval_seconds\":$INTERVAL_SECONDS}" > "$OUTPUT/host-metrics-identity.json"

while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    SAMPLE=$((SAMPLE + 1))
    PATH_OUT=$(printf '%s/host/host-%05d.txt' "$OUTPUT" "$SAMPLE")
    {
        printf '%s\n' '--- sample ---'
        printf 'sample=%s captured_at=%s elapsed_seconds=%s\n' "$SAMPLE" "$(date -Iseconds)" "$(( $(date +%s) - START_EPOCH ))"
        printf '%s\n' '--- domain state ---'
        virsh domstate "$VM_NAME" 2>&1
        printf '%s\n' '--- domain stats ---'
        virsh domstats --state --cpu-total --balloon --block --interface "$VM_NAME" 2>&1
        printf '%s\n' '--- domain address ---'
        virsh domifaddr "$VM_NAME" --source lease 2>&1
        printf '%s\n' '--- memory and load ---'
        free -m 2>&1
        cat /proc/loadavg 2>&1
        printf '%s\n' '--- cache filesystem ---'
        df -B1 /mnt/cache 2>&1
        du -sb "$OUTPUT" 2>&1
        printf '%s\n' '--- sensors ---'
        sensors 2>&1
        printf '%s\n' '--- docker health ---'
        docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' 2>&1
        docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>&1
        printf '%s\n' '--- listeners ---'
        ss -lntp 2>&1
        printf '%s\n' '--- routes ---'
        ip route 2>&1
        printf '%s\n' '--- recent kernel warnings/errors ---'
        dmesg --level=err,warn -T 2>&1 | tail -n 100
        printf '%s\n' '--- GPU sample ---'
        GPU_JSON="$OUTPUT/.gpu-$SAMPLE.json"
        GPU_ERR="$OUTPUT/.gpu-$SAMPLE.err"
        timeout 6s intel_gpu_top -J -s 1000 -o "$GPU_JSON" >/dev/null 2>"$GPU_ERR" || true
        cat "$GPU_JSON" 2>&1 || true
        cat "$GPU_ERR" 2>&1 || true
        rm -f "$GPU_JSON" "$GPU_ERR"
    } > "$PATH_OUT" 2>&1 || ERRORS=$((ERRORS + 1))

    if [ "$(du -sb "$OUTPUT" | awk '{print $1}')" -gt $((512 * 1024 * 1024)) ]; then
        printf '%s\n' 'evidence quota reached' >> "$OUTPUT/host-metrics.log"
        break
    fi

    NEXT=$((START_EPOCH + SAMPLE * INTERVAL_SECONDS))
    NOW=$(date +%s)
    if [ "$NEXT" -gt "$NOW" ]; then
        sleep $((NEXT - NOW))
    fi
done

printf '%s\n' "{\"collector\":\"rt012_unraid_host_metrics.sh\",\"pid\":$$,\"ended_at\":\"$(date -Iseconds)\",\"samples\":$SAMPLE,\"errors\":$ERRORS,\"expected_end_epoch\":$DEADLINE}" > "$OUTPUT/host-metrics-summary.json"
