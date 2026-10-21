/**
 * The knowledge base in the mini app (plan §13.5, package Q): the spaces meant for the person,
 * their pages, search, and "I've read it" for must-read pages. Home shows a card while pages wait
 * to be confirmed; Me has the entry with the same count.
 */
import { BookOpen } from "lucide-react";
import { lazy } from "react";

import { defineFeature, type SlotProps } from "../registry";
import { useKbHome } from "./api";
import { messages } from "./messages";
import { ToReadCard } from "./ToReadCard";

function useToReadCount({ member }: SlotProps) {
  const home = useKbHome(member.companyId);
  return { badge: home.data?.to_read.length ?? null };
}

export default defineFeature({
  id: "knowledge",
  messages,
  visible: (member) => member.status === "approved",
  pages: {
    home: lazy(() => import("./KnowledgeHome").then((m) => ({ default: m.KnowledgeHome }))),
    space: lazy(() => import("./SpacePage").then((m) => ({ default: m.SpacePage }))),
    page: lazy(() => import("./PageReader").then((m) => ({ default: m.PageReader }))),
  },
  homeCards: [{ id: "toRead", component: ToReadCard, order: 40 }],
  meItems: [{ id: "kb", group: "documents", label: "me.kb", icon: BookOpen, open: { page: "home" }, useStatus: useToReadCount }],
  // ?screen=knowledge or knowledge.page:12 (inbox notifications), startapp=kb-12.
  routes: { knowledge: { page: "home", tab: "profile" }, kb: { page: "page", tab: "profile" } },
});
