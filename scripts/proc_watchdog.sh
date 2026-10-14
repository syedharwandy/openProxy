#!/usr/bin/env bash
# Fast process terminator and watchdog
pattern="${1:-}"
limit="${2:-5}"

if [[ -z "$pattern" ]]; then
    exit 0
fi

i=1
while true; do
    pids=$(ps aux | grep "$pattern" | grep -v grep | grep -v proc_watchdog | awk '{print $2}')
    if [[ -z "$pids" ]]; then
        exit 0
    fi
    kill -9 $pids 2>/dev/null || true
    pids=$(ps aux | grep "$pattern" | grep -v grep | grep -v proc_watchdog | awk '{print $2}')
    if [[ -z "$pids" ]]; then
        exit 0
    fi
    i=$((i + 1))
    if [[ "$i" -ge "$limit" ]]; then
        exit 1
    fi
    sleep 0.1
done
