import { describe, expect, it } from "vitest";

import {
  cleanIds,
  contractActions,
  contractDatesProblem,
  contractParams,
  documentParams,
  documentState,
  headcountKpi,
  groupDigits,
  hrAccess,
  idDisplay,
  insertPlaceholder,
  isMasked,
  kindGroup,
  needsSensitive,
  onProbation,
  placeholdersIn,
  shapeCompliance,
  unknownPlaceholders,
  weekCelebrations,
} from "../lib";
import type { Compliance, ContractActionFlags } from "../types";

describe("access", () => {
  it("reads only without hr.manage; manage implies view; sensitive is its own permission", () => {
    const grant = (perms: string[]) => (perm: string) => perms.includes(perm);
    expect(hrAccess(grant(["hr.view"]))).toEqual({ view: true, manage: false, sensitive: false });
    expect(hrAccess(grant(["hr.manage"]))).toEqual({ view: true, manage: true, sensitive: false });
    expect(hrAccess(grant(["hr.view", "hr.sensitive"]))).toEqual({ view: true, manage: false, sensitive: true });
    expect(hrAccess(grant([]))).toEqual({ view: false, manage: false, sensitive: false });
  });
});

describe("masked IDs and the reveal", () => {
  const profile = { pinfl: "3120•••••••045", passport: "AA•••••67", payout_card: "" };

  it("tells masked values from full ones and empty ones", () => {
    expect(isMasked("AA•••••67")).toBe(true);
    expect(isMasked("AA****567")).toBe(true);
    expect(isMasked("AA1234567")).toBe(false);
    expect(isMasked("")).toBe(false);
    expect(isMasked(null)).toBe(false);
  });

  it("shows the masked number with a reveal only for hr.sensitive, and nothing to reveal when none was recorded", () => {
    expect(idDisplay(profile, "passport", null, true)).toEqual({ text: "AA•••••67", revealed: false, canReveal: true });
    expect(idDisplay(profile, "passport", null, false)).toEqual({ text: "AA•••••67", revealed: false, canReveal: false });
    expect(idDisplay(profile, "payout_card", null, true)).toEqual({ text: "", revealed: false, canReveal: false });
  });

  it("shows the full number once the audited read came back", () => {
    const revealed = { pinfl: "31204567890045", passport: "AA1234567", payout_card: "" };
    expect(idDisplay(profile, "pinfl", revealed, true)).toEqual({ text: "31204567890045", revealed: true, canReveal: false });
    // A field the server sent no full value for stays masked.
    expect(idDisplay({ ...profile, payout_card: "8600•••••••••1234" }, "payout_card", revealed, true)).toEqual({ text: "8600•••••••••1234", revealed: false, canReveal: true });
  });

  it("groups long digit strings for reading but leaves masked ones alone", () => {
    expect(groupDigits("8600123456789012")).toBe("8600 1234 5678 9012");
    expect(groupDigits("31204567890045")).toBe("3120 4567 8900 45");
    expect(groupDigits("8600••••••••9012")).toBe("8600••••••••9012");
    expect(groupDigits("AA1234567")).toBe("AA1234567");
  });

  it("checks typed IDs: spaces ignored, passport upper-cased, empty means keep", () => {
    expect(cleanIds({ pinfl: "3120 4567 8900 45", passport: "aa1234567", tin: "", payout_card: "8600-1234-5678-9012" })).toEqual({
      values: { pinfl: "31204567890045", passport: "AA1234567", payout_card: "8600123456789012" },
      errors: [],
    });
    expect(cleanIds({ pinfl: "123", passport: "A1234567", tin: "12345678", payout_card: "8600" }).errors).toEqual(["pinfl", "passport", "tin", "payout_card"]);
  });

  it("knows which document kinds are IDs", () => {
    expect(needsSensitive("passport")).toBe(true);
    expect(needsSensitive("id_card")).toBe(true);
    expect(needsSensitive("military_id")).toBe(true);
    expect(needsSensitive("medical_book")).toBe(false);
    expect(kindGroup("passport")).toBe("identity");
    expect(kindGroup("pharmacist_certificate")).toBe("qualification");
    expect(kindGroup("nda")).toBe("other");
  });
});

describe("expiry", () => {
  it("is expired before today, expiring inside the window, valid beyond it", () => {
    expect(documentState("2026-11-01", "2026-11-02", 30)).toBe("expired");
    expect(documentState("2026-11-02", "2026-11-02", 30)).toBe("expiring");
    expect(documentState("2026-12-02", "2026-11-02", 30)).toBe("expiring");
    expect(documentState("2026-12-03", "2026-11-02", 30)).toBe("valid");
    expect(documentState(null, "2026-11-02", 30)).toBe("no_expiry");
  });

});

describe("overview", () => {
  it("works out the headcount 30 days ago from who joined and who left since", () => {
    const trend = [40, 41, 43, 44].map((headcount, index) => ({ month: `2026-0${index + 7}`, headcount, hired: 0, left: 0 }));
    expect(headcountKpi({ headcount: { current: 45, active: 44, suspended: 1, joined_30d: 3, left_30d: 1 }, trend })).toEqual({ value: 45, previous: 43, spark: [40, 41, 43, 44] });
  });

  it("puts the week's birthdays and anniversaries in one list, soonest first", () => {
    const member = (id: number, name: string) => ({ id, name, photo_url: null });
    const week = weekCelebrations({
      birthdays: [
        { member: member(1, "Madina"), date: "2026-11-05", days_until: 3 },
        { member: member(2, "Alisher"), date: "2026-11-02", days_until: 0 },
      ],
      anniversaries: [{ member: member(3, "Bekzod"), date: "2026-11-03", days_until: 1, years: 4 }],
    });
    expect(week.map((row) => `${row.kind}:${row.member.name}:${row.years ?? "-"}`)).toEqual(["birthday:Alisher:-", "anniversary:Bekzod:4", "birthday:Madina:-"]);
  });
});

describe("filters → query", () => {
  it("turns the Documents chips into the API's params (the server knows the warning window)", () => {
    expect(documentParams({ state: "expiring", kind: ["medical_book", "pharmacist_certificate"], verified: false }, "  Alisher ")).toEqual({
      state: "expiring",
      kind: ["medical_book", "pharmacist_certificate"],
      verified: false,
      q: "Alisher",
    });
    expect(documentParams({ state: "expired", verified: "true", member: "42" }, "")).toEqual({ state: "expired", verified: true, member: 42 });
    expect(documentParams({ state: "soon" }, "")).toEqual({});
    expect(documentParams({}, "")).toEqual({});
  });

  it("turns the Contracts tab and chips into the API's params with the company's windows", () => {
    const warn = { contracts: 21, probation: 7 };
    expect(contractParams("active", { ending: true, probation: "true" }, "", warn)).toEqual({ status: ["active"], ending_within: 21, probation_within: 7 });
    expect(contractParams("ended", { kind: "fixed_term" }, "No 12", warn)).toEqual({ status: ["ended", "terminated"], kind: ["fixed_term"], q: "No 12" });
    expect(contractParams("all", {}, "", warn)).toEqual({});
  });
});

describe("compliance matrix", () => {
  const data: Compliance = {
    kinds: ["medical_book", "pharmacist_certificate"],
    rows: [
      {
        member: { id: 1, name: "Alisher Valiyev" },
        position: { id: 7, name: "Farmatsevt" },
        items: [
          { kind: "medical_book", status: "expiring", document_id: 11, expires_on: "2026-11-20", level: "" },
          { kind: "pharmacist_certificate", status: "missing", document_id: null, expires_on: null, level: "" },
        ],
      },
      {
        member: { id: 2, name: "Bekzod Mirzayev" },
        position: { id: 7, name: "Farmatsevt" },
        items: [
          { kind: "medical_book", status: "ok", document_id: 12, expires_on: "2027-04-01", level: "" },
          { kind: "pharmacist_certificate", status: "ok", document_id: 13, expires_on: null, level: "" },
        ],
      },
      { member: { id: 3, name: "Kamola Yusupova" }, position: { id: 9, name: "Kuryer" }, items: [{ kind: "medical_book", status: "expired", document_id: 14, expires_on: "2026-10-01", level: "" }] },
      { member: { id: 4, name: "Zafar Islomov" }, position: null, items: [{ kind: "medical_book", status: "unverified", document_id: 15, expires_on: null, level: "" }] },
    ],
  };

  it("groups people by position, counts gaps per kind and per person, worst gap first", () => {
    const matrix = shapeCompliance(data, { collator: new Intl.Collator("en") });
    expect(matrix.people).toBe(4);
    expect(matrix.withGaps).toBe(3);
    expect(matrix.gapsByKind).toEqual({ medical_book: 3, pharmacist_certificate: 1 });
    expect(matrix.groups.map((g) => g.position)).toEqual(["Farmatsevt", "Kuryer", null]);
    const alisher = matrix.groups[0]!.rows[0]!;
    expect(alisher.member.name).toBe("Alisher Valiyev");
    expect(alisher.gaps.map((g) => `${g.kind}:${g.status}`)).toEqual(["pharmacist_certificate:missing", "medical_book:expiring"]);
    // A kind the courier's position doesn't require is null, not missing.
    expect(matrix.groups[1]!.rows[0]!.byKind).toEqual({ medical_book: "expired", pharmacist_certificate: null });
  });

  it("keeps only who lacks something when asked, and copes with no data", () => {
    const matrix = shapeCompliance(data, { onlyGaps: true });
    expect(matrix.groups.flatMap((g) => g.rows.map((r) => r.member.id))).toEqual([1, 3, 4]);
    expect(matrix.people).toBe(4);
    expect(shapeCompliance(undefined)).toEqual({ kinds: [], groups: [], people: 0, withGaps: 0, gapsByKind: {} });
  });
});

describe("contract actions by status", () => {
  const none: ContractActionFlags = { edit: false, delete: false, activate: false, terminate: false, end: false, renew: false, pass_probation: false, extend_probation: false, generate_pdf: false };
  const template = { id: 1, name: "Mehnat shartnomasi" };
  // What apps.hr.serializers.contract_actions sends for hr.manage, by status.
  const draft = { status: "draft" as const, template, actions: { ...none, edit: true, delete: true, activate: true, generate_pdf: true } };
  const active = { status: "active" as const, template, actions: { ...none, terminate: true, end: true, renew: true, generate_pdf: true } };
  const onTrial = { ...active, actions: { ...active.actions, pass_probation: true, extend_probation: true } };
  const ended = { status: "ended" as const, template, actions: { ...none, renew: true, generate_pdf: true } };
  const terminated = { status: "terminated" as const, template, actions: { ...none, generate_pdf: true } };

  it("offers what each status allows, the decision due first and the endings last", () => {
    expect(contractActions(draft)).toEqual(["activate", "generate-pdf"]);
    expect(contractActions(active)).toEqual(["renew", "generate-pdf", "end", "terminate"]);
    expect(contractActions(onTrial)).toEqual(["pass-probation", "extend-probation", "renew", "generate-pdf", "end", "terminate"]);
    expect(contractActions(ended)).toEqual(["renew"]);
    expect(contractActions(terminated)).toEqual([]);
  });

  it("makes a PDF only from a template, while the contract is a draft or in force", () => {
    expect(contractActions({ ...draft, template: null })).toEqual(["activate"]);
    expect(contractActions({ ...active, template: null })).toEqual(["renew", "end", "terminate"]);
  });

  it("offers nothing to someone who only reads (the server sends every flag off)", () => {
    expect(contractActions({ ...active, actions: none })).toEqual([]);
  });

  it("says when probation is running", () => {
    expect(onProbation({ status: "active", on_probation: true })).toBe(true);
    expect(onProbation({ status: "draft", on_probation: true })).toBe(false);
    expect(onProbation({ status: "active", on_probation: false })).toBe(false);
  });

  it("checks the dates: a fixed-term contract needs an end, probation stays inside", () => {
    expect(contractDatesProblem({ kind: "fixed_term", starts_on: "2026-11-01", ends_on: null, probation_until: null })).toBe("ends_on");
    expect(contractDatesProblem({ kind: "indefinite", starts_on: "2026-11-01", ends_on: null, probation_until: "2027-02-01" })).toBeNull();
    expect(contractDatesProblem({ kind: "fixed_term", starts_on: "2026-11-01", ends_on: "2026-10-01", probation_until: null })).toBe("ends_on");
    expect(contractDatesProblem({ kind: "fixed_term", starts_on: "2026-11-01", ends_on: "2027-01-31", probation_until: "2027-03-01" })).toBe("probation_until");
    expect(contractDatesProblem({ kind: "civil", starts_on: null, ends_on: null, probation_until: null })).toBe("starts_on");
  });
});

describe("template placeholders", () => {
  it("puts the token where the caret is, replacing a selection, with a space before a word", () => {
    expect(insertPlaceholder("Xodim: ", 7, 7, "employee_full_name")).toEqual({ text: "Xodim: {{employee_full_name}}", caret: 29 });
    expect(insertPlaceholder("Lavozim", 7, 7, "position")).toEqual({ text: "Lavozim {{position}}", caret: 20 });
    expect(insertPlaceholder("<p>NAME, salom</p>", 3, 7, "employee_full_name")).toEqual({ text: "<p>{{employee_full_name}}, salom</p>", caret: 25 });
    expect(insertPlaceholder("", 0, 0, "today")).toEqual({ text: "{{today}}", caret: 9 });
    // Out-of-range positions are clamped.
    expect(insertPlaceholder("abc", 10, 2, "branch").text).toBe("abc {{branch}}");
  });

  it("lists the placeholders a body uses and the ones the server won't fill", () => {
    const body = "<p>{{ employee_full_name }} ({{position}}) — {{position}}, {{salary}} {{company_tin}}</p>";
    expect(placeholdersIn(body)).toEqual(["employee_full_name", "position", "salary", "company_tin"]);
    expect(unknownPlaceholders(body)).toEqual(["salary"]);
  });
});
