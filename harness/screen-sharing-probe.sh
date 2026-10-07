#!/bin/bash
# Can macOS Screen Sharing be switched on on this runner at all?
#
#   bash harness/screen-sharing-probe.sh <report file>
#
# It starts Apple's own Screen Sharing service for a few seconds, asks it for
# its greeting over the loopback address, and stops it again. No tunnel is
# opened, no VNC password is set, nobody connects: a hosted runner accepts no
# connections from outside, and signing in would need the account's password,
# which nobody has. The answer only says whether an interactive session
# (docs/INTERACTIVE.md) is worth setting up.
set -uo pipefail
QA_REPORT="${1:?Usage: screen-sharing-probe.sh <report file>}"
mkdir -p "$(dirname "$QA_REPORT")"
QA_SERVICE=system/com.apple.screensharing
QA_PLIST=/System/Library/LaunchDaemons/com.apple.screensharing.plist

greeting() {
  /usr/bin/python3 - <<'PY'
import socket
try:
    with socket.create_connection(("127.0.0.1", 5900), timeout=4) as link:
        link.settimeout(4)
        print("greeting: %r" % link.recv(12))
except OSError as problem:
    print("no answer on 127.0.0.1:5900 (%s)" % problem)
PY
}

{
  echo "macOS $(sw_vers -productVersion) ($(sw_vers -buildVersion))"
  echo "== before"
  greeting
  echo "== the service's files"
  ls -l "$QA_PLIST" /System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart 2>&1
  echo "== switching it on (launchctl enable, bootstrap)"
  sudo -n launchctl enable "$QA_SERVICE" 2>&1
  sudo -n launchctl bootstrap system "$QA_PLIST" 2>&1
  sleep 3
  sudo -n launchctl print "$QA_SERVICE" 2>&1 | grep -E 'state =|active count|path =' | head -6
  greeting
  echo "== switching it off again"
  sudo -n launchctl bootout "$QA_SERVICE" 2>&1
  sudo -n launchctl disable "$QA_SERVICE" 2>&1
  sleep 2
  greeting
} > "$QA_REPORT" 2>&1
cat "$QA_REPORT"
if grep -q "greeting: b'RFB" "$QA_REPORT"; then
  echo "Screen Sharing answered on the loopback address: an interactive session is technically possible on this runner."
else
  echo "Screen Sharing did not answer: an interactive session would need another way in."
fi
