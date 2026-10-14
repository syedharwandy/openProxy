#!/usr/bin/env bash
# DHCP Watchdog: checks all active modem namespaces and re-triggers DHCP if connection drops
for ns in /var/run/netns/ns_modem*; do
    [[ -e "$ns" ]] || continue
    ns_name=$(basename "$ns")
    
    # Check if namespace has a default route and can reach gateway
    has_gw=$(ip netns exec "$ns_name" ip route show default 2>/dev/null || true)
    if [[ -z "$has_gw" ]]; then
        echo "[!] No gateway in ${ns_name}. Refreshing DHCP..."
        # Find network interface inside namespace
        iface=$(ip netns exec "$ns_name" ip -o link show | awk -F': ' '{print $2}' | grep -vE 'lo|veth' | head -n1)
        if [[ -n "$iface" ]]; then
            ip netns exec "$ns_name" dhclient -r "$iface" 2>/dev/null || true
            ip netns exec "$ns_name" dhclient -v "$iface" 2>/dev/null || true
        fi
    fi
done
