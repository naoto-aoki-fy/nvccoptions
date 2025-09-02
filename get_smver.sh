#!/bin/bash

SCRIPT_DN="$(dirname "${BASH_SOURCE[0]}")"

ETC_MACHINEID="/etc/machine-id"
if [[ -f "$ETC_MACHINEID" ]]; then
    MACHINE_ID=$(cat "$ETC_MACHINEID")
else
    MACHINE_ID="$(hostname -I)"
fi
SMVER_PATH="${SCRIPT_DN}/smver.${MACHINE_ID}.txt"

if [[ -f "$SMVER_PATH" ]]; then
    cat "$SMVER_PATH"
else
    nvidia-smi --query-gpu=compute_cap --format=csv,noheader \
    | awk '{print $1*10;}' \
    | tee "$SMVER_PATH"
fi