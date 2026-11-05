#!/bin/bash
# Builds menubar/HeaterBar.app (no Xcode needed, Command Line Tools are enough).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/HeaterBar.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.officeheater.bar</string>
  <key>CFBundleName</key><string>HeaterBar</string>
  <key>CFBundleExecutable</key><string>HeaterBar</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
EOF
swiftc -O -parse-as-library -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
  "$HERE/HeaterBar.swift" -o "$APP/Contents/MacOS/HeaterBar"
codesign --force --sign - "$APP" >/dev/null 2>&1 || true
echo "Built $APP"
