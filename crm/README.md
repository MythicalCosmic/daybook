# Daybook CRM

The CRM companion of Daybook, built for pharmacy chains. **One Rust codebase** ([Dioxus 0.7](https://dioxuslabs.com)) runs on **Windows, Android, iPhone, macOS, Linux and the web**. It works fully offline on the device and connects to a Daybook server for real branches, staff, medicines and tasks.

The app opens on a demo company called **Oydin Farm**. It's a fictional chain with 6 Tashkent branches, 16 staff, 320 customers, about 4,000 purchases, B2B clinics and companies, deals, chats, campaigns, tickets and a defektura waitlist. The demo is generated relative to today, so refills fall due this week and leads arrived this morning.

## What's inside

| Area | Highlights |
|---|---|
| Home | Greeting with today's numbers; KPIs with trends; 30-day and 12-month revenue chart; smart insights (refills due, quiet deals, waiting chats, arrived waitlist items, SLA breaches, VIPs slipping away, birthdays, cold leads, overdue invoices); my day; refill radar; inbox; Daybook status |
| Customers | Customer 360 (purchases, medicines and refills, loyalty card and ledger, timeline, notes, consents, next best actions, AI summary); companies (B2B: credit, debts, health); leads ("unsorted" inbox with scoring and convert); segments (rule builder, RFM matrix) |
| Sales | Deal pipelines (kanban with drag and drop, quiet-deal warnings, forecast, lost reasons); quotes and invoices (printable, VAT 12%); medicine catalogue with stock per branch and expiry |
| Marketing | Telegram/SMS campaigns with consent filtering, phone preview and Rx compliance checks; automations with pharmacy recipes (refill reminder, day-3 antibiotic check-in, the 4-hour adverse-reaction rule, birthday, win-back); loyalty (tiers, cashback, Rx excluded, liability) |
| Care | **Refill radar** (who runs out of which medicine, by day); **defektura waitlist** tied to stock ("demand we lost" in so‘m); tickets with SLA, pharmacovigilance form and batch-aware complaints |
| Insights | Reports (sales, cohorts, RFM, pipeline, campaigns, service, team), goals and leaderboard, team |
| AI | "Ask your pharmacy": questions in Uzbek, Russian or English become segments, lists and numbers, counted against the company's AI budget (Claude Haiku); AI summaries and next best actions on every customer; suggested replies in the inbox |
| Everywhere | Command palette (Ctrl+K); quick add; notifications; 4 languages (O‘zbekcha, Ўзбекча generated automatically, Русский, English); light, dark and system themes; privacy mode (masks phones and health data); a phone layout with a tab bar; health-data access written to the audit log |

The research behind the feature list is in [docs/RESEARCH.md](docs/RESEARCH.md).

## Layout

```
crm/
  core/   data model, demo company, analytics, formatting, translations (pure Rust, unit-tested)
  app/    Dioxus app: shell, design system (assets/app.css), screens (src/pages), Daybook client
  tools/  build image, cargo queue, installer, packaging and screenshot scripts
```

## Building

Everything builds in one Docker image, so the Windows machine needs nothing but Docker Desktop:

```powershell
docker build -f crm/tools/build.Dockerfile --target android -t daybook-crm-android crm/tools
docker run -d --name crm-build --cpus 5 -v "${PWD}:/src" -v crm-cargo-registry:/usr/local/cargo/registry -v crm-target:/target -p 127.0.0.1:28380-28389:28380-28389 -w /src/crm daybook-crm-android sleep infinity
```

| Target | Command (inside `crm-build`) | Output |
|---|---|---|
| Web | `cd /src/crm && dx build --platform web -p daybook-crm` (add `--release` for production) | `/target/dx/daybook-crm/*/web/public` |
| Windows | `CARGO_TARGET_DIR=/target/win cargo build --release -p daybook-crm --no-default-features --features desktop --target x86_64-pc-windows-gnu`, then `CARGO_TARGET_DIR=/target/win sh /src/crm/tools/package-windows.sh 0.1.0` | `/target/dist/win/DaybookCRM-Setup-0.1.0.exe` and a portable zip |
| Android | `cd /src/crm/app && dx bundle --android --release --target aarch64-linux-android --package-types apk --out-dir /target/dist/android` | APK |
| iPhone / iPad | On a Mac with Xcode: `cd crm/app && dx bundle --ios --release` (sign with the team's Apple ID) | `.ipa` |
| macOS / Linux | `dx bundle --desktop --release` on that OS | `.dmg` / `.AppImage` / `.deb` |

Until a Mac build is signed, iPhone users can open the web build in Safari and use **Share → Add to Home Screen**. The page carries the app icon and full-screen meta tags.

Notes:
- Android: `dx bundle --android` regenerates the Gradle project each time. Run `tools/package-android.sh` afterwards: it sets the name "Daybook CRM" and the launcher icon, then rebuilds the APK (debug-signed, so it installs directly; a Play Store release needs a release key). If `cargo` is wrapped, as with the queue below, export `CC_aarch64_linux_android=$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android24-clang` so `ring` finds the NDK compiler.
- The Windows build is cross-compiled with MinGW. It loads WebView2 through `WebView2Loader.dll`, which the installer and the portable zip ship next to the exe. WebView2 is built into Windows 11; the installer offers Microsoft's download page if it's missing.
- The installer is per-user (`%LOCALAPPDATA%\Programs\Daybook CRM`), so it needs no admin rights. Customer data lives in `%LOCALAPPDATA%\Daybook CRM` and survives reinstalling.
- Inside the container, heavy cargo commands queue behind one lock (`tools/cargo-queue.sh`), so parallel builds don't overheat a laptop.
- Web screenshots for design reviews: `crm/tools/shot.ps1` uses headless Edge. Add `?theme=dark&lang=ru` to the URL to choose the theme and language and skip the welcome screen.

## Daybook connection

**Settings → Daybook connection** uses the same API as the owner dashboard:
1. `GET /health/` shows the server status and version.
2. **Sign in with Telegram.** `POST /api/v1/owner/auth/login-links/` returns a t.me deep link, shown as a QR code, and a two-digit number to match in the owner bot. The app polls with `X-Login-Poll` until the owner approves, then `claim` returns the access token and the `owner_refresh` cookie. Tokens stay on the device and refresh automatically. On local dev servers, a developer sign-in (Telegram id) is offered instead.
3. **Sync** pulls branches, people, medicines (`stock/products`), B2B customers (`sales/customers`) and the defektura count. It pushes CRM tasks marked "also in Daybook" to Daybook tasks, assigned to the matching person or else to the branch.

The browser build can't call the server directly (that would need CORS on the server). The Windows and Android apps connect.

## Tests

```sh
cargo test -p daybook-crm-core   # formatting, plurals, Cyrillic, demo consistency (totals match purchases), story numbers
cargo test -p daybook-crm        # no duplicate translation keys
```
