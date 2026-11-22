# Daybook CRM - product research

Scope: what the best CRMs do, turned into a feature map for a pharmacy-chain CRM (desktop + Android + iPhone, Rust), companion to Daybook (tasks, HR, payroll, money, stock with batches/expiry/defektura, learning, Face ID attendance, Telegram bots).

Sources: working knowledge plus 3 web searches (HubSpot Fall 2026 / Salesforce Dreamforce 2026, Veeva Vault CRM AI agents, Uzbek pharmacy CRM market). Not verified by search: Kommo/amoCRM 2026 features and Billz / Sales Doctor / Smartup pharmacy features (the search found nothing on them); those entries come from general knowledge and must be checked before we make claims in sales material.

Confirmed 2025-26 facts: HubSpot Fall 2026 redesigned Breeze Assistant (state a goal in plain words, it routes to specialist agents; Customer, Prospecting, Data agents GA; outcome-based pricing, about $0.50 per resolution). Salesforce Agentforce (about $2 per autonomous resolution, CRM-specific reasoning model, Slack-centred editions). Veeva Vault CRM AI agents (Dec 2025): Pre-call, Voice (hands-free CRM, voice notes into structured fields), Free Text (flags non-compliant call notes), Content; all inside existing permissions and audit trail. Uzbekistan CRM market by site share (wmtips): Bitrix24 about 60%, amoCRM about 19%. Pharmacy chains in the region use bonus/loyalty apps (e.g. UDS in a Tashkent chain).

## 1. CRM -> signature strengths

| CRM | Signature strengths |
|---|---|
| Salesforce | Deepest customization, Flow automation, Agentforce agents, Health/Life Sciences clouds, huge ecosystem |
| HubSpot | Easiest UX, all-in-one (marketing+sales+service), Breeze AI assistant/agents, timeline-first contact record |
| Zoho CRM | Cheap, very broad suite, Zia AI, Blueprint (enforced process stages), Canvas custom layouts |
| Pipedrive | Best visual pipeline, activity-based selling, simple automations, deal rotting |
| Dynamics 365 | Office/Teams integration, Copilot, strong service + field service, Dataverse |
| Freshsales | Built-in phone/email, Freddy AI lead scoring, clean mid-market UX |
| monday CRM | Board-style flexibility, no-code automations, dashboards anyone can build |
| Odoo CRM | Native link to inventory/accounting/POS, pharmacy industry page, multiple price lists |
| Bitrix24 | Free tier, CRM+tasks+chat+telephony+HR in one, ~60% of Uzbek market, robots/triggers |
| amoCRM / Kommo | Messenger-first (Telegram, WhatsApp, Instagram), Salesbot chat flows, "unsorted" inbound leads |
| RetailCRM | Retail loyalty, RFM segmentation, omnichannel orders, trigger campaigns, repeat-purchase logic |
| Attio | Modern data model (custom objects), auto-enriched records, collaborative lists, fast UI |
| Close | Calling/SMS/email sequences inside the CRM, power dialer, call transcription and summaries |
| Copper | Lives inside Google Workspace, near-zero data entry from email |
| Keap | Small-business automation, campaign builder, invoicing and payments in CRM |
| Creatio | No-code process + CRM, strong in banking/pharma, composable AI agents |
| SugarCRM | Customizable, predictive scoring, solid for regulated sectors |
| Twenty | Open-source, self-hostable, custom objects, API-first, Notion-like views |
| folk | Lightweight relationship CRM, groups, one-click enrichment, email sequences |
| Capsule | Simple contacts + tasks + pipeline, fast onboarding, tracks (task templates) |
| Veeva Vault CRM | Pharma-grade: HCP/HCO data model, call reporting, samples, approved content, consent capture, compliance audit trail, AI agents (pre-call, voice, free-text check) |
| IQVIA OCE | Omnichannel engagement, next-best-action orchestration, HCP reference data |
| Salesforce Health / Life Sciences Cloud | Patient 360, care plans, referral management, HCP engagement, consent objects |
| Billz / Sales Doctor / Smartup (UZ) | Uzbek retail/distribution: POS+stock+sales-rep apps, van sales, order taking, local payments, Russian/Uzbek UI; Sales Doctor and Smartup are distributor-side field sales (agents, routes, visits). Pharmacy specifics unverified |
| UDS / bonus apps (CIS) | Cashback and tier loyalty as a separate app; pharmacy owners already expect bonuses and push offers |

## 2. Feature map

Priority: P0 = demo must have, P1 = next, P2 = later.

### 2.1 Contacts / customer 360
| Feature | Inspired by | Pri |
|---|---|---|
| Unified customer card: phone-keyed profile, purchases by branch, bonus balance, notes, tags, open tasks, timeline | HubSpot, Attio, RetailCRM | P0 |
| One activity timeline (calls, chats, purchases, tickets, reminders, complaints) | HubSpot, Pipedrive | P0 |
| Dedupe and merge by phone (+998 normalization), family/household link | Zoho, Attio, RetailCRM | P0 |
| Quick-add by phone/QR from any screen, works offline on mobile | Pipedrive, Copper | P0 |
| Custom fields, tags, saved views and filters | Attio, Twenty, monday | P1 |
| Auto-computed: preferred branch, usual products, average basket, last-visit gap | Attio, RetailCRM | P1 |
| Birthday, language (uz/ru) and preferred channel | Keap, RetailCRM | P1 |
| Relationship graph (caregivers buying for a patient) | Attio, Salesforce Health | P2 |

### 2.2 Companies / B2B
| Feature | Inspired by | Pri |
|---|---|---|
| Company records with contacts, contracts, credit limit, payment terms, branch assignment | Odoo, Dynamics, HubSpot | P0 |
| Corporate price lists / discounts per company | Odoo, Zoho | P1 |
| Account hierarchy (holding -> clinics -> departments) | Salesforce, Dynamics | P1 |
| Customer-specific order templates and standing orders | Sales Doctor, Smartup | P1 |
| Receivables view (overdue invoices per client) linked to Daybook money | Odoo, Keap | P1 |
| Territory/route assignment for reps | Salesforce, Sales Doctor | P2 |

### 2.3 Leads
| Feature | Inspired by | Pri |
|---|---|---|
| Inbound lead inbox ("unsorted") from Telegram, calls, web form, QR; one tap to qualify or reject | amoCRM/Kommo | P0 |
| Lead source tracking and cost per source | HubSpot, Bitrix24 | P1 |
| Lead scoring (rules first, AI later) | Freshsales, Zoho, HubSpot | P1 |
| Round-robin / least-busy assignment per branch | Pipedrive, Bitrix24 | P1 |
| Speed-to-lead SLA with escalation | Close, Salesforce | P2 |

### 2.4 Deals and pipelines
| Feature | Inspired by | Pri |
|---|---|---|
| Kanban pipelines, several per type (B2B supply, corporate health program, clinic partnership, special order) | Pipedrive, amoCRM | P0 |
| Drag-drop stage moves with required fields per stage, lost-reason capture | Zoho Blueprint, Pipedrive | P0 |
| Deal rotting / stale highlighting | Pipedrive | P1 |
| Weighted forecast per stage | Salesforce, Pipedrive | P1 |
| Deal products and quotes from the Daybook stock catalogue | Odoo, Dynamics | P1 |
| Pipeline templates by customer type | Creatio, Zoho | P2 |

### 2.5 Activities, tasks, calendar
| Feature | Inspired by | Pri |
|---|---|---|
| Tasks and reminders tied to customer/deal, shared with Daybook tasks | Pipedrive, Bitrix24, Capsule | P0 |
| "Today" screen: calls to make, refills due, overdue follow-ups, birthdays | Pipedrive, Close | P0 |
| Call log with one-tap call from mobile, auto-attach to card, outcome picker | Close, Freshsales | P0 |
| Task templates / tracks (e.g. after-purchase check-in sequence) | Capsule | P1 |
| Calendar view and sync (Google/Outlook) | Zoho, Copper | P1 |
| Visit planning and check-in for field reps (GPS, photo) | Sales Doctor, Veeva | P1 |
| Meeting booking links for clinic/doctor meetings | HubSpot | P2 |

### 2.6 Omnichannel inbox (Telegram first)
| Feature | Inspired by | Pri |
|---|---|---|
| Shared team inbox: Telegram bot chats and phone-linked conversations in the customer card | amoCRM/Kommo, Bitrix24 | P0 |
| Reply templates, quick replies, attachments (prescription photo, receipt) | Kommo | P0 |
| Chat assignment, internal notes, transfer between branches, SLA indicators | Kommo, HubSpot | P1 |
| Chat flows (Salesbot style): availability checks, order status, FAQ | Kommo, Bitrix24 | P1 |
| Instagram / WhatsApp / SMS (Eskiz, Playmobile) channels | Kommo, Bitrix24 | P1 |
| Click-to-call and IP telephony with call recording | Bitrix24, Close | P2 |

### 2.7 Marketing campaigns and segments
| Feature | Inspired by | Pri |
|---|---|---|
| Dynamic segments from purchase data (product, category, last visit, spend, branch, age) | RetailCRM, HubSpot | P0 |
| Broadcast via Telegram and SMS with merge fields, opt-out respected | Kommo, Keap | P0 |
| RFM segments out of the box (champions, at risk, lost) | RetailCRM | P1 |
| Trigger campaigns (after purchase, lapse N days, birthday) | RetailCRM, Keap | P1 |
| Campaign ROI: cost vs revenue from recipients' later purchases | HubSpot, RetailCRM | P1 |
| A/B test and send-time optimization | HubSpot | P2 |

### 2.8 Automation / workflows
| Feature | Inspired by | Pri |
|---|---|---|
| Visual rule builder: trigger -> condition -> action (create task, send Telegram, move stage, tag) | Bitrix24 robots, monday, Zoho | P0 |
| Recipe library (pharmacy recipes, one click to enable) | HubSpot, Zoho | P0 |
| Webhooks and API; Daybook events as triggers (stock arrived, batch near expiry, shift ended) | Twenty, Attio | P1 |
| Approvals (discount above X, return) | Dynamics, Creatio | P1 |
| Run log and dry-run of automations | Salesforce Flow | P2 |

### 2.9 Loyalty and retention
| Feature | Inspired by | Pri |
|---|---|---|
| Bonus/cashback wallet with ledger, earn/spend at POS or by phone | RetailCRM, UDS | P0 |
| Tiers (Standard/Silver/Gold) with automatic upgrade/downgrade and perks | RetailCRM | P0 |
| Digital card in Telegram mini app / QR (no plastic) | UDS, Kommo | P0 |
| Referral program (both sides get bonus) | UDS, Keap | P1 |
| Promo codes, coupons, personal offers | RetailCRM | P1 |
| Churn-risk alerts and win-back offers | HubSpot, Salesforce | P1 |
| Points for reviews or finishing a health program | RetailCRM | P2 |

### 2.10 Quotes / invoices / products
| Feature | Inspired by | Pri |
|---|---|---|
| Product catalogue synced from Daybook stock (price, stock per branch, expiry-aware) | Odoo, Dynamics | P0 |
| Quote/offer builder with PDF and Telegram send; accept in chat | HubSpot, Zoho, Odoo | P1 |
| Invoice and payment status (Payme, Click, Uzum, bank transfer) | Keap, Odoo | P1 |
| Recurring orders (monthly chronic supply, corporate packs) | Keap, Odoo | P1 |
| Discount rules with approval | Odoo, Salesforce CPQ | P1 |
| Contracts with end-date alerts | Creatio, Dynamics | P2 |

### 2.11 Service / tickets
| Feature | Inspired by | Pri |
|---|---|---|
| Ticket from chat/call with category, priority, SLA, owner | HubSpot Service, Dynamics | P0 |
| Complaint types: quality, wrong item, staff behaviour, adverse reaction (routes to pharmacovigilance) | Salesforce Health, Veeva | P0 |
| CSAT/NPS after ticket or purchase via Telegram | HubSpot, Freshsales | P1 |
| Staff knowledge base (links to Daybook learning) | Zoho, HubSpot | P1 |
| Return/recall handling by batch | Veeva-style, Odoo | P1 |

### 2.12 Analytics / forecasting
| Feature | Inspired by | Pri |
|---|---|---|
| Role dashboards: owner (retention, repeat rate, LTV), branch manager, call agent | HubSpot, Zoho, monday | P0 |
| Cohort retention, repeat-purchase rate, average basket by segment | RetailCRM | P1 |
| Pipeline funnel and time-in-stage | Pipedrive, Salesforce | P1 |
| Rep/branch leaderboards and targets | Bitrix24, Pipedrive | P1 |
| Report builder and export (Excel, PDF) | Zoho, Attio | P1 |
| B2B revenue forecast | Salesforce, Dynamics | P2 |

### 2.13 AI
| Feature | Inspired by | Pri |
|---|---|---|
| Natural-language assistant: "who bought insulin pens last month and has not returned?" -> segment | HubSpot Breeze Assistant, Attio | P0 |
| Chat summary and suggested reply in the inbox (uz/ru) | Kommo, Close, HubSpot | P0 |
| Per-company AI budget and visible usage (Daybook caps already exist) | (own) | P0 |
| Pre-call/pre-visit brief on the card | Veeva pre-call agent | P1 |
| Voice notes -> structured fields and tasks (uz/ru) | Veeva voice agent, Close | P1 |
| Note/compliance checker (flags dosage claims, prescription-only promotion) | Veeva free-text agent | P1 |
| Next-best-action per customer (refill, cross-sell, reactivate) | IQVIA OCE, Salesforce | P1 |
| Autonomous service agent for availability/order status in Telegram with handover summary | HubSpot Customer Agent, Agentforce | P2 |
| Data cleanup / enrichment agent | HubSpot Data Agent, Attio | P2 |

### 2.14 Mobile-specific
| Feature | Inspired by | Pri |
|---|---|---|
| Offline-first: card view, call log, notes, product lookup; sync later | Veeva, Pipedrive | P0 |
| Incoming-call popup with customer card (Android) | Bitrix24, Close | P0 |
| Barcode/QR scan to find customer or product; scan loyalty QR | Odoo, Billz | P0 |
| Push notifications for assigned chats, tasks, waitlist matches | all | P0 |
| Biometric lock, remote wipe, privacy screen for health data | Veeva | P1 |
| Field-rep route map and visit check-in | Sales Doctor | P1 |
| Home-screen widget (today's tasks), contact import via share sheet | Pipedrive | P2 |

### 2.15 Admin / permissions / data
| Feature | Inspired by | Pri |
|---|---|---|
| Multi-tenant companies, branches, roles (owner, manager, pharmacist, call agent, rep), per-branch visibility | Salesforce, Dynamics | P0 |
| Field-level permissions (hide health notes from non-clinical roles) | Salesforce, Veeva | P0 |
| Full audit log (who opened/changed a customer, exports) | Veeva, Salesforce | P0 |
| Consent records: timestamp, channel, purpose, withdrawal | Veeva, Salesforce Health | P0 |
| Excel/CSV import with mapping and dedupe preview; export | Zoho, HubSpot | P0 |
| Single sign-on with Daybook users and bots | (own) | P0 |
| Uzbek (Latin and Cyrillic), Russian, English UI and search | amoCRM, Bitrix24 | P0 |
| Retention rules and right-to-erasure workflow | Veeva, Dynamics | P1 |
| Demo/sandbox tenant | Salesforce | P1 |
| Data-location statement (hosting in Uzbekistan if the law requires) | (regional) | P1 |

## 3. Pharmacy-specific must-haves

1. Chronic-patient refill reminders (P0). A customer has a "regular medicines" list built from purchase history or entered by staff: product, usual pack count, days of supply. The system predicts run-out and sends a Telegram/SMS nudge 3-5 days before, with a "reserve for me" button. Staff get a daily refill call list per branch. Segment by product class (diabetes, hypertension, thyroid, asthma, contraception); store product class, not diagnosis.
2. Defektura "notify me when it arrives" waitlist (P0). Customer asks for an out-of-stock item; staff or the bot adds them to a waitlist for that product (analog optional). When Daybook records a receipt, the CRM messages waitlisted customers in order, holds N packs for X hours, and shows the pharmacist who is waiting. Demand ("12 people asked for X this month") flows back to purchasing.
3. Doctor / clinic referrals (P1). Doctors and clinics as contacts with specialty, workplace, preferred brands; track referred customers; thank-you rules that comply with local law; per-doctor dashboard; prescription-photo intake with pharmacist reply.
4. Corporate clients (P0). Employer programs: company discount, monthly invoice, employee list, credit limit, statement of account; clinics, factories and schools buy in bulk through a B2B pipeline plus recurring orders.
5. Consent and privacy for health data (P0). Separate consents: service contact, marketing, storing purchase history, health-related reminders. Store text version, time, channel, who recorded it. Sensitive notes in restricted fields, masked by default, access logged. "Stop" in every message. Per-branch role access. Retention and erasure tool. Align with Uzbekistan's personal-data law; get local legal review before launch.
6. Pharmacovigilance complaint capture (P0). Guided form (patient, product, batch/lot, expiry, reaction, severity, outcome, reporter) from chat, call or counter; batch auto-filled from purchase history; routed to the responsible pharmacist; exportable report for supplier/regulator; kept separate from marketing. Quality complaints link to the batch for quarantine or recall in Daybook stock.
7. Loyalty tiers with pharmacy rules (P0). Tiers by 12-month spend; cashback caps; per-category "no bonus" flag for products where bonuses are restricted; family wallet; pensioner/social-category perks; birthday offer.
8. Expiry-driven offers (P1). Daybook knows batches near expiry; CRM proposes discounted offers to matching segments (vitamins, skincare, OTC only), with manager approval. Never prescription-only products.
9. Reservation and order-ahead (P0). "Reserve this pack at branch X" from Telegram, pickup code, delivery request; staff inbox checks stock live in Daybook.
10. Distributor / supplier side (P1). Pharmacy accounts with credit, price lists, order history, rep visits with GPS check-in, route planning, promo agreements, returns; pharmacies get a supplier order portal in the mini app.
11. Cross-branch recognition (P0). Same customer card at every branch of the chain, with branch-specific preferences.
12. Compliance guardrails (P0). Staff templates avoid medical claims; AI replies never give dosage or diagnosis; prescription-only items never appear in broadcasts; symptom messages escalate to a pharmacist.

## 4. How we beat them: 10 signature ideas

1. Refill radar. One screen shows who runs out of which regular medicine this week, per branch, with one-tap Telegram nudge and reservation. amoCRM and Bitrix24 know nothing about days of supply.
2. Waitlist tied to live stock. Defektura requests become a real waitlist; when Daybook receives the batch, customers are messaged and packs are held. Report "demand we lost" in money.
3. Batch-aware complaints. Every complaint or adverse-reaction report links to the batch sold, lists other customers who got that lot, and can open a quarantine task in stock. Veeva-grade traceability for a pharmacy.
4. One company brain with Daybook. The card shows the pharmacist on shift, open task, stock of the wanted item, loyalty tier and attendance context. The CRM is a window on a system the owner already runs, not a bolt-on.
5. Telegram-native everything. Loyalty card, reservations, refill confirmations, surveys and orders live inside the existing bot and mini app; no install for customers; richer than Kommo because stock and price sit behind it.
6. Ask-your-pharmacy AI (uz/ru). "Customers who bought amoxicillin twice and did not return" or "who is waiting for metformin" becomes a saved segment in seconds, with a visible per-company AI budget (HubSpot-style assistant, cost-controlled).
7. Compliance copilot. Checks staff replies and broadcasts for medical claims and prescription-only promotion, like Veeva's free-text agent, in Uzbek and Russian.
8. Pharmacy recipe library. Ready automations: diabetic refill, expiring-vitamins offer, day-3 check-in, 60-day win-back, birthday cashback; one click to enable. Competitors ship blank rule builders.
9. Unchangeable audit trail for health data. Reuse Daybook's never-edited, tamper-evident list idea for consents, complaints and views of sensitive notes: visible corrections, sealed history. A trust and regulator-readiness argument no mass CRM offers.
10. Chain cockpit for owners. Repeat rate, lost sales by branch (out-of-stock requests), loyalty liability, refill conversion, staff response time, complaint rate; branch benchmarks and manager scorecards fed by Daybook HR and attendance.

## 5. Suggested demo cut (P0 spine)
Customer card + timeline; Telegram inbox with templates; waitlist and refill list; loyalty wallet with tiers; B2B pipeline kanban; complaint/pharmacovigilance form with batch link; Today screen; AI "ask" segment builder; consent log and audit; role dashboards; mobile offline card and call popup; Excel import.

## 6. Open questions (verify)
- Billz, Sales Doctor, Smartup, UDS pharmacy specifics (not confirmed by search).
- Kommo/amoCRM 2026 AI features (not confirmed by search).
- Uzbek rules on bonus programs for medicines, prescription-only advertising, and personal-data localization (needs local legal check).
