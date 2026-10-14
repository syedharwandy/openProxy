#!/usr/bin/env bash
# Android Phone USB Auto-Setup for OpenProxy
# Ensures ADB daemon is running and lists connected devices
set -euo pipefail

echo "[*] Checking connected Android devices via ADB..."
adb devices -l

echo ""
echo "[*] Connected devices:"
adb devices | awk 'NR>1 && $2=="device" {print $1}'
