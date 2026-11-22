# Daybook CRM: a 10-minute demo script

Open the Windows app (Start menu → **Daybook CRM**) or the Android app. The welcome screen offers four languages; pick one and press **Demoni boshlash**. Nothing can break: Settings → Data → *Reset demo data* rebuilds the company for today.

## 1. The morning (Home), 1 minute
- The greeting and today's line: tasks due, and how many customers run out of medicine this week.
- KPIs with trends: revenue this month vs last month, active customers, weighted pipeline, refills due.
- **Smart insights.** Each card is one click to the action: refills in 3 days, quiet deals, chats waiting over 30 minutes, waitlist items that arrived, overdue tickets and adverse reactions, VIPs slipping away, birthdays, cold leads, overdue invoices.
- My day: tick a task and it's done. Then the refill radar ("remind all" sends Telegram reminders) and the inbox.

## 2. A customer (Customer 360), 2 minutes
Search with **Ctrl+K**: type a name, a phone fragment or a card number.
- Tier, RFM segment, LTV, points, and the churn-risk ring.
- **Medicines:** the regular therapies with the next due date. The consent rules are visible, and every view of health data lands in the audit log.
- **Next best actions:** remind about a refill, birthday bonus, tier upgrade, consent. Each is one click.
- Loyalty card with tier gradient, points ledger, timeline.

## 3. The pharmacy-only features, 2 minutes
- **Refill radar:** who runs out of which medicine, day by day, with stock at their branch. Remind, reserve or call.
- **Defektura waitlist:** what customers asked for and we didn't have, with "demand we lost" in so‘m and "send the list to Daybook purchasing".
- **Tickets:** SLA timers. An adverse reaction gets the 4-hour rule and the pharmacovigilance form; batch-aware complaints show who else bought that batch.

## 4. Sales, 1 minute
- **Deals:** drag a card between stages. Quiet ("rotting") deals are marked, with a forecast and lost reasons.
- From a deal: products, then **Create quote**, giving a printable quote/invoice with VAT 12%.

## 5. Marketing, 1 minute
- **Campaign:** pick a segment and it counts only customers who gave consent. A live Telegram preview on a phone mock-up. The compliance check blocks promoting prescription medicines.
- **Automations:** pharmacy recipes, such as the refill reminder, the day-3 antibiotic check-in and the 4-hour adverse-reaction rule.
- **Loyalty:** tiers, cashback, Rx excluded, the points liability.

## 6. Ask your pharmacy (AI), 1 minute
Press the ✨ button in the top bar and ask in plain words, in Uzbek, Russian or English:
- "60 yoshdan katta diabetik ayollar" gives 11 customers as a segment, with how many can be reached on Telegram. One click saves it and opens a campaign.
- "Bu hafta kimning dorisi tugaydi?" (whose medicine runs out this week?), "Qaysi filial ko‘proq sotdi?" (which branch sold most?), "Eng yaxshi mijozlar" (best customers).
Each answer is counted against the company's AI budget (Claude Haiku). In the demo, the understanding runs on the device.

## 7. Everything else, 1 minute
- **Inbox:** Telegram, SMS, WhatsApp and Instagram in one place, with templates, an AI suggested reply, internal notes and a compliance warning.
- Reports (cohorts, RFM, funnel), goals and leaderboard, team.
- **Settings:** language (Uzbek Latin and Cyrillic, Russian, English), dark theme, privacy mode, per-company rules, editable pipelines, AI budget (Haiku by default).

## 8. Connected to Daybook, 1 minute
**Settings → Daybook connection → Sign in with Telegram.** Scan the QR code (or tap the button), then tap the matching number in the owner bot. The app then pulls branches, staff, medicines and B2B customers, and pushes CRM tasks into Daybook tasks.

## Phones
- **Android:** install `DaybookCRM-<version>-android.apk` (allow installs from this source once).
- **iPhone:** a native build needs a Mac (`dx bundle --ios`). Until then, open the web build in Safari → Share → **Add to Home Screen**, which gets the same icon and works offline once loaded.
