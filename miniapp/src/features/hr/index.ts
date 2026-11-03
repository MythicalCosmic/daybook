/**
 * "Hujjatlarim" (My documents) in the mini app (PLAN-OWNER §9.3 `features/hr/`, the employee rows
 * of §4.10): my profile (changing only phone, email, address, city, whether colleagues see my
 * birthday, and the pay card, masked back), emergency contacts (three at most), my documents
 * (open the file, upload a renewed one) and my contract (its terms, the PDF, and "Tanishdim").
 * Home shows a card while the contract waits to be read or a document ran out; Me → My documents.
 *
 * Shown while the company has HR on, to approved people and to suspended ones (they keep reading
 * their file, §13.4; the server refuses their changes).
 *
 * Deep links (the bot's notices): `hr.contract`, `hr.documents`; also `hr` for this page.
 */
import { FolderOpen } from "lucide-react";
import { lazy } from "react";

import { hasModule, isSuspended } from "../../api/membership";
import { defineFeature } from "../registry";
import { messages } from "./messages";
import { ContractCard, DocumentCard, useMeStatus } from "./slots";

const sheets = () => import("./sheets");

export default defineFeature({
  id: "hr",
  messages,
  visible: (member) => hasModule(member, "hr") && (member.status === "approved" || isSuspended(member)),
  pages: {
    home: lazy(() => import("./HrPage")),
    contract: lazy(() => import("./ContractPage")),
    documents: lazy(() => import("./DocumentsPage")),
  },
  sheets: {
    profile: lazy(() => sheets().then((module) => ({ default: module.ProfileSheet }))),
    contact: lazy(() => sheets().then((module) => ({ default: module.ContactSheet }))),
    upload: lazy(() => sheets().then((module) => ({ default: module.UploadSheet }))),
    document: lazy(() => sheets().then((module) => ({ default: module.DocumentSheet }))),
  },
  // Things to act on: read the contract, renew a document.
  homeCards: [
    { id: "contract", component: ContractCard, order: 40 },
    { id: "document", component: DocumentCard, order: 45 },
  ],
  meItems: [{ id: "documents", group: "documents", label: "me.documents", icon: FolderOpen, open: { page: "home" }, order: 10, useStatus: useMeStatus }],
  routes: {
    hr: { page: "home", tab: "profile" },
    "hr.contract": { page: "contract", tab: "profile" },
    "hr.documents": { page: "documents", tab: "profile" },
  },
});
