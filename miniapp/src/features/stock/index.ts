/**
 * The pharmacist's stock screens (PLAN-OWNER §14.17, package P) on the stock module's employee
 * endpoints (`backend/apps/inventory/api.py`): stock lookup (typed, or scanned where the phone
 * reads EAN-13 and the company allows it), the product with its batches, other pharmacies and
 * analogs, the expiry check, defektura, transfers in, the blind count, receiving and the
 * prescription entry. Home: "4 batches expire within 30 days here" and the transfers to count;
 * Me: Stock; (+): Defektura and Receive goods; the monthly expiry shelf check task opens the
 * expiry check. Shown while the company has the stock module on, to people who may read stock.
 *
 * Deep links (inline [Open] of the stock notices): `stock` (the lookup), `stock.expiry`,
 * `stock.transfer:<id>`, `stock.count:<id>`, `stock.receive:<id>`.
 */
import { FilePlus2, PackagePlus, Pill } from "lucide-react";
import { lazy } from "react";

import { defineFeature } from "../registry";
import { operatesStock, stockVisible } from "./access";
import { messages } from "./messages";
import { ExpiryCard, IncomingCard, ShelfCheckBlock, useMeStatus } from "./slots";

export default defineFeature({
  id: "stock",
  messages,
  visible: (member) => stockVisible(member),
  pages: {
    home: lazy(() => import("./StockPage")),
    product: lazy(() => import("./ProductPage")),
    expiry: lazy(() => import("./ExpiryPage")),
    transfers: lazy(() => import("./TransfersPage")),
    transfer: lazy(() => import("./TransferPage")),
    counts: lazy(() => import("./CountsPage")),
    count: lazy(() => import("./CountPage")),
    receive: lazy(() => import("./ReceivePage")),
  },
  sheets: {
    scan: lazy(() => import("./ScanSheet")),
    defektura: lazy(() => import("./DefekturaSheet")),
    writeoff: lazy(() => import("./WriteOffSheet")),
  },
  homeCards: [
    // Things to act on today: goods on their way here, then what expires.
    { id: "incoming", component: IncomingCard, order: 15, visible: operatesStock },
    { id: "expiry", component: ExpiryCard, order: 25, visible: operatesStock },
  ],
  meItems: [{ id: "stock", group: "work", label: "me.stock", icon: Pill, open: { page: "home" }, order: 20, useStatus: useMeStatus }],
  plusActions: [
    { id: "defektura", label: "plus.defektura", icon: FilePlus2, open: { sheet: "defektura" }, order: 50, visible: operatesStock },
    { id: "receive", label: "plus.receive", icon: PackagePlus, open: { page: "receive" }, order: 55, visible: operatesStock },
  ],
  // The expiry shelf check's own block, before "How to do this" (knowledge, 10).
  taskActions: [{ id: "shelfCheck", component: ShelfCheckBlock, order: 6 }],
  routes: {
    stock: "home",
    "stock.expiry": { page: "expiry" },
    "stock.transfer": { page: "transfer" },
    "stock.count": { page: "count" },
    "stock.receive": { page: "receive" },
  },
});
