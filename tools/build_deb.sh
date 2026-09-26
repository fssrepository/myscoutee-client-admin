#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version=1.3.0
stage_dir="$(mktemp -d)"
trap 'rm -rf -- "$stage_dir"' EXIT
install -d "$stage_dir/DEBIAN" "$stage_dir/opt/myscoutee-client-admin" "$stage_dir/usr/bin" "$stage_dir/usr/share/applications" "$stage_dir/usr/share/icons/hicolor/scalable/apps" "$project_dir/dist"
cat > "$stage_dir/DEBIAN/control" <<EOF
Package: myscoutee-client-admin
Version: $version
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), xdg-utils, libnotify-bin
Maintainer: MyScoutee
Description: Private MyScoutee administrator monitor
 Minimal browser UI with one local background polling process.
EOF
for file in admin_monitor.py index.html app.js style.css LICENSE; do
  install -m 644 "$project_dir/$file" "$stage_dir/opt/myscoutee-client-admin/$file"
done
cat > "$stage_dir/usr/bin/myscoutee-client-admin" <<'EOF'
#!/bin/sh
exec python3 /opt/myscoutee-client-admin/admin_monitor.py "$@"
EOF
chmod 755 "$stage_dir/usr/bin/myscoutee-client-admin"
install -m 644 "$project_dir/packaging/myscoutee-client-admin.desktop" "$stage_dir/usr/share/applications/"
install -m 644 "$project_dir/packaging/myscoutee-client-admin.svg" "$stage_dir/usr/share/icons/hicolor/scalable/apps/"
install -d "$stage_dir/etc/xdg/autostart"
install -m 644 "$project_dir/packaging/myscoutee-client-admin-autostart.desktop" "$stage_dir/etc/xdg/autostart/"
dpkg-deb --root-owner-group --build "$stage_dir" "$project_dir/dist/myscoutee-client-admin_${version}_all.deb"
