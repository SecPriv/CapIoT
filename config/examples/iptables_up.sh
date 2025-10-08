#!/usr/bin/env bash
set -euo pipefail

/sbin/iptables -t nat -I PREROUTING -i wlp1s0 -p udp --dport 53 -j ACCEPT
/sbin/iptables -t nat -I PREROUTING -i wlp1s0 -p tcp --dport 53 -j ACCEPT
/sbin/iptables -t nat -I PREROUTING -i wlp1s0 -p udp --dport 67 -j ACCEPT
/sbin/iptables -t nat -A PREROUTING -i wlp1s0 -p tcp -s 10.42.0.70 -j REDIRECT --to-port 8080
/sbin/iptables -t nat -A PREROUTING -i wlp1s0 -p udp -s 10.42.0.70 -j REDIRECT --to-port 8080
