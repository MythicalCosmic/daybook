#!/bin/sh
# Brands the Android project that `dx bundle --android` generated (app name, launcher icon)
# and rebuilds the APK with Gradle. Runs inside the crm-build container after:
#   cd /src/crm/app && dx bundle --android --release --target aarch64-linux-android --package-types apk --out-dir /target/dist/android
# usage: CARGO_TARGET_DIR=/target/android sh crm/tools/package-android.sh [version]
set -e
VERSION="${1:-0.1.0}"
P="${CARGO_TARGET_DIR:-/target/android}/dx/daybook-crm/release/android/app"
ICONS=/src/crm/app/assets/icons
RES="$P/app/src/main/res"

sed -i 's|<string name="app_name">[^<]*</string>|<string name="app_name">Daybook CRM</string>|' "$RES/values/strings.xml"

# Legacy icons (Android 7) and adaptive-icon foreground layers (Android 8+), per density.
for d in mdpi:48:108 hdpi:72:162 xhdpi:96:216 xxhdpi:144:324 xxxhdpi:192:432; do
  name=${d%%:*}; rest=${d#*:}; legacy=${rest%%:*}; fg=${rest#*:}
  mkdir -p "$RES/mipmap-$name"
  rm -f "$RES/mipmap-$name"/ic_launcher*.webp "$RES/mipmap-$name"/ic_launcher*.png
  convert "$ICONS/icon-1024.png" -resize "${legacy}x${legacy}" "$RES/mipmap-$name/ic_launcher.png"
  convert "$ICONS/android-foreground.png" -resize "${fg}x${fg}" "$RES/mipmap-$name/ic_launcher_foreground.png"
done
rm -f "$RES/drawable-v24/ic_launcher_foreground.xml"
cat > "$RES/drawable/ic_launcher_background.xml" <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<shape xmlns:android="http://schemas.android.com/apk/res/android" android:shape="rectangle">
    <gradient android:type="linear" android:angle="315" android:startColor="#E08F57" android:centerColor="#B2622D" android:endColor="#7A3D17" />
</shape>
EOF
cat > "$RES/mipmap-anydpi-v26/ic_launcher.xml" <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@drawable/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
EOF

cd "$P"
./gradlew assembleDebug --offline -q
mkdir -p /target/dist/android
cp app/build/outputs/apk/debug/app-debug.apk "/target/dist/android/DaybookCRM-$VERSION-android.apk"
/opt/android-sdk/build-tools/35.0.0/aapt dump badging "/target/dist/android/DaybookCRM-$VERSION-android.apk" | grep -E "^package|^application-label:|launchable"
ls -la /target/dist/android
