# MyScoutee Admin

Small Linux monitor for private admin statistics and notifications. The browser window attaches to one local background process; closing/reopening it keeps the connection alive.

| 1.0.2 | Download |
| --- | --- |
| Linux installer (Debian/Ubuntu) | [myscoutee-client-admin_1.0.2_all.deb](https://github.com/fssrepository/myscoutee-client-admin/releases/download/v1.0.2/myscoutee-client-admin_1.0.2_all.deb) |
| Private API and operation guide | [PDF](docs/admin-client-api.pdf) · [Source](docs/admin-client-api.md) |

```sh
sudo apt install ./myscoutee-client-admin_1.0.2_all.deb
myscoutee-client-admin
```

Copy the **API URL and key** from your admin profile, choose live/demo data and click **Connect**. Polling defaults to **10 seconds** and is adjustable (5–3600 seconds). **Disconnect** clears the key. Open MyScoutee and sign in to handle messages/reports; this monitor exposes no case content or moderation actions. Private downloads require GitHub repository access.

The key stays in RAM, never in saved preferences. Remote URLs require HTTPS; localhost HTTP supports the dev stack. The installer includes Ubuntu notification-center support (`notify-send`) and a desktop-login autostart entry. Closing the window preserves an existing connection. **Disconnected means no polling or notifications.** After logout/reboot the background process starts disconnected; reconnect with your key, which is never stored on disk. Desktop Do Not Disturb settings are respected.

| Development / lifecycle | Command |
| --- | --- |
| Run from source | `python3 admin_monitor.py` |
| Stop the background process | `myscoutee-client-admin --stop` |
| Tests | `python3 -m unittest discover -s tests -v` |
| Build installer | `tools/build_deb.sh` |
| Release | Tag `v1.0.2`; the private GitHub Actions workflow builds and uploads the installer and PDF. |

## Documentation

[API reference, metric definitions and lifecycle](docs/admin-client-api.md). Stats show the server snapshot time; registrations are the last 7/30 UTC calendar days including today. Chrome/Chromium opens a compact app window when installed; other browsers open the same local UI normally. No embedded Chromium/GTK runtime is installed.

Next release: **1.3.0**, Git tag `v1.3.0`. The download links above refer to the existing 1.0.2 release until 1.3.0 is published.
