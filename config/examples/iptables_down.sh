#!/usr/bin/env bash
set -euo pipefail

/sbin/iptables -t nat -F PREROUTING