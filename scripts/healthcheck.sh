#!/bin/sh
# Local liveness only: no credentials, redirects, proxy or external-system checks.
set -eu

scheme=${JENKINS_HEALTH_SCHEME:-http}
port=${JENKINS_HEALTH_PORT:-8080}
path=${JENKINS_HEALTH_PATH:-/login}
case "$scheme" in http|https) ;; *) exit 1 ;; esac
case "$port" in ''|*[!0-9]*) exit 1 ;; esac
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || exit 1
case "$path" in /*) ;; *) exit 1 ;; esac

set -- --silent --show-error --noproxy '*' --connect-timeout 3 --max-time 8 --output /dev/null --write-out '%{http_code}'
# Loopback HTTPS may use a private CA or a hostname-only certificate. No secret is sent.
if [ "$scheme" = https ]; then
    set -- "$@" --insecure
fi
status=$(curl "$@" "$scheme://127.0.0.1:$port$path") || exit 1
case "$status" in
    200|301|302|303|307|308|401|403) exit 0 ;;
    *) exit 1 ;;
esac
