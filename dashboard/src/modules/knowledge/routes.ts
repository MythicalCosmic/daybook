/**
 * Routes of the knowledge base, children of /c/:companyId. The reading pages share a layout with
 * the spaces sidebar; the editor takes the whole width.
 */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "knowledge",
    component: () => import("./pages/KnowledgeLayout.vue"),
    meta: { title: "knowledge.title" },
    children: [
      { path: "", name: "knowledge.home", component: () => import("./pages/KnowledgeHome.vue"), meta: { title: "knowledge.title" } },
      { path: "s/:spaceId(\\d+)", name: "knowledge.space", component: () => import("./pages/SpacePage.vue"), meta: { title: "knowledge.title" } },
      { path: "p/:pageId(\\d+)", name: "knowledge.page", component: () => import("./pages/PageView.vue"), meta: { title: "knowledge.title" } },
    ],
  },
  {
    path: "knowledge/new",
    name: "knowledge.new",
    component: () => import("./pages/PageEditor.vue"),
    meta: { title: "knowledge.editor.newTitle", perm: "knowledge.manage" },
  },
  {
    path: "knowledge/p/:pageId(\\d+)/edit",
    name: "knowledge.edit",
    component: () => import("./pages/PageEditor.vue"),
    meta: { title: "knowledge.editor.editTitle", perm: "knowledge.manage" },
  },
];
