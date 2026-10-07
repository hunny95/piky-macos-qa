#!/bin/bash
# Builds the two QA tools on the machine that will use them:
#
#   bash harness/build-tools.sh <output folder>
#
#   <output>/qa                 the driver (events, Accessibility, screenshots)
#   <output>/TestReceiver.app   the message box that records what arrives
#
# Both are compiled here, so neither is quarantined, and ad-hoc signed.
set -euo pipefail
QA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QA_OUT="${1:?Usage: build-tools.sh <output folder>}"
mkdir -p "$QA_OUT"
QA_OUT="$(cd "$QA_OUT" && pwd)"
QA_SCRATCH="${TMPDIR:-/tmp}/piky-qa-build"
mkdir -p "$QA_SCRATCH"

swift build --package-path "$QA_ROOT/tools/qa" --scratch-path "$QA_SCRATCH/qa" -c release
cp "$(swift build --package-path "$QA_ROOT/tools/qa" --scratch-path "$QA_SCRATCH/qa" -c release --show-bin-path)/qa" "$QA_OUT/qa"

swift build --package-path "$QA_ROOT/TestReceiver" --scratch-path "$QA_SCRATCH/receiver" -c release
QA_BINARY="$(swift build --package-path "$QA_ROOT/TestReceiver" --scratch-path "$QA_SCRATCH/receiver" -c release --show-bin-path)/TestReceiver"
test -x "$QA_BINARY"

QA_APP="$QA_OUT/TestReceiver.app"
rm -rf "$QA_APP"
mkdir -p "$QA_APP/Contents/MacOS"
cp "$QA_BINARY" "$QA_APP/Contents/MacOS/TestReceiver"
cat > "$QA_APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDisplayName</key>
	<string>PIKY TestReceiver</string>
	<key>CFBundleExecutable</key>
	<string>TestReceiver</string>
	<key>CFBundleIdentifier</key>
	<string>app.getpiky.qa.testreceiver</string>
	<key>CFBundleName</key>
	<string>TestReceiver</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>LSMinimumSystemVersion</key>
	<string>14.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSPrincipalClass</key>
	<string>NSApplication</string>
</dict>
</plist>
PLIST
codesign --force --sign - "$QA_APP"
codesign --verify --strict "$QA_APP"
"$QA_OUT/qa" now >/dev/null
echo "Built $QA_OUT/qa and $QA_APP ($(lipo -archs "$QA_APP/Contents/MacOS/TestReceiver"), ad-hoc signed)"
