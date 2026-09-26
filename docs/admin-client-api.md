# Private admin client API · 1.3.0

This interface is for the private MyScoutee admin monitor. It is separate from the affiliate/import API and exposes no administrative mutation or message body.

## Connect

Obtain a key in the admin profile's **API** popup. Enter the displayed base URL and key in the Linux app. Choose demo data only for the matching demo account/key. Examples:

- Local dev: `http://localhost/api/admin-client/v1`
- Remote: `https://YOUR_HOST/api/admin-client/v1`

Remote URLs require HTTPS. Do not put credentials in URLs. The installed client requires Python 3.10+, a browser and xdg-utils; `notify-send` provides desktop notifications when available. The package recommends libnotify-bin. An installed Chrome/Chromium opens an app window without its tab bar; otherwise the default browser opens the same local UI. No embedded GUI toolkit or browser engine is bundled.

## Request

`GET {baseUrl}/overview`

| Header | Value |
| --- | --- |
| Authorization | `Bearer <admin-client key>` |
| X-MyScoutee-Client-Id | Stable UUID persisted by this client installation |
| X-App-Session-Kind | `demo` only when using demo data; omitted for real data |

A key is scoped to admin-client, has expiry/revocation and is bound to the first client UUID. Each poll rechecks that its owner is still an active administrator. Affiliate keys are rejected; admin-client keys cannot use the affiliate API. The key is entered once per daemon lifetime and kept only in RAM. Do not delete the client identity preferences while retaining a claimed key: create a new key for a new installation.

## Response

| Field | Meaning |
| --- | --- |
| statistics.ready | Whether the active-profile breakdown has been generated |
| statistics.generatedAtIso | UTC timestamp of the server statistics snapshot |
| statistics.activeProfiles | Active nonstaff profile count |
| statistics.genders | female / male / other-or-unspecified counts among active profiles |
| statistics.registrations7Days | Registration telemetry across last 7 UTC calendar dates, including today |
| statistics.registrations30Days | Same definition, last 30 dates; includes the 7-day interval |
| attention.unreadMessages | Current admin's unread chat counter |
| attention.unreadVersion | Opaque incoming unread-change marker; not message content |
| attention.unresolvedReports | Unresolved user reports |
| attention.unresolvedFeedback | Unresolved user feedback |
| attention.supportCases | Pending/warned/picked support cases |
| attention.failedJobs | Stored failed-Job attention counter |

Active means profile visibility public, friends only or host only. Inactive, deleted and blocked profiles are excluded, including automatic deactivation. This is not an online-now or daily-login metric. First activity is not treated as registration. Statistics reuse the existing server telemetry snapshot; ten-second polling does not make a minute-old snapshot live. Historical periods without recorded telemetry cannot be reconstructed by the client.

401 means missing, invalid, expired, revoked, wrong-scope or differently claimed credentials. 403 means removed/inactive administrator access. Either disconnects the monitor and clears the key. Transient network/server failures retain the last successful snapshot with an error and retry on the selected interval. Responses use `Cache-Control: no-store`.

## Lifecycle and notification watcher

Default remote polling: 10 seconds, configurable between 5 and 3600. One worker performs sequential requests with a 15-second network timeout. No overlapping requests or blind immediate retries. The browser refreshes the local process state separately.

A first successful poll establishes a baseline. New incoming unread state or an increased action count emits a generic desktop alert; identical polls and decreases do not. No chat content appears in alerts. Notifications depend on the desktop's notification service; the visible counts remain available without it. Handling any case requires signing into MyScoutee.

Closing the browser does not stop the process. Reopening attaches to the same process and connection. Disconnect clears credentials/data and discards in-flight responses. `myscoutee-client-admin --stop` ends the process; after a reboot/stop, paste the key again. Preferences hold URL, interval, language, demo mode and client UUID, never the API key.

The local UI binds only to 127.0.0.1 on a random port. A per-instance control capability and origin/Host checks protect its API. Runtime/preferences files are private to the OS user. TLS validation remains enabled and redirects never receive the bearer key. Other processes running as the same OS user are outside this isolation boundary.

## Build and release

`tools/build_deb.sh` builds `dist/myscoutee-client-admin_1.3.0_all.deb`. Install with `sudo apt install ./myscoutee-client-admin_1.3.0_all.deb`. The private repository's `v1.3.0` workflow uploads the installer and this PDF to GitHub Releases. Repository access is required for downloads. Uninstall using the package manager; stop the monitor first. Per-user preferences remain until explicitly removed.

Automated application QA is tracked in the backend repository under `guides/qa/checklists/api/ADMIN-CLIENT-API-001.md`.

## Desktop startup and notifications

The Debian package installs an XDG desktop-login autostart entry invoking the same singleton launcher with `--no-open`. No cron process, second daemon or automatic browser window is created. Desktop notifications use the Ubuntu notification center with the application icon and desktop-entry identity. Polling and alerts run only while connected; Disconnect stops both. Closing the window leaves the connection alive. Logout/reboot clears the in-memory key, so the next desktop session starts disconnected until Connect is used again. The operating system controls Do Not Disturb and notification retention.
