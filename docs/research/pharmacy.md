# Pharmacies in Uzbekistan: research note for 911 Trello (plan §14)

Prepared 21.10.2026 for the owner's clarification of the same day: "This project is for pharmacy and all that, not for food related stuff." It supports the draft plan section §14 (`plan-14.md`) and is meant to be copied to `docs/research/pharmacy.md`.

## How to read this note

**Method.** Four research passes on 21.10.2026 (about 180 web searches and page reads in total): (1) licensing, staff, prescriptions, controlled substances, returns, online sales, working hours; (2) digital marking, fiscal receipts, taxes, price regulation, storage, destruction; (3) day-to-day operations, software features, market numbers and a glossary; (4) two spot checks (night-work pay; Telegram's scanner). Primary sources were preferred: consolidated texts on lex.uz, gov.uz, the operator site crpt-turon.uz, Telegram's documentation. Secondary sources (gazeta.uz, kun.uz, spot.uz, norma.uz, buxgalter.uz, podrobno.uz, anhor.uz and others) were used where the primary text could not be reached, and are marked.

**Tags on every claim.**

| Tag | Meaning |
|---|---|
| **V** | Verified: read in the primary text cited (mostly a consolidated lex.uz edition) |
| **V2** | Verified in a secondary source (news, legal commentary) that was opened and read |
| **S** | Seen only in a search-result snippet; the page was not opened |
| **A** | Assumed: domain knowledge, international or Russian practice, or our own calculation |
| **H / M / L** | Confidence: high, medium, low |

**Caveats.**
- lex.uz pages were read through an automated page reader that returns extracts, and some Russian texts on lex.uz are unofficial translations. Re-check paragraph numbers before quoting them in a legal document.
- Not read at all: the Uzbek-only licence "passports" annexed to CM Resolution No. 80 (premises, staff and the list of gross violations); the national GPP standard; the text of the Consumer Protection Law; the appendix to CM Resolution No. 75; the new edition of the cash-register regulation that applies from 22.10.2026; the help centre of the marking operator (HTTP 403).
- Several rules changed in 2025–2026 and more are announced (see the calendar in §16). Anything the plan marks "(confirm)" must be checked by a local pharmacist or lawyer before a customer relies on it.
- Real companies and products are named below for research context only. **Demo data must use invented names** (plan §14.3).

## Summary

**Verified and decisive for the product (H unless marked):**
1. Only people with special pharmaceutical education may sell medicines; a pharmacy head needs higher medical or pharmaceutical education (CM No. 185 Annex 2 para 8; Law 415-I art. 21).
2. Rx price caps since 01.04.2025: retail markup at most 20 % of the purchase price, wholesale at most 15 %, never above the maximum reference price; OTC and medical devices are free (Decree UP-13, para 2). Tax-app receipts are compared with reference prices and fined.
3. Medicines sold are not returned or exchanged (CM No. 185 Annex 2 para 39).
4. Prescription retention: preferential 3 years, narcotic 5 years, psychotropic and strong-acting 1 year, others 3 months (CM No. 185 Annex 2 para 36).
5. Narcotics, psychotropics and precursors: a licensed activity with sealed paper books, a monthly inventory by the 3rd, discrepancies reported within 3 days (MoH order No. 36, reg. No. 3604, in force 30.01.2025).
6. Digital marking ("Asl belgisi") is mandatory for medicines; codes travel in e-invoices and are scanned into fiscal receipts at sale (CM No. 149 of 02.04.2022, as amended to 2026; PP-190).
7. Unfit or falsified medicines are destroyed within 30 days by a commission of at least five, with photo or video and an act (CM No. 185 Annex 3, edition of 30.06.2026; M–H, read in an unofficial translation).
8. A GPP certificate is mandatory for every pharmacy from 01.01.2026 (Decree UP-20).
9. Pharmacies must stock the Ministry of Health's mandatory assortment list and show prices signed by the responsible person; Rx items are not displayed to the public (CM No. 185 Annex 2 paras 24, 26).
10. Dispensing is video-recorded continuously and kept one month (PP-4438 para 3).

**Assumed or not found (to confirm):** humidity limits and how often storage readings must be logged; partial-pack and write-off reporting in Asl belgisi; whether e-prescriptions now cover every Rx medicine; the VAT treatment of medicines in October 2026; pharmacy-specific market numbers (average check, payment mix, margins, distributor payment terms); several Uzbek glossary forms.

---

## 1. Regulators (2025–2026)

| Body | Role | Source | Tag |
|---|---|---|---|
| Ministry of Health (Sog‘liqni saqlash vazirligi / Минздрав) | Regulates the circulation of medicines and devices; approves prescription forms and the Rx/OTC classification | Decree UP-20 of 23.01.2024 p.1, https://lex.uz/ru/docs/6774918; Law 415-I arts. 6, 20, https://lex.uz/ru/docs/2856466 | V-H |
| Agency for the Development of the Pharmaceutical Industry, renamed **Agency for the Development of Medicine and the Pharmaceutical Industry** | Renamed by Decree UP-74 of 05.05.2026 (in force 07.05.2026; new tasks from 01.09.2026); runs the reference-price registry; its site moved to pharm.gov.uz | https://lex.uz/ru/docs/8180401 | V-H |
| Center for Good Practices (GxP), under the Agency | Issues GPP certificates after an on-site inspection; reorganised into a state institution by UP-20 | UP-20 p.3; kun.uz 09.10.2025 | V-H / V2-M |
| Center for Pharmaceutical Product Safety (Farmatsevtika mahsulotlari xavfsizligi markazi) | Inspects pharmacies (licensing department, inspectorate); publishes rejected and falsified series; revises currency-based reference prices; to be designated the licensing and notification authority (UP-137 of 19.08.2025, drafts due Dec 2025) | anhor.uz 17.04.2026; https://lex.uz/ru/docs/7697214; https://lex.uz/ru/docs/7345614 | V2-M |
| Tax Committee | Checks fiscal receipts, marking and receipt prices against reference prices | UP-13; PP-190 (via buxgalter.uz) | V2-M |
| CRPT Turon LLC | Operator of the national marking system "Asl belgisi" | CM No. 737 of 20.11.2020 (title seen); crpt-turon.uz | V-H |

## 2. Licensing, premises and inspections

**Verified**
- **Licence, 5 years.** Law No. 415-I "On medicines and pharmaceutical activity" (Dori vositalari va farmatsevtika faoliyati to‘g‘risida / О лекарственных средствах и фармацевтической деятельности) of 25.04.1997, current edition adopted by ZRU-399 of 04.01.2016, amended by ZRU-629 (2020), ZRU-721 (2021), ZRU-879 (2023), ZRU-908 and ZRU-928 (2024). Art. 16: activity is licensed; the licence is issued for five years (shorter only at the applicant's request) and can be extended. Art. 20: retail sale of medicines and medical devices (ophthalmic devices excepted) only by pharmacies and their branches. Art. 21: a pharmacy is a legal entity or its unit, licensed for retail and compounding. https://lex.uz/ru/docs/2856466 (consolidated 2026). **V-H.** (Do not use https://lex.uz/ru/docs/2229, an outdated 1997 text.)
- **Licensing procedure.** CM Resolution No. 80 of 21.02.2022: one regulation for licensing through an electronic system (in force 01.03.2022); licences are indefinite "unless the Law provides otherwise", so pharmacies keep five years; requirements and gross violations sit in Uzbek-only "passports" (Annexes 2–40); state duty within 30 days. It replaced the pharmacy annexes of CM No. 284 of 12.05.2017. https://lex.uz/ru/docs/5870217, https://lex.uz/ru/docs/3204383. **V-H** for the framework; passports not read.
- **New licence conditions from 01.09.2025** (Presidential Resolution PP-190 of 23.05.2025): new pharmacies must register their lease or free-use agreement with the tax authority and accept electronic payments; existing pharmacies can have the licence suspended for buying, transporting, storing or selling medicines without documents or without marking. buxgalter.uz 11.08.2025. **V2-M.**
- **Premises.** CM No. 185 of 06.04.2017, Annex 2 "Regulation on retail sale of medicines and medical equipment" (consolidated to CM No. 353 of 30.06.2026, edition of 03.07.2026): para 21, a pharmacy may be in a separate building or on the ground floor of a building, storage may be in a basement; para 23, the pharmacy keeps goods safe and of good quality. No distance rules found for ordinary pharmacies. Social pharmacies have recommended service radii (2–3 km in cities, 5–10 km rural) and locations approved by the Ministry (CM No. 334 of 03.05.2018 paras 7–8). https://lex.uz/ru/docs/3155770, https://lex.uz/ru/docs/3719680. **V-H.**
- **Inspections.** Licence-compliance supervision of pharmaceutical organisations at most once a year, up to 5 days, with a special control regime and risk analysis from 01.07.2024 (UP-20 Annex 2 item 2). **V-H.** Inspections target illegal Rx sales, including strong-acting medicines (PP-4438 of 06.09.2019 p.1, amended by UP-110 of 21.07.2023). **V-H.**
- **Video recording.** From 01.01.2020 pharmacies keep continuous video of dispensing and store it for one month; violations twice a year are grounds to end the licence (PP-4438 p.3). https://lex.uz/ru/docs/4501282. **V-H.**
- **Quality basics** (CM No. 185 Annex 2): para 11, goods needing a certificate of conformity are not sold without one; para 12, substandard, falsified, unregistered goods and illegal copies are banned; para 13, adverse reactions are reported to the Ministry in writing. **V-H.** Reporting adverse reactions is to become a licence requirement (UP-137 plan item 4). **V-M.**
- **Medical devices.** UP-137 p.4(г): from 01.01.2026 retail sale of medical devices needs a notification instead of a licence; the Law text read still limits it to pharmacies, so implementation is not confirmed. **V-M.**
- **Penalties.** Operating without a licence: up to 300 base calculation amounts for a legal entity (anhor.uz 17.04.2026, **V2-M**); 25 pharmacies sanctioned for that in Q1 2026 and 23 licences annulled since January 2026 (anhor.uz, **S-M**). Violations of the retail rules are linked to Administrative Code art. 165¹ and Criminal Code art. 186³ (lex.uz editorial notes, **V-H** for the reference; fine amounts not checked).

**What an inspector looks at** (pieced together from the acts above, **A-M**): licence and its display, GPP certificate, staff education, prescription journals, narcotics books and safes, expired and substandard goods, prices against reference prices, marking codes on receipts, video recording and, since January 2026, use of e-prescriptions.

**Not found or uncertain:** minimum areas (54 m² with branches, 34 m² without, 8 m² rural point) come from 2017-era rules seen in snippets only (**S-L**); a 3 mln so‘m fee and 10-day review (2023 snippet, **S-L**); the current list of gross violations (in the unread passport).

## 3. Who may sell; qualifications; GPP

**Verified**
- **Only qualified staff sell.** CM No. 185 Annex 2 para 8: "only persons with special pharmaceutical education are admitted to selling medicines"; heads of pharmacies and branches need higher or secondary-special pharmaceutical education. **V-H.**
- **Heads.** Law art. 21 (as amended by ZRU-721): a pharmacy head needs higher medical or higher pharmaceutical education; a branch head needs pharmaceutical education. **V-H.**
- **Advice and delivery.** Para 28: the pharmacist advises on analogues, dosing, administration, storage and expiry (a duty of the pharmacist, not of software). Para 39¹: for deliveries the pharmacist advises remotely; couriers need no pharmaceutical education. **V-H.**
- **No explicit "present every hour" rule** was found; that any shift selling medicines needs a qualified person is an inference from para 8. **A-M.**
- **Qualification categories.** The old regulation on attestation and categories (MoH order No. 21 of 18.12.2014, reg. No. 2649; categories valid 5 years) lost force on 22.02.2024; its replacement was not identified. https://lex.uz/ru/docs/2543185. **V-M.**
- **State registration of medical and pharmaceutical workers** (government resolution of 19.10.2026, number not confirmed): registration valid 5 years; voluntary from 01.07.2027, mandatory to practise from 01.01.2030; electronic certificates in a unified register. podrobno.uz 21.10.2026. **V2-M.**
- **GPP mandatory.** UP-20 Annex 2 item 3 (amending UP-5707): a GPP certificate is required for chain pharmacies from 01.01.2025 and for all other pharmacies from 01.01.2026. **V-H.** CM No. 788 of 18.09.2019 cl. 3 (added by PP-411 in 2022) also requires retail pharmacies to meet national GPP requirements (https://lex.uz/docs/4520726, **V-H**). The certificate lasts 3 years with surveillance about every 9 months; fees about 8.3–8.5 mln so‘m for a main pharmacy and 3.2 mln for a branch; 9 231 pharmacies (77 %) certified by 03.10.2025 (kun.uz 09.10.2025, **V2-M**). No postponement of the 2026 deadline found.
- **Diploma rental.** Tashkent job ads offer 1.8–2.4 mln so‘m a month to "rent" a pharmacist's diploma and certificate for a licence (OLX, Sep–Oct 2026) — evidence that licences need qualified staff and that the rule is gamed. **V-H** (ads) / **A-M** (interpretation).

**Not found:** a legal definition of "provizor" (higher) versus "farmatsevt" (secondary) — the law says "higher pharmaceutical" and "pharmaceutical" education; the number of the GPP standard order.

## 4. Prescription-only medicines, prescriptions and e-prescriptions

**Verified**
- **Rx versus OTC.** Law art. 20 part 2 (ZRU-928 of 30.05.2024): medicines are sold on a prescription on the approved form, or without one; the Ministry approves the classification (art. 6). **V-H / V-M.** The OTC list (MoH reg. No. 3315 of 30.07.2021) has 87 single-ingredient items and 814 combinations and applies whatever the pack or leaflet says (norma.uz 02.08.2021, **V2-M/H**); a medicine not on it is Rx. The reference-price registry listed 12 815 Rx names and strengths in December 2025; ibuprofen, ambroxol, paracetamol syrup and medical ethanol are among items now Rx (spot.uz 12.12.2025, **V2-M**).
- **Dispensing** (CM No. 185 Annex 2, consolidated to 03.07.2026; **V-H**):
  - para 27: sale by prescription on the approved form, including e-prescriptions, which go through the Ministry's information system;
  - para 31: dispense by INN, in the prescribed quantity;
  - para 31¹: on a paper prescription the pharmacist completes, signs and stamps the tear-off stub for the patient; the prescription stays in the pharmacy and is entered in the **prescription register** (Annex 1). On an e-prescription the pharmacist records the dispensing in the Ministry's system with an electronic signature;
  - para 32: a dose above the maximum single dose without the proper note → dispense half the maximum;
  - para 34: up to 3 months of treatment in exceptional cases; para 35: long-term prescriptions go back to the patient with dispensing notes;
  - para 36 **retention**: preferential prescriptions 3 years; narcotic (pink forms) 5 years; psychotropics, medical ethanol, anabolic agents and the strong-acting list 1 year; all others 3 months; para 37: then destroyed with an act;
  - para 37¹: invalid prescriptions are stamped and entered in the **register of incorrectly written prescriptions** (Annex 2), and the prescribing facility's head is told;
  - para 30: a single unit (a blister) may be sold only if it shows name, series, expiry and manufacturer; never from damaged primary packaging;
  - para 26: Rx medicines and information about them are not displayed to the public.
- **E-prescriptions.** CM No. 570 of 08.09.2025 approved the regulation on prescribing by e-prescription, in force 12.12.2025 (norma.uz 12.09.2025, **V2-M/H**). MoH order No. 25 of 15.12.2025, MoJ reg. **No. 3725**, in force 16.12.2025 ("Elektron retsept" phased introduction; https://lex.uz/ru/docs/7920485, **V-H**):
  - pilot: Tashkent city and 15 districts or cities; stage 1 groups that must be prescribed electronically: antibiotics, systemic synthetic antibacterials, systemic hormonal drugs; later groups set by an expert council;
  - excluded: strong-acting substances, drugs with narcotics or psychotropics, reimbursement processes;
  - the pharmacist first checks the e-prescription in the module using the patient's ID document and **PINFL (JShShIR)**; paper prescriptions are entered into the module by the pharmacist; paper allowed until 01.03.2026 for facilities not yet integrated and during outages;
  - validity equals the course: 60 or 90 days for chronic patients, 30 days under reimbursement.
- **Uptake and next steps.** Only 13.3 % of about 412 000 e-prescriptions in Tashkent were used in pharmacies; checks with Prosecutor General and Tax Committee data announced; nationwide rollout planned for the end of 2026 (gazeta.uz 20.01.2026, **V2-M**). In May 2026 the Ministry published a draft to move pilot facilities fully to e-prescriptions for Rx medicines (spot.uz 01.05.2026; gazeta.uz 01.05.2026; **V2-M**); adoption **not confirmed**.
- **Antibiotics** have no separate "prescription only" article; they are Rx because they are not on the OTC list, and from 16.12.2025 must be e-prescribed in the pilot territories. **V-M.**
- **Reimbursement.** Chronic patients on the dispensary register get guaranteed-package medicines free on an e-prescription; pharmacies under contract with the State Health Insurance Fund dispense and are reimbursed; about 28 medicines; all regions planned by the end of 2026 (uza.uz, gov.uz news, gazeta.uz 01.2026; **S / L-M**).

**Not found:** prescription form numbers; MoH order No. 121 of 01.07.2020 on INN prescribing (reg. No. 3277 seen in a snippet, **S**); instruction reg. No. 3758 of 19.01.2026 on the e-prescription modules (**S**); fines for selling Rx without a prescription.

## 5. Controlled substances and subject-quantitative accounting

**Verified**
- **Regulation.** MoH order No. 36 of 25.12.2024, MoJ reg. **No. 3604** of 27.01.2025, in force 30.01.2025 ("Giyohvandlik vositalari, psixotrop moddalar va prekursorlarni saqlash, berish, sotish, taqsimlash, hisobga olish shartlari to‘g‘risidagi nizom"), amended by MoH order No. 15 of 30.04.2026 (reg. 3837, 19.05.2026); replaced reg. No. 1090 of 2001. https://lex.uz/ru/docs/7349574. **V-H.**
  - Scope: legal entities licensed by the Ministry for activity with narcotics, psychotropics and precursors.
  - Storage: narcotics in safes, locked and sealed after hours (cl. 5), never overnight in the assistants' room (cl. 13); psychotropics in locked metal cabinets (cl. 64); precursor-containing medicines in metal cabinets (cl. 76); warehouses for psychotropics need a metal door at least 3 mm thick and a separate alarm (cl. 63).
  - Dispensing: narcotics only on the special form (Annex 1), one narcotic per form, at most 7 days' need, valid 7 days (cl. 6, 36); psychotropics up to one month's amount, valid one month (cl. 65); a pharmacy holds at most one month's need of psychotropics (cl. 67); precursor-containing medicines are Rx only (cl. 92), except small amounts of potassium permanganate (3 g) and dilute hydrochloric acid (cl. 91); invalid prescriptions are stamped and registered (cl. 39–40).
  - Books: narcotics (Annex 3), psychotropics and precursor-containing medicines (Annex 18), research precursors (Annex 20); each **numbered, laced, sealed and signed by the head** (cl. 14, 71, 92, 93); electronic books are not mentioned.
  - **Monthly inventory** of the previous month **by the 3rd** (Annex 4); discrepancies reported to the internal affairs bodies and the Ministry **within 3 days** (Annex 5).
  - Retention: narcotic prescriptions 5 years, sealed (cl. 16); psychotropic 1 year (cl. 69); destruction by burning, by a commission of at least 3, with an act (Annex 6).
- **Strong-acting substances.** List in CM No. 818 of 27.09.2019 Annex 1 (edition CM No. 632 of 04.10.2024, amended by CM No. 732 of 18.11.2025; further changes from 12.01.2027). Starred items — zaleplon, pregabalin, tropicamide, cyclopentolate, gabapentin, sibutramine — may be sold only through social pharmacies and pharmacies licensed for narcotics and psychotropics; tramadol is not on this list. https://lex.uz/ru/docs/4532171. **V-H.**
- **Subject-quantitative accounting.** From 01.12.2019 certain medicines on the strong-acting list are under subject-quantitative accounting ("предметно-количественный учёт"), sold only through social pharmacies and pharmacies licensed for narcotics and psychotropics, with prescriptions kept one year (PP-4438 pp. 1, 3, amended by UP-110 and UP-207 of 03.11.2025). **V-H.**
- **No online sale** of narcotics, psychotropics or precursors (CM No. 185 para 15); social pharmacies must hold the licence for storing and dispensing narcotics and psychotropics (CM No. 334 p.6(a)). **V-H.**

**Uncertain:** whether the narcotics/psychotropics activity is a separate licence document or an activity within the licence (**A**); pharmacy reporting periods (the quarterly and annual reports found apply to medical facilities); the narcotics law number (No. 813-I of 19.08.1999, from memory); the Uzbek term "predmet-miqdoriy hisob" (not seen in a source, **L**).

## 6. Digital marking ("Asl belgisi")

**Verified**
- **Legal basis.** CM No. 737 of 20.11.2020 (the system, operator CRPT Turon; **V-H** via title and citations); CM No. 833 of 31.12.2020 (general marking regulation; crpt-turon.uz, **V-H**); **CM No. 149 of 02.04.2022** on medicines and medical devices, edition current to 07.03.2026, amended by PP-190 (2025), CM No. 23 (23.01.2026) and UP-35 (05.03.2026), https://lex.uz/ru/docs/5936145 (**V-H**); PP-190 of 23.05.2025, https://lex.uz/ru/docs/7540341 (**V-H**); CM No. 23 of 23.01.2026, https://lex.uz/ru/docs/8012407 (about 40 % read, **V-H** exists / **M** details).
- **Scope** (CM No. 149 cl. 2): group 1 medicines in secondary packaging from 01.09.2022; group 2 medicines in primary packaging and herbal products from 01.11.2022; group 3 orphan drugs and listed products from 01.03.2023; group 4 listed medical devices (HS 3005, 3006) from **01.07.2027**. Pharmaceutical substances and compounded medicines are excluded. From 01.07.2026 medicines bought with budget money must be marked. **V-H.** The operator's retail page still says devices from 01.02.2025; the 2026 lex.uz text is treated as current (**M**).
- **Retail deadlines** (CM No. 149 Annex 4): registration in the system, codes in e-invoices, reporting sales and recording all movements were due in 2023–2024; unmarked leftover stock had to be written off by 01.08.2025 (group 1), 01.11.2025 (group 2) and 01.03.2026 (group 3). So in October 2026 unmarked group 1–3 medicines can no longer be sold. **V-M/H.**
- **Receiving.** Codes travel inside the electronic invoice; the operator learns of the change of owner from the e-invoice roaming operator; a transfer of ownership must reach the system within 72 hours (CM No. 149). From 01.09.2025 an e-invoice for marked goods without codes is not allowed; from 01.07.2025 wholesale of marked goods is **non-cash only**, and imported medicines reach wholesalers and retailers only through the importer or its official dealers, on an e-invoice (PP-190 cl. 3, 7). From 01.07.2026 the system checks automatically, when an e-invoice is formed, that the seller holds a licence or notification, is registered in the system and that the codes are right (CM No. 23 cl. 4). **V-H.**
- **Selling.** The cashier scans the code; code and product code go into the online cash-register receipt; the fiscal data operator sends the system the register number, date, price and codes within a day; the system records the withdrawal from circulation (CM No. 149 stage 5). From 01.09.2025 a receipt is formed only after the code is entered, and a code already used blocks the receipt (PP-190 cl. 7). From 01.07.2026 product data linked to the code is printed on the receipt (CM No. 23 cl. 4). Cash registers that can't read codes may not sell to the public (buxgalter.uz 28.12.2023, **V2-M**). **V-H.**
- **Penalties.** Storing or selling unmarked medicines is a gross breach of licence requirements and can suspend the licence (CM No. 149 Annex 7); the licence can be suspended on the tax authority's initiative when unmarked or contraband medicines are found (PP-190 cl. 9). Remote inspections from 01.01.2026: first a warning, then fines of 0.2 %, 0.4 %, 1 % and 2 % of the last quarter's net revenue, and no VAT refund for a year after the fourth; a marking violation sets the tax risk to "high" (PP-190 cl. 8 and Annex 2). **V-H.** A 2025 article quotes 2 % and 20 % fines under Tax Code art. 227-1; its relation to the PP-190 scale is unclear (**V2-L**).
- **Apps.** Consumers check products and report mismatches in the Asl Belgisi and Soliq apps (CM No. 23 cl. 37–39, **V-H**). 7 652 pharmacy organisations were connected in 2025 and more than 251 million marked packs were sold through receipts (podrobno.uz 25.09.2026, **V2-H**).
- **API.** No legal text defines one; CM No. 23 requires each participant to have a system that signs and exchanges electronic documents with the marking system (cl. 5) and offers document exchange in a personal account (cl. 41–42). **V-H.** The operator's help centre has an "API and technical documentation" section (**S**, page returned 403).

**Not found / assumed:** how a sale of part of a pack is reported (the retail rules allow selling single units, para 30; a "share of pack" field like Russia's is **A**); how write-offs, destruction and theft withdraw codes (**A**: a withdrawal document with a reason); how a mistaken sale re-activates a code; the name "True API" (**A**, by analogy with Russia).

## 7. Prices, display and assortment

**Verified**
- **Rx caps** (Decree UP-13 of 28.01.2025, para 2, from 01.04.2025; https://lex.uz/ru/docs/7345614): markup caps apply **only to Rx medicines**: retail at most **20 %** of the purchase price, wholesale at most **15 %**, however many intermediaries; prices never above the maximum wholesale and retail **reference prices**; OTC prices free. Same composition from the same manufacturer gets the lowest reference price. Currency-based reference prices are revised each January and July after a 3 % currency move, early after 5 %. The tax app compares each receipt's price with the reference price and overpricing is fined (Appendix 4 item 6); half of the fines go to the Pharma Development Fund. **V-H.** The same 20 % cap and reference ceiling are in CM No. 185 Annex 2 para 10 (as amended by CM No. 662 of 21.10.2025). **V-H.**
- **Reference pricing** for Rx medicines rests on PP-4554 of 30.12.2019 as amended; since 01.04.2025 an Rx medicine without a reference price, or above it, cannot be certified (PP-411 as amended). **V-H / V2-M.** Price registration rules: MoH order No. 115 of 24.03.2020 (reg. No. 3242); a newer order reg. No. 3735 of 25.12.2025 picks the lowest of values computed in USD, EUR or RUB (**S-M**).
- **Socially significant medicines: 10 % cap** (podrobno.uz 29.01.2025, **V2-M**). Social pharmacies sell listed items at no more than fixed prices and post the list (CM No. 334 p.6(б), para 12; **V-H**).
- **Enforcement.** 991 pharmacies checked, more than 414 000 overpricing cases, 8.5 bn so‘m of illegal income, 6 licences revoked (anhor.uz 2026, **V2-M**); 237 more pharmacies found in breach in October 2026 (spot.uz 05.10.2026, **S-M**); about 2 000–2 500 Rx items had price cuts from 01.03.2026 (**S**); invoices above the reference price reportedly blocked by the tax system since March 2026 (**S-M**).
- **Display and documents** (CM No. 185 Annex 2; **V-H**):
  - para 26: every medicine and device on sale shows its price, confirmed by the signature of the responsible person; Rx medicines are not displayed to the public; medicines for internal and external use are displayed separately; a share of display space (the reader returned "at least 10 %") goes to dietary supplements and herbal products (**V-M** for the share: re-check minimum or maximum);
  - para 24: the buyer gets the fiscal receipt and a **goods receipt** (товарный чек) with name, dosage, packaging, quantity, dispensing employee, date and price; every pharmacy stocks the Ministry's **mandatory assortment** list; social pharmacies display the socially significant list in Uzbek and Russian (12 pt or larger);
  - para 14: the pharmacy displays its licence number, validity, activity and issuer; para 22: the sign shows name, legal form, address and working hours; para 29: price and quality documents shown on request;
  - para 29¹: pharmacy websites and apps show the seller's details, licence, each item's price and markup, and payment and delivery terms.
- A suspended licence for gross violation of pricing rules is a recognised case (CM No. 284 para 4, **V-H** for the reference).

## 8. Storage

**Verified**
- **Sanitary rules for pharmacies: SanQvaN 0071-24** ("Dorixonalarning joylashuvi va jihozlanishiga doir sanitariya qoidalari…"), order No. 10 of 05.04.2024 of the Sanitary-Epidemiological Committee, registered 26.04.2024, replacing SanQvaN 0337-16. https://lex.uz/docs/-6915942. **V-H** exists, **M** details. It sets: sales hall at least 16 °C in the heating season (Annex 3: about 20 °C in preparation and storage rooms); air conditioning in the sales area and storage room (cl. 34); a thermometer in finished-medicine storage rooms on an inner wall away from heaters, 1.5–1.7 m high and 1 m from the door (cl. 35); a refrigerator for heat-sensitive medicines (cl. 33); sun shading (cl. 25); nothing on the floor (cl. 15); shelving clearances (cl. 24); flammables in metal cabinets and controlled substances in equipped areas (cl. 37); daily wet cleaning, weekly disinfection and a monthly sanitary day (cl. 38, 46).
- The Law (art. 21) still cites the older SanPiN 0243-07 of 29.12.2007 (https://lex.uz/docs/1912039), with similar thermometer, air-conditioning and refrigerator rules; probably superseded. **V-M.**
- **GPP and GSP.** Retail pharmacies must meet national GPP (CM No. 788 cl. 3); GSP for storage businesses was added by UP-20 of 24.01.2024. GxP certificates last 3 years with yearly surveillance; nonconformities fixed within 90 working days. https://lex.uz/docs/4520726. **V-H.**
- **Compounding pharmacies** (MoH order No. 17 of 27.03.2018, reg. No. 2990, amended from 20.05.2026): every incoming item is checked for appearance, packaging and documents including quality certificates; doubtful items go to an accredited lab, are marked and held in quarantine (cl. 65–66). https://lex.uz/docs/3606685. **V-M.**
- **Wholesale and delivery** (CM No. 185): goods to be withdrawn are kept under an act in an isolated zone, returned goods in a separate zone (Annex 1 cl. 28–29); delivery vehicles have cameras and keep temperature and humidity (Annex 2 cl. 39¹). **V-M.**

**Not found / assumed:** humidity limits, a hygrometer requirement and how often readings are logged are **not** in the text read. A 2017 rule (snippet) says warehouse temperature and humidity are recorded daily, electronically or in a laced, numbered, sealed journal; labour-protection rules No. 1976 of 26.06.2009 require a temperature and humidity table in each section (**S-L/M**). Room storage at 15–25 °C, cold chain at 2–8 °C, humidity at or below 60 %, readings twice a day (morning and evening), and the journal list are **A** (international and CIS practice). National standards O‘z DSt 3127:2016 (GPP) and O‘z DSt 2763:2018 (GSP) were cited but not read.

## 9. Expired, damaged, falsified medicines; destruction; recalls

**Verified**
- **CM No. 185 Annex 3** (withdrawal and destruction of unfit, falsified, unregistered and counterfeit medicines), largely rewritten by CM No. 353 of 30.06.2026. https://lex.uz/ru/docs/3155770. **V-M/H.**
  - Definitions: "unfit" = deteriorated or expired; "falsified" = false information about composition, characteristics or manufacturer; "counterfeit" = put into circulation in breach of intellectual property.
  - The owner (or a court) decides; the owner withdraws the goods **at once** and destroys them **within 30 days**, at its own cost (cl. 5–8).
  - Methods: liquids broken or diluted at least 1:100; solids crushed or sent for disposal; biologics decontaminated; radioactive products need an environmental conclusion.
  - A **commission of at least 5**: the owner, the environmental and sanitary authorities and the pharmaceutical-safety centre (cl. 16–17); a responsible person named by the owner's order; destruction photographed or filmed (cl. 18–19).
  - The **act** records date, product details, owner, method and commission; copies go to the owner, the environmental and sanitary authorities and the centre, with the order, the decision and the photo or video (cl. 20–23). Samples held for an investigation stay until the case ends (cl. 24).
- Expired medicine is legally "sifatsiz dori vositasi" (substandard medicine) and the law mentions companies that carry out destruction (Law 415-I, Uzbek text, https://lex.uz/docs/-8437; **V-H**).
- **Rejected and falsified series.** The pharmaceutical-safety centre publishes lists of falsified, substandard and rejected medicines as downloadable files (2022–2025 seen) and safety letters on uzpharm-control.uz; pages render by JavaScript; no API or machine-readable feed found. **S-M.**
- From 01.07.2026 the marking system won't let a code be re-applied unless the product was first withdrawn (CM No. 23 cl. 24). **V-M.**

**Not found:** how pharmacies are formally told about suspended batches, and whether checking every incoming batch against the centre's lists is a written duty outside compounding pharmacies; whether licensed waste contractors are required; whether the marking system blocks recalled batches at the till (a pharmacy director says scanning blocks unregistered, sold, suspended, recalled and expired packs: podrobno.uz 25.09.2026, **V2-M**).

## 10. Returns from customers

- **No returns of medicines.** CM No. 185 Annex 2 para 39: medicines sold "are not subject to return or exchange for analogues". https://lex.uz/ru/docs/3155770. **V-H.**
- General rule: non-food goods of proper quality can be exchanged within 10 days, or refunded if no equivalent is in stock, if unused and with the receipt (Consumer Protection Law art. 18, per the Competition and Consumer Protection Committee, 08.08.2023, https://raqobat.gov.uz/ru/poryadok-vozvrata-tovara-nadlejashhego-kachestva/). **V2-H.** Exceptions are in CM No. 75 of 13.02.2003 (Rules of retail trade) Appendix 1, which includes goods for preventing and treating disease at home, including medicines (lex.uz explanation via snippet, **S-M**).
- **A:** non-medicine goods (cosmetics) follow the general 10-day rule unless on the CM No. 75 list; defects and recalls go to quarantine and the Annex 3 procedure.

## 11. Online sales and delivery

- Only licensed pharmacies sell (Law art. 20). **V-H.**
- CM No. 185 Annex 2 (**V-H**): para 41, only OTC medicines (and medical equipment) may be sold by e-commerce; para 15, never narcotics, psychotropics or precursors; para 29¹, the website or app shows the seller's details, licence, each item's price and markup, payment and delivery terms; para 39¹, delivery: the pharmacist advises remotely, couriers need no pharmaceutical education, vehicles have cameras and keep temperature and humidity, no private or hitchhiking transport, cold-chain goods only in refrigerated or monitored transport, no mixed cargo.
- An April 2026 presidential resolution on e-commerce asked for rules on pharmacy online sales by mid-July 2026 (pickup points for marketplace orders, no opening of packaging by couriers, thermal containers) (spot.uz 14.04.2026, **V2-M**); outcome unknown.

## 12. Working hours and 24-hour pharmacies

- **No national obligation** to run night or on-duty pharmacies was found in the Law, CM No. 185 or CM No. 334 (**V-M**, absence of evidence). Local duty schedules may exist; none found.
- The sign shows working hours (CM No. 185 para 22, **V-H**). Temporary closures of a social pharmacy (inventory, repairs, sanitary days) need the state partner's agreement, sanitary days also the sanitary service's (CM No. 334 para 13, **V-H**).
- Practice: typical hours 08:00–23:00 or 08:00–21:00; a minority open 24 hours (aggregator filters, directory listings; **S-M / V-H**).

## 13. Fiscal receipts, cash registers, product codes and e-invoices

- **Cash registers.** CM No. 943 of 23.11.2019 regulates online cash registers and virtual cash registers; a **new edition** (CM No. 393 of 20.07.2026) applies from **22.10.2026** and was not reviewed (nrm.uz summary, **V2-H** exists / **L** content). Only devices in the State Register, registered with the tax authority, may be used; receipts are mandatory, including for QR payments; registers must accept bank cards from 01.01.2023 (**V2-M**).
- **Fiscal module and operator.** The fiscal data operator is the state enterprise "Yangi texnologiyalar" research centre under the Tax Committee; the fiscal module costs 1 base calculation value a year (buxgalter.uz, **V2-M**).
- **Receipt contents.** A QR code, the fiscal sign and each line's product classifier code (**MXIK / ИКПУ**), plus fiscal-module and register data; a terminal slip does not replace it (buxgalter.uz 28.12.2023, citing the Tax Committee, **V2-M/H**). Older material adds the marking code and up to 24 hours of offline work (**V2-M**). A separate package code per line is **A** (from memory of the protocol).
- **MXIK.** A 17-digit code from tasnif.soliq.uz used in receipts and e-invoices; base codes ending in "000 000" for unmarked goods; units and packages are linked to each code (buxgalter.uz snippets, **S-M**).
- **Electronic payments** are a pharmacy licence condition from 01.09.2025 (PP-190 cl. 9, **V-H**); payment-app receipts (Click, Payme and others) count as fiscal (**S**).
- **Who may issue receipts.** In 2023 the Tax Committee said retail accounting software must integrate as a virtual cash register entered in the State Register (sample, certificate of conformity, technical passport, Cybersecurity Center conclusion); some lawyers dispute that it is required (buxgalter.uz, **V2-M**). Inference: a platform that does not fiscalize, or that integrates with an already registered register, avoids certification (**A**).
- **E-invoices.** Mandatory for all businesses since 01.01.2020 (CM No. 522 of 25.06.2019, cited, not read); 27 operators listed by the Tax Committee in early 2026 (Didox, Faktura.uz, Soliqservis…); roaming operator "Yangi texnologiyalar"; retention 5 years for operators, 10 for the roaming operator (buxgalter.uz, bss.uz snippets, **S-M**).
- **Soliq app cashback** of 1 % for registering a receipt (since 01.01.2022, reportedly capped at 60 base values a month since 2024); a July 2026 proposal would replace it with lotteries (kun.uz 08.07.2026, **S**); status in October 2026 **not confirmed**.

## 14. Taxes

- **VAT on medicines.** The exemption for medicines and medical devices (Tax Code art. 243) ended on 01.04.2024; since then 12 % VAT applies, including to stock on hand (buxgalter.uz articles, **S/V2-M**; the cancelling act's number not confirmed).
- Decree UP-229 of 27.12.2024 said sellers of medicines and medical services must become VAT payers from 01.04.2025, but the Tax Code's list of businesses barred from turnover tax was not amended; consultants say pharmacies may stay on turnover tax (buxgalter.uz 01.04.2025, **V2-M**). Status in October 2026 **not confirmed**.
- UP-13 Annex 3 item 4 only ordered an analysis of VAT on medicines; it raised the import duty on HS 3004 from 0 % to 2 % from 01.04.2025 (**V-H**).
- **Decree UP-100 of 26.05.2026** (in force 28.05.2026, amended 27.08.2026): turnover-tax threshold 12 000 base calculation values from 01.06.2026 (about 4.9 bn so‘m); an optional simplified VAT of 6 % on turnover, 0 % profit tax, no input credit, available to trade and services until 01.01.2030; pharmacies are not named (https://lex.uz/ru/docs/8237115; spot.uz 11.06.2026; **V-H**). Whether pharmacies may use the 6 % regime is **A**.

## 15. Night work (labour) and Telegram scanning (spot checks)

- **Night work** is paid at no less than 1.5 times the rate per hour (time-based pay), or with a supplement of at least 50 % of the hourly base (piece rate); overtime at least double (gov.uz guidance page linking the Labour Code of 28.10.2022, https://gov.uz/ru/advice/554/document/2215, read 21.10.2026; **V2-H**). Night time is 22:00–06:00 and a night shift is one hour shorter unless the person was hired for night work (tax-legal.uz, snippet; **S-M**); the Labour Code articles (reported as 264) not re-checked.
- **Telegram Mini Apps** document only a QR scanner: `showScanQrPopup` (Bot API 6.4+) is "a native popup for scanning a QR code"; nothing for EAN-13 or DataMatrix (https://core.telegram.org/bots/webapps, read 21.10.2026; **V-H**). The browser `BarcodeDetector` API is experimental and "not Baseline", available only in some browsers; supported formats must be checked at runtime with `getSupportedFormats()` (MDN, read 21.10.2026; **V-H**).

## 16. Compliance calendar

| Date | Change | Tag |
|---|---|---|
| 01.12.2019 | Subject-quantitative accounting and restricted channels for listed strong-acting medicines (PP-4438) | V-H |
| 01.01.2020 | Video recording of dispensing, kept 1 month (PP-4438) | V-H |
| 01.04.2024 | VAT exemption for medicines ends | S/V2-M |
| 01.01.2025 | GPP mandatory for chain pharmacies (UP-20) | V-H |
| 30.01.2025 | New narcotics, psychotropics and precursors regulation (reg. 3604) | V-H |
| 01.04.2025 | Markup caps only on Rx (20 % retail, 15 % wholesale); reference prices; OTC free (UP-13) | V-H |
| 01.07.2025 | Imported medicines only via the importer or official dealers; wholesale of marked goods non-cash only (PP-190) | V-H |
| 01.09.2025 | New licence conditions (lease registered, e-payments); licence suspension for unmarked goods; no e-invoice without codes; receipt formed only after the code (PP-190) | V-H / V2-M |
| 12.12.2025 / 16.12.2025 | E-prescription regulation in force; mandatory for antibiotics, antibacterials and systemic hormones in pilot territories (CM No. 570; reg. 3725) | V-H |
| 01.01.2026 | GPP mandatory for all pharmacies; remote marking checks with fines; medical-device retail by notification (implementation unconfirmed) | V-H / V-M |
| 01.03.2026 | Paper prescriptions end for non-integrated pilot facilities; last write-off deadline for unmarked group 3 stock | V-H / V-M |
| 07.05.2026 | Agency renamed (UP-74) | V-H |
| 01.06.2026 | Turnover-tax threshold 12 000 base values; optional 6 % VAT (UP-100) | V-H |
| 01.07.2026 | Automatic e-invoice checks; product data printed from the code; budget-bought medicines must be marked (CM No. 23; CM No. 149) | V-H |
| 03.07.2026 | CM No. 353 amendments to CM No. 185 and No. 334 | V-H |
| 22.10.2026 | New edition of the cash-register regulation (CM No. 393) — not reviewed | V2-H |
| End 2026 | Nationwide e-prescriptions planned | V2-M |
| 12.01.2027 | Amendments to the strong-acting list (CM No. 818) | V-H |
| 01.07.2027 | Marking mandatory for listed medical devices; voluntary state registration of pharmaceutical workers | V-H / V2-M |
| 01.01.2030 | Registration of pharmaceutical workers mandatory to practise | V2-M |

---

## 17. How a pharmacy works day to day

A typical Tashkent independent or small-chain pharmacy (**A-M** unless tagged; the shape matches the Uzbek reference product's menus and a chain director's account):

1. **Opening (08:00).** The pharmacist opens the fiscal shift on the cash register and counts the float; fridge and room temperature (and humidity) are written in the log, usually morning and evening (**A-M**). Hours 08:00–23:00 or 08:00–21:00; a minority 24/7 (**S-M / V-H**).
2. **Deliveries** from several distributors through the morning: goods matched to documents; packaging, expiry and marking checked; each code checked in Asl belgisi; discrepancies held back from sale until settled with the supplier (Navbahor commercial director, podrobno.uz 25.09.2026, **V2-H**). Price tags reprinted after repricing.
3. **Selling all day.** Every pack is scanned; the scan records the pack leaving circulation and blocks packs that are unregistered, already sold, suspended or recalled, or expired (**V2-H**). Pharmacists advise, suggest substitutes and add-ons, and log requests they couldn't fill (**V-H** for the software headings; **A** for practice). Reservations arrive from aggregators.
4. **Ordering and payments (afternoon).** The head or purchaser builds orders from distributor price lists; in small pharmacies by hand (**A-M**). A Kazakh chain took 3–4 days to order manually from 5 000–6 000 names (Astana Hub 2025, **V2-H**). Supplier invoices are paid as they fall due (**A-M**).
5. **Shift handover** (16:00–17:00, or 20:00 for 12-hour shifts): X-report, cash counted and handed over, spot counts of high-value items (**A-M**).
6. **Closing.** Z-report, cash to the owner or bank, temperature log; night staff take over in 24/7 pharmacies (**A-M**).
7. **Monthly and periodic:** partial counts and a near-expiry review; returns to suppliers and write-offs with signed acts; repricing when reference prices or exchange rates change (**V-H** for automatic revisions); payroll with bonuses; reconciliation with suppliers ("akt sverki") (**A-M**).

## 18. What pharmacy software offers, and what owners need

**Reference products (research only, never demo data).** Uzbekistan: **F-Apteka** by FOM Group — modules for receiving, write-offs and returns, transfers, retail and reservations, cash and shifts, pricing with reference-price control, price tags, defektura, staff motivation, inventory, analytics, discounts, supply, and integrations with Didox (e-invoices), Asl belgisi, DMED (e-prescriptions) and Click/Payme/Uzum; it feeds the consumer price aggregator Arzon Apteka (FOM knowledge base, read 21.10.2026, **V-H**). 1C is widespread (F-Apteka imports from it). Russia: Solaris, Инфо-Аптека, М-Аптека плюс, еФарма2, Saby; Kazakhstan: 1C with Pharmcenter.kz price lists (**V2-H**).

**Feature catalogue** (standard in CIS pharmacy systems; **V-H** where a source shows it, **A-H** otherwise):

| Area | How it works |
|---|---|
| Product card | INN, trade name, form, strength, pack count ("№20"), divisibility (e.g. 2 blisters × 10), manufacturer, country, Rx flag, storage, several EAN-13 barcodes, marking flag, ATC code, registration number, pharmacological group, controlled flag. Uzbek additions: MXIK code (**V-H**), reference price for Rx (**V-H**), socially significant flag (**V-H**), mandatory-assortment flag (**S-L**). Search must cope with Uzbek Latin, Uzbek Cyrillic, Russian and spelling variants (farmatsevt / farmasevt / farmaseft) (**V-H**) |
| Batches | Stock per batch: series, expiry, purchase price, supplier, invoice, marking codes; retail price can be per batch; the till suggests the nearest expiry (FEFO) and refuses expired goods (Saby, **V-H**) |
| Near expiry | Reports by expiry; the head discounts them (**V-H**); thresholds 180/90/60/30 days; return, transfer, mark down or push (**A-M**); deliveries with short remaining shelf life (under 6–12 months or 50–60 % of the total) refused (**A-M**) |
| Receiving | Import the e-invoice or delivery note → match to the order → check quantities, series, expiry, prices (and Rx prices against reference) → scan DataMatrix and compare → accept, price, print tags, attach quality certificates → discrepancy act and claim (**V-H** for the Uzbek product's steps) |
| Payables | Due date = invoice date + the contract's deferral; aging; payment calendar; reconciliation acts (**A-H**). Uzbek terms in days: **not found** |
| Returns, write-offs, quarantine | Separate documents with reasons and acts; quarantine area; checking stock against rejected series (**V-H**) |
| Transfers | A document listing series; goods in transit until the receiving branch accepts; codes move with them (**A-H**; **V-H** for the Uzbek product's menus) |
| Counts | Full counts periodically and when the materially responsible person changes; partial counts by shelf or category, monthly for high-value and controlled items; scanners or phones; shortages often deducted from staff pay under collective liability in CIS practice (**A-M**) |
| Defektura and refusals | (a) items normally stocked at zero or below minimum; (b) requests that couldn't be served, logged at the till; both feed ordering (**A-H**; **V-H** for headings) |
| Ordering | Min/max with average daily sales and ABC/XYZ classes; supplier choice by price, expiry, minimum lot, supplier stock, deferral and discounts; a manual order of up to 5 hours cut to about 1 (Pharmvestnik 2017, **V2-H**); matching each distributor's codes to your catalogue is the hard part (**A-H**) |
| Pricing and tags | Markup rules by group, supplier or price band; repricing documents; tag templates (**V-H**). Uzbek rule: Rx = min(purchase × 1.20, reference price); socially significant purchase × 1.10; OTC free (**V-H** for the rule) |
| Substitutes | Same INN, form and strength, with stock and price across branches (**A-H**); one minimum reference price per INN across trade names makes INN grouping matter (**V-H**) |
| Analytics | ABC/XYZ (**V2-H**); dead stock = no movement for more than 90 days ("lazy items" in the Uzbek product, **V-H**); margin by product, category and supplier; expiry losses; lost sales from refusals (**A-H**); owner KPIs: net and gross profit, turnover, receipts, average check, packs per receipt, discounts, dead-stock share, payroll (**V-H**) |
| Staff KPIs and pay | Average check, packs per receipt, discount share, add-on sales, sales of priority ("marketing") products, plan completion (**V-H** names); fixed pay plus a percentage of sales or a per-pack bonus on priority items (**A-M**) |
| Loyalty, cash discipline | Bonus points, manual discounts for pensioners, campaign reports; shift open and close times, tracking of cancellations and manual discounts; offline till that syncs later (**V-H**) |
| Rx and controlled | Rx flag and prescription or e-prescription number at sale; separate quantity registers and storage for narcotic, psychotropic, potent and poisonous drugs and precursors; controlled access to the storage area (**V-H** for access, **A-H** for the rest) |
| Back margin | Manufacturers and distributors pay for displays, priority recommendations and sales plans; the Uzbek product has a "back margin" glossary entry (**V-L**); software tracks contracts, plans, covered sales and bonus receivable (**A-M**) |
| Reservations | Reservation register for aggregator and online orders (**V-H**) |

**What owners need, in order** (**A-M**, from everything above): (1) compliance without thinking — Rx caps at receiving and sale, marking scans, MXIK codes, e-invoice receiving; (2) stock per batch and expiry with FEFO and 90/60/30-day alerts; (3) cash control and theft prevention — shift cash by method, Z-report against system sales, alerts on cancellations, returns and manual discounts, count shortages per responsible person; (4) purchasing — consolidated price lists, the cheapest acceptable supplier, order proposals from sales speed, defektura; (5) supplier debt by due date; (6) a multi-branch view — revenue, receipts, average check and margin per branch, transfers to rebalance near-expiry stock, staff KPIs; (7) online presence — stock and price feed to aggregators, reservations.

**Owner pain points:** price-compliance fines and licence loss; frequent reference-price changes (**V-H**); unmarked or undocumented goods and marking discrepancies at receiving (**V-H**); chain consolidation and the distributor shake-out (**V2-M**); staff theft, tax fines, dead stock, unprofitable range, bad supplier terms (**V-H** as topics in the Uzbek product's case list); slow manual ordering (**V2-H**, Kazakhstan); counterfeit and smuggling (**V2-M**); expiry losses, cash leakage, supplier debt (**A-M**).

## 19. Market shape

| Metric | Value | Data date | Tag | Source |
|---|---|---|---|---|
| Retail market | **25.9 trillion so‘m** (+28 % in value), **0.86 bn packs** (+6 %); Rx 60–70 % of value | Dec 2024–Nov 2025 | V2-H | IQVIA via podrobno.uz 20.01.2026 |
| Average pack price | ≈ 30 000 so‘m (25.9 trillion ÷ 0.86 bn) | 2025 | A-M | own calculation |
| Fiscal-receipt spending on medicines | 19.7 trillion so‘m (imported 15.7, local 4.0); Tashkent 5 trillion (> 25 %), 1.7 mln so‘m per person vs ≈ 0.3 mln in the south | 2024 | V2-H | Tax Committee via spot.uz 03.03.2025 |
| Pharmacies | > 12 000 (agency head, July 2025); > 13 000 sold medicines in 2024; 15 799 licensed outlets in 2022 (Tashkent 2 338); 8 575 registered pharmacy taxpayers and ≈ 16 000 cash registers (2024); 7 652 pharmacy organisations on Asl belgisi (2025); 8 360 licensed pharmacies and 3 945 branches (Oct 2025) | 2022–2025 | V2-H / V2-M | gazeta.uz 02.07.2025; eurasiatoday 06.03.2026; UzA via upl.uz 21.03.2023; spot.uz 03.03.2025; podrobno.uz 25.09.2026; kun.uz 09.10.2025 |
| Estimate | Tashkent 2 300–3 000 outlets; nationally 13 000–16 000 | 2026 | A-L | — |
| Chains | Independents dominate; the largest chain group grew from 323 to 442 outlets in 2025; share of chains not found (estimate: chains of 10+ hold 15–25 % of outlets, 25–35 % of sales) | 2025–2026 | V2-M / A-L | podrobno.uz 31.01.2025; INFOLine 26.05.2026 |
| Distributors | > 370, down from 580 in 2023 (storage rules forced out over 200); top four held ≈ 32 % in 2021 | 2021–2025 | V2-H / V2-M | gazeta.uz 02.07.2025; spot.uz 08.10.2021 |
| Payment terms | Not found in any Uzbek source; demo assumption: new or small independents prepay or 7–14 days, established 14–30, chains 30–60, some local makers on consignment | — | A-L | — |
| Revenue per pharmacy | ≈ 4.5–5.5 mln so‘m a day on average (market ÷ outlets); small 1.5–4 mln, typical 3–7, busy or near a hospital 10–25, large 24/7 15–40 | 2025 | A-M / A-L | derived |
| Average check, packs per receipt, receipts | 45 000–65 000 so‘m; 1.5–2.2 packs; 60–150 receipts a day (250–500 for flagships). Cross-checks: national cashback average receipt 94 200 so‘m (all retail, 2025, **S-M**) | 2025–2026 | A-L | derived |
| Range stocked | 1 500–3 000 items (small), 3 000–6 000 (large) | — | M | Astana Hub (Kazakhstan) |
| Shelf prices (Tashkent) | Cheap local and CIS generics 1 500–12 000 so‘m; imported brands 20 000–150 000; the same item differs 15–40 % between pharmacies (examples: paracetamol-caffeine №100 29 400–31 900; ibuprofen 200 mg №50 8 000–10 700; ibuprofen 400 mg №10 22 000–28 000; triptan №6 125 000–152 400) | Oct 2026 | V2-M | liki.uz, accessed 21.10.2026 |
| Margins | Not found; assumption: Rx markup 12–20 %, OTC 25–40 %, cosmetics and supplements 30–60 %; blended markup 20–30 % (gross margin 17–23 %); expiry write-offs 0.5–2 % of turnover | — | A-L | — |
| Payments | Card acceptance mandatory for new licensees from 01.09.2025 (**V-H**); apps make up more than half of cashless operations nationally (**V2-M**); target 75 % cashless in retail by 2030 (**S-M**). Pharmacy shares not found; assumption for Tashkent: cash 35–45 %, cards 30–40 %, QR and apps 20–30 % (regions: cash 50–70 %) | 2025–2026 | A-L | podrobno.uz 21.03.2026 |
| Shifts | Day, evening and night shifts; "2 va 2" (two on, two off) and third shifts; night staff called "ночники" | Oct 2026 | V-H | OLX Tashkent ads |
| Staffing | Small pharmacy 2–3 pharmacists (one per shift); medium 4–6 (two at peak); 24/7 6–9; the head often works shifts | — | A-M | — |
| Pay (Tashkent, Sep–Oct 2026) | Most ads 3–8 mln so‘m a month (bands 4–6, 4–8); night or experienced 4–10 mln (some 12); heads up to 10–20 mln; chain ads 3–10 mln; product managers 15–25 mln; medical representatives 8–15 mln | Oct 2026 | V-H | OLX, hh.uz |
| Licence enforcement | 2026: 25 pharmacies sanctioned for no licence in Q1, 23 licences annulled | 2026 | S-M | anhor.uz |

**Demo parameter sheet** (used by plan §14.3; **A** unless tagged): tenant mix 60 % single pharmacies, 30 % micro-chains (2–8), 10 % chains (15–60); revenue per branch 1.5–25 mln so‘m a day (median ≈ 4 mln); average check 45 000–65 000 so‘m; 1.5–2.2 packs per receipt; 1 500–6 000 items (M); Rx ≈ 60–70 % of value (V2-H); markups Rx ≤ 20 % (V-H rule), OTC 25–40 %; 5–15 suppliers with 0–60 days; payment mix in Tashkent cash 40 / card 35 / QR and apps 25; hours 08:00–21:00 or 23:00, ≈ 10 % of branches 24/7; pharmacist pay 4–7 mln so‘m a month (V-H); near-expiry thresholds 180/90/60/30 days; dead stock after 90 days without sales (V-H).

## 20. Glossary (en / uz / ru)

Uzbek column: literary form first, then "·" and the colloquial form pharmacists use, including Russian loanwords. Confidence (H/M/L) is for the Uzbek form; L rows must be checked with a practising Tashkent pharmacist before they go into the UI. Sources: Uzbek legal texts on lex.uz (Law 415-I and others), Tashkent job ads (OLX, hh.uz, Sep–Oct 2026), liki.uz Uzbek pages, the Uzbek reference product's knowledge base, and the research reports.

| # | English | Uzbek (literary · colloquial) | Russian | Note | Conf. |
|---|---|---|---|---|---|
| 1 | Pharmacy | dorixona · apteka | аптека | Both in ads | H |
| 2 | Pharmacy chain | dorixonalar tarmog‘i · apteka seti | аптечная сеть | "… tarmog‘iga" in ads | H |
| 3 | Branch | filial (formal: bo‘linma) | филиал | | H |
| 4 | Social pharmacy | ijtimoiy dorixona | социальная аптека | CM No. 334 | H |
| 5 | 24-hour / on-duty pharmacy | kecha-kunduz ishlaydigan dorixona; navbatchi dorixona · kruglosutochniy | круглосуточная / дежурная аптека | Usage frequency not checked | M |
| 6 | Medicine | dori; dori-darmon (collective) | лекарство | | H |
| 7 | Medicinal product | dori vositasi (pl. dori vositalari); dori preparati | лекарственное средство / препарат | Law 415-I art. 2 | H |
| 8 | Medical device | tibbiy buyum · medtovar | медицинское изделие / медтовары | Legal term | H |
| 9 | INN; generic | xalqaro patentlanmagan nom (XPN) · MNN, ta’sir qiluvchi modda; generik | МНН; дженерик | Law defines "generik dori vositalari" | H / M |
| 10 | Trade name | savdo nomi · nazvaniye, brend | торговое наименование | | M |
| 11 | Dosage form | dori shakli · forma | лекарственная форма | | M |
| 12 | Tablet | tabletka | таблетка | | H |
| 13 | Capsule | kapsula | капсула | | H |
| 14 | Syrup | sirop | сироп | | M |
| 15 | Ampoule | ampula | ампула | "5 ampulalar" on liki.uz | H |
| 16 | Injection solution | in’yeksiya uchun eritma · ukol | раствор для инъекций | | H |
| 17 | Ointment | malham · maz | мазь | | M |
| 18 | Drops; eye drops | tomchilar · kapli; ko‘z tomchilari | капли; глазные капли | | H |
| 19 | Suspension | suspenziya | суспензия | | H |
| 20 | Powder | kukun · poroshok | порошок | | M |
| 21 | Suppository | sham (rektal sham), suppozitoriy · svecha | суппозиторий / свеча | | M |
| 22 | Strength (dosage) | dozasi · dozirovka, "necha mg" | дозировка | | M |
| 23 | Pack | qadoq · upakovka, karobka | упаковка | Pack count written "№20" | M |
| 24 | Blister, strip | blister · plastinka | блистер / пластинка | | M |
| 25 | Piece, unit | dona | штука (шт.) | | H |
| 26 | Selling part of a pack | qadoqni bo‘lib sotish · plastinkalab / donalab sotish | продажа частями | Common with №100 boxes | L |
| 27 | Manufacturer | ishlab chiqaruvchi · zavod | производитель | Country: ishlab chiqarilgan mamlakat | H |
| 28 | Distributor, supplier | distribyutor; yetkazib beruvchi · postavshik | дистрибьютор / поставщик | Importer: import qiluvchi; official dealer: rasmiy diler (M) | H |
| 29 | Wholesaler | ulgurji savdo korxonasi · optovik | оптовик | Law term | H |
| 30 | Price list | narxlar ro‘yxati · prays | прайс-лист | | M |
| 31 | Order to a supplier | buyurtma · zakaz, zayavka | заказ / заявка | | H |
| 32 | Invoice | hisob-faktura · faktura | счёт-фактура | | H |
| 33 | Electronic invoice | elektron hisobvaraq-faktura (EHF) · e-faktura, "Didox" | электронный счёт-фактура (ЭСФ) | | H |
| 34 | Delivery note | yuk xati · nakladnoy | накладная | Colloquial form dominates | M / H |
| 35 | Receipt of goods | tovarni qabul qilish; kirim · prixod, priyomka | приход / приёмка | | H |
| 36 | Batch, series | seriya; partiya (a delivery lot) | серия / партия | | H |
| 37 | Expiry date | yaroqlilik muddati · srok | срок годности | | H |
| 38 | Near expiry | yaroqlilik muddati tugayotgan · srogi yaqin, korotkiy srok | истекающий срок | | M |
| 39 | Expired | yaroqlilik muddati o‘tgan · prosrochka | просроченный | Legally "sifatsiz dori vositasi" | H |
| 40 | Unfit; substandard | yaroqsiz; sifatsiz | непригодный; недоброкачественный | CM No. 185 Annex 3 | H |
| 41 | Falsified; counterfeit | qalbakilashtirilgan · poddelka, falsifikat; kontrafakt | фальсифицированный; контрафактный | Defined in law | H |
| 42 | Rejected goods | brak (yaroqsiz deb topilgan mahsulot) | забракованная продукция | | M |
| 43 | Write-off | hisobdan chiqarish · spisaniye | списание | | H |
| 44 | Destruction; destruction act | yo‘q qilish; yo‘q qilish dalolatnomasi · utilizatsiya akti | уничтожение; акт уничтожения | "yo‘q qilish" in law | M |
| 45 | Act (signed record) | dalolatnoma · akt | акт | | H |
| 46 | Quarantine | karantin (zonasi) | карантин | | M |
| 47 | Withdrawal from circulation | muomaladan chiqarish | вывод из оборота / изъятие | Marking term | H |
| 48 | Return to a supplier | yetkazib beruvchiga qaytarish · vozvrat | возврат поставщику | | H |
| 49 | Return from a customer | xaridordan qaytarib olish · vozvrat | возврат от покупателя | Medicines: not allowed | M |
| 50 | Transfer between branches | filiallararo ko‘chirish · peremesheniye, perebroska | перемещение | | M |
| 51 | Stock balance | qoldiq · ostatka | остаток | | H |
| 52 | Stock count | inventarizatsiya; xatlov · reviziya | инвентаризация / ревизия | | H |
| 53 | Shortage; surplus | kamomad · nedostacha; ortiqcha · izlishka | недостача; излишек | | H / M |
| 54 | Defektura (out-of-stock list) | defektura · yetishmayotgan dorilar ro‘yxati | дефектура | A request not served: "otkaz" (L) | M |
| 55 | Minimum stock | minimal qoldiq · minimalka | минимальный остаток | Owners say "min" | M |
| 56 | Dead stock | sotilmay yotgan tovar · nelikvid | неликвид | No movement for 90+ days | M |
| 57 | Markup; maximum markup | ustama (savdo ustamasi) · natsenka; eng yuqori (chegaraviy) savdo ustamasi | наценка / торговая надбавка; предельная надбавка | Rx cap 20 % | H |
| 58 | Reference price | referent narx | референтная цена | Rx only | H |
| 59 | Discount | chegirma · skidka | скидка | | H |
| 60 | Price tag | narx yorlig‘i · tsennik | ценник | | M |
| 61 | Retail price | chakana narx | розничная цена | Wholesale: ulgurji narx | H |
| 62 | Purchase price | xarid narxi · prixod narxi | закупочная цена | | M |
| 63 | Margin; back margin | yalpi foyda · marja; bek-marja, "marketing" | маржа; бэк-маржа | Back margin: L | M / L |
| 64 | Prescription | retsept | рецепт | Law term | H |
| 65 | E-prescription | elektron retsept | электронный рецепт | The state module "Elektron retsept" | H |
| 66 | Prescription-only | retsept bo‘yicha beriladigan · retseptli | рецептурный | | M |
| 67 | Over the counter | retseptsiz beriladigan · retseptsiz | безрецептурный | OTC list title | H |
| 68 | Prescription register | retseptlarni ro‘yxatga olish jurnali | журнал регистрации рецептов | CM No. 185 Annex 2, Annex 1 | L |
| 69 | Narcotic drugs | giyohvandlik vositalari · narkotik | наркотические средства | Law 813-I title | H |
| 70 | Psychotropic substances | psixotrop moddalar | психотропные вещества | | H |
| 71 | Precursors | prekursorlar | прекурсоры | | H |
| 72 | Strong-acting substances | kuchli ta’sir qiluvchi moddalar | сильнодействующие вещества | CM No. 818 | H |
| 73 | Subject-quantitative accounting | predmet-miqdoriy hisob · PKU | предметно-количественный учёт (ПКУ) | Uzbek form not seen in a source | L |
| 74 | Analog, substitute | analog; o‘rnini bosuvchi dori · zamena | аналог / замена | | M |
| 75 | Storage conditions | saqlash sharoitlari | условия хранения | | H |
| 76 | Cold chain | sovuq zanjiri | холодовая цепь | | M |
| 77 | Refrigerator | sovutgich · xolodilnik | холодильник | | H |
| 78 | Thermometer; hygrometer | termometr · gradusnik; gigrometr | термометр; гигрометр | Humidity: namlik | H |
| 79 | Temperature log | harorat qayd etish jurnali · jurnal | журнал учёта температуры | | M |
| 80 | Pharmacist (higher education) | provizor | провизор | | H |
| 81 | Pharmacist (college) | farmatsevt · farmasevt, farmaseft | фармацевт | Spelling variants in ads | H |
| 82 | Head of pharmacy | dorixona mudiri (mudirasi) · zav, zavapteka | заведующий аптекой | | H |
| 83 | Licence | litsenziya | лицензия | | H |
| 84 | Specialist certificate; qualification category | mutaxassis sertifikati · sertifikat; malaka toifasi | сертификат специалиста; квалификационная категория | "diplom va sertifikat … litsenziya uchun" in ads | M |
| 85 | GPP | Zarur dorixona amaliyoti (GPP) | Надлежащая аптечная практика | Uzbek name from one source | M |
| 86 | Shift; night shift | smena; tungi smena · nochnoy, nochnik; kunduzgi / kechki smena | смена; ночная смена | 2/2 schedule: "2 va 2" | H |
| 87 | Online cash register; Z-report | onlayn nazorat-kassa mashinasi (onlayn-NKM), virtual kassa · kassa; Z-hisobot · Z-otchyot | онлайн-ККМ / виртуальная касса; Z-отчёт | | H / M |
| 88 | Fiscal receipt; goods receipt | fiskal chek · chek; tovar cheki | фискальный чек; товарный чек | | H / M |
| 89 | Cash; card; QR payment | naqd pul · nalichka; bank kartasi · plastik (Uzcard, Humo); QR-kod orqali to‘lov · "Click/Payme qilish" | наличные; банковская карта; оплата по QR | | H / M |
| 90 | Deferred payment; due date | nasiya · otsrochka; to‘lov muddati | отсрочка платежа; срок оплаты | Consignment: realizatsiya | H |
| 91 | Debt to a supplier | kreditorlik qarzdorligi · qarz, dolg | кредиторская задолженность | Reconciliation act: solishtirma dalolatnoma · akt sverki | H |
| 92 | Loyalty card | sodiqlik kartasi · bonus karta, diskont karta | карта лояльности / дисконтная карта | | M |
| 93 | Average check | o‘rtacha chek | средний чек | Items per receipt: chekdagi mahsulotlar soni | H |
| 94 | Sales; revenue | savdo, sotuv; tushum · viruchka, kassa | продажи; выручка | | H |
| 95 | Digital marking | raqamli markirovka · markirovka | цифровая маркировка | Asl belgisi | H |
| 96 | Marking code (DataMatrix) | markirovka kodi; DataMatrix kodi | код маркировки | | H |
| 97 | Barcode | shtrix-kod | штрихкод | | H |
| 98 | Product classifier code | MXIK kodi · IKPU | ИКПУ | tasnif.soliq.uz | H |
| 99 | Personal ID number | JShShIR | ПИНФЛ | Used to check e-prescriptions; never stored by 911 | H |
| 100 | VAT; turnover tax | qo‘shilgan qiymat solig‘i (QQS); aylanmadan olinadigan soliq | НДС; налог с оборота | Base calculation value: BHM (bazaviy hisoblash miqdori) | H |

## 21. Open questions and gaps

1. **Licence passport** under CM No. 80 (Uzbek only): premises, area, equipment and staff requirements and the list of gross violations.
2. **Storage journals:** humidity limits, instruments, and how often readings must be recorded (and in what form).
3. **Asl belgisi:** partial-pack sales and write-offs (expiry, damage, destruction, theft); API documentation and sandbox (ask CRPT Turon).
4. **Cash registers:** what the edition in force from 22.10.2026 changes; whether a package code per line is required.
5. **E-prescriptions:** whether the May 2026 draft was adopted and e-prescriptions now cover all Rx medicines; whether an integration API exists for pharmacy software.
6. **Taxes:** whether pharmacies may use the 6 % simplified VAT; whether the UP-229 VAT obligation was ever written into the Tax Code; whether the Soliq cashback still runs.
7. **Socially significant medicines:** confirm the 10 % cap in a primary text.
8. **Qualifications:** the replacement of the repealed attestation regulation; the text and number of the 19.10.2026 registration resolution.
9. **Controlled substances:** whether the narcotics/psychotropics activity is a separate licence document; the exact book layouts (Annexes 3, 4, 18) for printing.
10. **Market:** pharmacy-specific average check, payment mix, gross margins and distributor payment terms (ask two or three owners).
11. **Glossary:** confirm every L row with a practising pharmacist.

## 22. Sources (all accessed 21.10.2026 unless a date is given)

Primary legal texts (lex.uz, consolidated editions):
- Law No. 415-I "On medicines and pharmaceutical activity" (edition ZRU-399): https://lex.uz/ru/docs/2856466; Uzbek text https://lex.uz/docs/-8437
- CM No. 185 of 06.04.2017 (retail regulation, Annex 2; destruction, Annex 3; edition 03.07.2026): https://lex.uz/ru/docs/3155770
- CM No. 80 of 21.02.2022 (licensing): https://lex.uz/ru/docs/5870217; CM No. 284 of 12.05.2017: https://lex.uz/ru/docs/3204383
- CM No. 334 of 03.05.2018 (social pharmacies): https://lex.uz/ru/docs/3719680
- Decree UP-20 of 23.01.2024: https://lex.uz/ru/docs/6774918
- Decree UP-13 of 28.01.2025: https://lex.uz/ru/docs/7345614
- Decree UP-137 of 19.08.2025: https://lex.uz/ru/docs/7697214
- Decree UP-74 of 05.05.2026: https://lex.uz/ru/docs/8180401
- Decree UP-100 of 26.05.2026: https://lex.uz/ru/docs/8237115
- PP-4438 of 06.09.2019: https://lex.uz/ru/docs/4501282
- PP-190 of 23.05.2025: https://lex.uz/ru/docs/7540341
- CM No. 149 of 02.04.2022 (marking of medicines): https://lex.uz/ru/docs/5936145
- CM No. 23 of 23.01.2026 (marking): https://lex.uz/ru/docs/8012407 (Russian: 8012594)
- CM No. 788 of 18.09.2019 (GxP): https://lex.uz/docs/4520726
- CM No. 818 of 27.09.2019 (strong-acting list): https://lex.uz/ru/docs/4532171
- MoH order No. 36, reg. No. 3604 (narcotics, psychotropics, precursors): https://lex.uz/ru/docs/7349574
- MoH order No. 25, reg. No. 3725 (e-prescription phases): https://lex.uz/ru/docs/7920485
- MoH order No. 21, reg. No. 2649 (old attestation, repealed): https://lex.uz/ru/docs/2543185
- MoH order No. 17, reg. No. 2990 (compounding pharmacies): https://lex.uz/docs/3606685
- SanQvaN 0071-24 (pharmacy sanitary rules): https://lex.uz/docs/-6915942; SanPiN 0243-07: https://lex.uz/docs/1912039
- CM No. 75 of 13.02.2003 (retail trade rules): https://lex.uz/ru/docs/243233 (appendix not read)

Government and operators:
- gov.uz, night and overtime pay guidance: https://gov.uz/ru/advice/554/document/2215
- Competition and Consumer Protection Committee, returns (08.08.2023): https://raqobat.gov.uz/ru/poryadok-vozvrata-tovara-nadlejashhego-kachestva/
- CRPT Turon, retail marking page: https://crpt-turon.uz/tovarnaya-kategoriya/lekarstvennye-sredstva/roznichnaya-torgovlya/
- Telegram Mini Apps documentation: https://core.telegram.org/bots/webapps; MDN BarcodeDetector: https://developer.mozilla.org/en-US/docs/Web/API/BarcodeDetector

Secondary sources (opened):
- buxgalter.uz: pharmacy requirements from 01.09.2025 (11.08.2025) https://buxgalter.uz/publish/doc/text209962_kakie_trebovaniya_k_aptekam_v_uzbekistane_vvodyatsya_s_1_sentyabrya_2025_goda; VAT for pharmacies (01.04.2025) https://buxgalter.uz/publish/doc/text207438_doljny_li_apteki_i_meduchrejdeniya_pereyti_na_nds_s_1_aprelya; selling after the end of markup caps (01.04.2025) https://buxgalter.uz/publish/doc/text207435_kak_prodavat_lekarstva_i_medizdeliya_posle_otmeny_predelnoy_nacenki; Tax Code art. 227-1 violations (28.12.2023) https://buxgalter.uz/publish/doc/text195437_narusheniya_po_state_227-1_nalogovogo_kodeksa_respubliki_uzbekistan
- nrm.uz, cash-register regulation summary: https://nrm.uz/contentf?doc=608532_1_obshchie_polojeniya&products=2_maloe_predpriyatie
- kun.uz, GPP certification fees (09.10.2025): https://kun.uz/ru/news/2025/10/09/otkuda-vzyalis-takiye-rassenki-aptechnyy-biznes-jaluyetsya-na-novyy-obyazatelnyy-platej
- gazeta.uz: agency head interview (02.07.2025) https://www.gazeta.uz/ru/2025/07/02/drugs/; e-prescription uptake (20.01.2026) https://www.gazeta.uz/ru/2026/01/20/e-receipt/; e-prescription draft (01.05.2026) https://www.gazeta.uz/ru/2026/05/01/e-receipt/
- spot.uz: Rx list and e-prescriptions (12.12.2025) https://www.spot.uz/ru/2025/12/12/electronic-prescription/; e-prescription draft (01.05.2026) https://www.spot.uz/ru/2026/05/01/prescriptions-stop/; online sales plan (14.04.2026) https://www.spot.uz/ru/2026/04/14/pharmacies-online; VAT (11.06.2026) https://www.spot.uz/ru/2026/06/11/vat-increase/; pharma market 2024 (03.03.2025) https://www.spot.uz/ru/2025/03/03/pharma; market review (08.10.2021) https://www.spot.uz/ru/2021/10/08/pharmacy/
- norma.uz: OTC list (02.08.2021) https://www.norma.uz/novoe_v_zakonodatelstve/obnovlen_perechen_bezrecepturnyh_preparatov; e-prescription regulation (12.09.2025) https://www.norma.uz/novoe_v_zakonodatelstve/kak_budut_vypisyvat_elektronnyy_recept
- podrobno.uz: worker registration (21.10.2026) https://podrobno.uz/cat/obchestvo/v-uzbekistane-mediki-i-farmatsevty-dolzhny-budut-prokhodit-gosudarstvennuyu-registratsiyu-kazhdye-pya; OTC caps abolished (29.01.2025) https://podrobno.uz/cat/obchestvo/v-uzbekistane-perestanut-regulirovat-tseny-na-bezretsepturnye-lekarstva/; "From factory to pharmacy shelf" (25.09.2026) https://podrobno.uz/cat/obchestvo/ot-zavoda-do-aptechnoy-polki-chto-proiskhodit-s-lekarstvom-po-doroge-k-patsientu/; IQVIA 2025 (20.01.2026) https://podrobno.uz/cat/economic/farmatsevticheskiy-rynok-uzbekistana-vyshel-v-lidery-evrazii-po-itogam-2025-goda/; market structure (31.01.2025) https://podrobno.uz/cat/obchestvo/rynok-aptek-v-uzbekistane-dvizhetsya-k-modeli-vostochnoy-evropy-mnenie-eksperta/; payments (21.03.2026) https://podrobno.uz/cat/obchestvo/bolshe-poloviny-cherez-smartfon-kak-menyaetsya-rynok-platezhey-v-uzbekistane/
- anhor.uz: unlicensed pharmacies (17.04.2026) https://anhor.uz/uzl/news/litsenziyasiz-faoliyat-yuritgan-25-ta-dorixona-javobgarlikka-tortildi/; overpricing (2026) https://anhor.uz/news/vlast/
- upl.uz / UzA, pharmacy counts 2018–2022 (21.03.2023): https://upl.uz/obshestvo/32310-news.html
- eurasiatoday.ru, 24 trillion so‘m in 2024 (06.03.2026): https://eurasiatoday.ru/70-lekarstv-mestnogo-proizvodstva-farmatsevticheskij-rynok-uzbekistana-dostig-2-5-mlrd/
- INFOLine, chain growth (26.05.2026): https://infoline.spb.ru/news/?news=307491
- nuz.uz, new pharmacy rules (27.05.2025): https://nuz.uz/2025/05/27/prodazha-lekarstv-v-uzbekistane-stanet-strozhe-vvodyatsya-novye-pravila/
- OLX Tashkent pharmacist ads (Sep–Oct 2026): https://www.olx.uz/rabota/meditsina-farmatsiya/farmacevt/tashkent/q-фармацевт/; hh.uz: https://hh.uz/search/vacancy?text=фармацевт&area=2759
- liki.uz Tashkent prices: https://liki.uz/shop/substance/paratsetamol/pharmacy/tashkent_r1713, https://liki.uz/shop/bosh-ogrigi-uchun/pharmacy/tashkent_r1713
- FOM Group knowledge base (F-Apteka): https://docs.superhuman.com/@fom/baza-znaniy (KPIs: /-7; Arzon Apteka: /4-arzonapteka-113)
- Saby, pharmacy automation: https://saby.ru/articles/retail/avtomatizaciya_apteki; Pharmvestnik, automatic ordering (09.10.2017): https://pharmvestnik.ru/content/articles/vytesnitj-ruchnoj-trud.html; Astana Hub, Pharmateka auto-order task (2025): https://astanahub.com/ru/tech_task/nastroit-avtozakaz-v-apteke

Seen in snippets only (not opened): norma.uz on reference-price calculation; tax-legal.uz on night hours; uzpharm-control.uz rejected-series lists; help.crpt-turon.uz (403); MoH reg. 3735 (https://lex.uz/uz/docs/7952213); reg. 3758; the 389-item OTC list (spot.uz 12.12.2025); Sputnik's 72-trillion figure (20.04.2026); kun.uz on cashback (08.07.2026); zamin.uz on the mandatory assortment list; Golden Pages pharmacy hours.
