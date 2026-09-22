#!/bin/bash
# Read-only survey of the server. Changes nothing, installs nothing.
# Run as root on the cPanel box:   bash deploy/check-server.sh
# Paste the whole output back.

echo "=================================================================="
echo " Bitcoin vs The Moon - server survey    $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "=================================================================="

echo
echo "--- OS --------------------------------------------------------"
[ -f /etc/redhat-release ] && cat /etc/redhat-release
[ -f /etc/os-release ] && grep -E '^(PRETTY_NAME|NAME|VERSION)=' /etc/os-release
echo "kernel: $(uname -r)   arch: $(uname -m)"

echo
echo "--- Web server ------------------------------------------------"
if systemctl is-active --quiet lsws 2>/dev/null; then
  echo "LiteSpeed: RUNNING"
  /usr/local/lsws/bin/lshttpd -v 2>/dev/null | head -2
elif systemctl is-active --quiet httpd 2>/dev/null; then
  echo "Apache httpd: RUNNING (not LiteSpeed)"
  httpd -v 2>/dev/null | head -2
else
  echo "Neither lsws nor httpd reported active. Checking what exists:"
  systemctl list-units --type=service --state=running 2>/dev/null \
    | grep -Ei 'lsws|httpd|apache|nginx' || echo "  (none found)"
fi
echo "proxy modules:"
httpd -M 2>/dev/null | grep -E 'proxy_module|proxy_http|headers|rewrite' \
  || echo "  httpd -M unavailable (normal on LiteSpeed; it honours the directives anyway)"

echo
echo "--- cPanel / CloudLinux ---------------------------------------"
[ -f /usr/local/cpanel/version ] && echo "cPanel: $(cat /usr/local/cpanel/version)" || echo "cPanel: not detected"
[ -f /etc/cloudlinux-release ] && cat /etc/cloudlinux-release || echo "CloudLinux: not installed (explains the missing 'Setup Python App')"
command -v selectorctl >/dev/null && echo "Python Selector: present" || echo "Python Selector: absent"

echo
echo "--- Python ----------------------------------------------------"
for p in python3 python3.13 python3.12 python3.11 python3.10 python3.9; do
  command -v $p >/dev/null && echo "  $p -> $($p -V 2>&1)"
done
echo "  venv module: $(python3 -c 'import venv; print("available")' 2>&1 | tail -1)"
echo "  pip:         $(python3 -m pip --version 2>&1 | head -1)"
command -v gcc >/dev/null && echo "  gcc: $(gcc --version | head -1)" || echo "  gcc: absent (fine - we use pure-Python MySQL driver)"

echo
echo "--- MySQL -----------------------------------------------------"
mysql --version 2>/dev/null || echo "  mysql client not on PATH"
systemctl is-active mysql 2>/dev/null || systemctl is-active mysqld 2>/dev/null \
  || systemctl is-active mariadb 2>/dev/null || echo "  no mysql/mariadb service active"

echo
echo "--- cPanel accounts & domains ---------------------------------"
if [ -x /usr/local/cpanel/bin/whmapi1 ]; then
  /usr/local/cpanel/bin/whmapi1 listaccts 2>/dev/null \
    | grep -E '^\s+(user|domain|homedir):' | sed 's/^/  /' | head -40
else
  echo "  whmapi1 unavailable; listing /var/cpanel/users:"
  ls -1 /var/cpanel/users 2>/dev/null | sed 's/^/  /' | head -20
fi

echo
echo "--- Port 8000 (the app will bind here) ------------------------"
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E ':8000\b' \
  && echo "  ^ ALREADY IN USE - we'll pick another port" \
  || echo "  free"

echo
echo "--- firewall --------------------------------------------------"
systemctl is-active --quiet csf 2>/dev/null && echo "CSF: active" || true
systemctl is-active --quiet firewalld 2>/dev/null && echo "firewalld: active" || true
echo "(only loopback:8000 is needed - no inbound rule required)"

echo
echo "=================================================================="
echo " end of survey"
echo "=================================================================="
