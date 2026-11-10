/**
 * Routes of HR, children of /c/:companyId (plan §6.1): the overview first, then documents (and the
 * compliance matrix), contracts, contract templates, celebrations, hiring (vacancies and each
 * one's pipeline board) and policies. Every page loads lazily.
 */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  { path: "hr", name: "hr.overview", component: () => import("./pages/HrOverviewPage.vue"), meta: { title: "hr.nav.overview", perm: "hr.view" } },
  { path: "hr/documents", name: "hr.documents", component: () => import("./pages/DocumentsPage.vue"), meta: { title: "hr.nav.documents", perm: "hr.view" } },
  { path: "hr/contracts", name: "hr.contracts", component: () => import("./pages/ContractsPage.vue"), meta: { title: "hr.nav.contracts", perm: "hr.view" } },
  {
    path: "hr/contract-templates",
    name: "hr.templates",
    component: () => import("./pages/TemplatesPage.vue"),
    meta: { title: "hr.nav.templates", perm: "hr.manage" },
  },
  {
    path: "hr/contract-templates/:templateId",
    name: "hr.template",
    component: () => import("./pages/TemplateEditorPage.vue"),
    meta: { title: "hr.nav.templates", perm: "hr.manage" },
  },
  { path: "hr/celebrations", name: "hr.celebrations", component: () => import("./pages/CelebrationsPage.vue"), meta: { title: "hr.nav.celebrations", perm: "hr.view" } },
  // Pharmacist coverage (plan §14.9): HR's, and the roster's (whoever runs attendance reads it too).
  { path: "hr/coverage", name: "hr.coverage", component: () => import("./pages/CoveragePage.vue"), meta: { title: "hr.nav.coverage", perm: ["hr.view", "attendance.view"] } },
  // Policies people read and sign: the list, one policy (people, text, versions), the editor.
  { path: "hr/policies", name: "hr.policies", component: () => import("./pages/PoliciesPage.vue"), meta: { title: "hr.nav.policies", perm: "hr.view" } },
  { path: "hr/policies/new", name: "hr.policy.new", component: () => import("./pages/PolicyEditorPage.vue"), meta: { title: "hr.nav.policies", perm: "hr.manage" } },
  { path: "hr/policies/:policyId(\\d+)", name: "hr.policy", component: () => import("./pages/PolicyPage.vue"), meta: { title: "hr.nav.policies", perm: "hr.view" } },
  { path: "hr/policies/:policyId(\\d+)/edit", name: "hr.policy.edit", component: () => import("./pages/PolicyEditorPage.vue"), meta: { title: "hr.nav.policies", perm: "hr.manage" } },
  // Hiring: vacancies with a bot link, and each one's pipeline board (apps/hr/hiring).
  { path: "hr/hiring", name: "hr.hiring", component: () => import("./hiring/pages/HiringPage.vue"), meta: { title: "hr.nav.hiring", perm: "hr.hiring" } },
  { path: "hr/hiring/:vacancyId(\\d+)", name: "hr.vacancy", component: () => import("./hiring/pages/VacancyPage.vue"), meta: { title: "hr.nav.hiring", perm: "hr.hiring" } },
];
