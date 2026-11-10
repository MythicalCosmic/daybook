/**
 * "Hujjatlarim" (My documents) in the mini app (PLAN-OWNER §9.3 `features/hr/`, the employee rows
 * of §4.10): my profile (changing only phone, email, address, city, whether colleagues see my
 * birthday, and the pay card, masked back), emergency contacts (three at most), my documents
 * (open the file, upload a renewed one), my contract (its terms, the PDF, and "Tanishdim"), and
 * the rules of my position to read and sign ("O‘qidim va roziman"). Home shows a card while the
 * contract waits to be read, a rule waits to be signed or a document ran out; Me → My documents
 * and Me → Rules.
 *
 * Shown while the company has HR on, to approved people and to suspended ones (they keep reading
 * their file, §13.4; the server refuses their changes).
 *
 * Deep links (the bot's notices): `hr.contract`, `hr.documents`, `hr.policy:<id>`, `hr.policies`;
 * also `hr` for this page.
 */
import { BookOpenCheck, FolderOpen } from "lucide-react";
import { lazy } from "react";

import { hasModule, isSuspended } from "../../api/membership";
import { defineFeature } from "../registry";
import { messages } from "./messages";
import { ContractCard, DocumentCard, PoliciesCard, useMeStatus, usePoliciesStatus } from "./slots";

const sheets = () => import("./sheets");

export default defineFeature({
  id: "hr",
  messages,
  visible: (member) => hasModule(member, "hr") && (member.status === "approved" || isSuspended(member)),
  pages: {
    home: lazy(() => import("./HrPage")),
    contract: lazy(() => import("./ContractPage")),
    documents: lazy(() => import("./DocumentsPage")),
    policies: lazy(() => import("./PoliciesPage")),
    policy: lazy(() => import("./PolicyPage")),
  },
  sheets: {
    profile: lazy(() => sheets().then((module) => ({ default: module.ProfileSheet }))),
    contact: lazy(() => sheets().then((module) => ({ default: module.ContactSheet }))),
    upload: lazy(() => sheets().then((module) => ({ default: module.UploadSheet }))),
    document: lazy(() => sheets().then((module) => ({ default: module.DocumentSheet }))),
  },
  // Things to act on: read the contract, sign the rules, renew a document.
  homeCards: [
    { id: "contract", component: ContractCard, order: 40 },
    { id: "policies", component: PoliciesCard, order: 42 },
    { id: "document", component: DocumentCard, order: 45 },
  ],
  meItems: [
    { id: "documents", group: "documents", label: "me.documents", icon: FolderOpen, open: { page: "home" }, order: 10, useStatus: useMeStatus },
    { id: "policies", group: "documents", label: "me.policies", icon: BookOpenCheck, open: { page: "policies" }, order: 12, useStatus: usePoliciesStatus },
  ],
  routes: {
    hr: { page: "home", tab: "profile" },
    "hr.contract": { page: "contract", tab: "profile" },
    "hr.documents": { page: "documents", tab: "profile" },
    // The bot's "Open in app" on a rule to sign (`hr.policy:12`), and on several (`hr.policies`).
    "hr.policy": { page: "policy", tab: "profile" },
    "hr.policies": { page: "policies", tab: "profile" },
  },
});
