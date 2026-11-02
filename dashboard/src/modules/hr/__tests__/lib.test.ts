import { describe, expect, it } from "vitest";

import {
  cleanIds,
  contractActions,
  contractDatesProblem,
  contractParams,
  documentParams,
  documentState,
  fileKind,
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
} from "../lib";
import type { Compliance, Contract } from "../types";

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

  it("tells images, PDFs and other files apart by name or link", () => {
    expect(fileKind("medkitob.JPG")).toBe("image");
    expect(fileKind("/api/v1/files/abc/scan.pdf?sig=1")).toBe("pdf");
    expect(fileKind("archive.zip")).toBe("other");
    expect(fileKind(null)).toBe("other");
  });
});

describe("filters → query", () => {
  it("turns the Documents chips into the API's params", () => {
    expect(documentParams({ state: "expiring", kind: ["medical_book", "pharmacist_certificate"], verified: false }, "  Alisher ", 30)).toEqual({
      expiring_within: 30,
      kind: ["medical_book", "pharmacist_certificate"],
      verified: false,
      q: "Alisher",
    });
    expect(documentParams({ state: "expired", verified: "true", member: "42" }, "", 14)).toEqual({ expired: true, verified: true, member: 42 });
    expect(documentParams({}, "", 30)).toEqual({});
  });

  it("turns the Contracts tab and chips into the API's params", () => {
    expect(contractParams("active", { ending: true, probation: "true" }, "", 21)).toEqual({ status: ["active"], ending_within: 21, probation: true });
    expect(contractParams("ended", { kind: "fixed_term" }, "No 12", 30)).toEqual({ status: ["ended", "terminated"], kind: ["fixed_term"], q: "No 12" });
    expect(contractParams("all", {}, "", 30)).toEqual({});
  });
});

describe("compliance matrix", () => {
  const data: Compliance = {
    kinds: ["medical_book", "pharmacist_certificate"],
    rows: [
      {
        member: { id: 1, name: "Alisher Valiyev" },
        position: { id: 7, name: "Farmatsevt" },
        cells: [
          { kind: "medical_book", status: "expiring", document_id: 11, expires_on: "2026-11-20" },
          { kind: "pharmacist_certificate", status: "missing" },
        ],
      },
      {
        member: { id: 2, name: "Bekzod Mirzayev" },
        position: { id: 7, name: "Farmatsevt" },
        cells: [
          { kind: "medical_book", status: "ok", document_id: 12 },
          { kind: "pharmacist_certificate", status: "ok", document_id: 13 },
        ],
      },
      { member: { id: 3, name: "Kamola Yusupova" }, position: { id: 9, name: "Kuryer" }, cells: [{ kind: "medical_book", status: "expired", document_id: 14 }] },
      { member: { id: 4, name: "Zafar Islomov" }, position: null, cells: [{ kind: "medical_book", status: "unverified", document_id: 15 }] },
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
  const base: Pick<Contract, "status" | "kind" | "probation_until" | "probation_passed_at" | "template"> = {
    status: "active",
    kind: "fixed_term",
    probation_until: null,
    probation_passed_at: null,
    template: { id: 1, name: "Mehnat shartnomasi" },
  };

  it("offers what each status allows", () => {
    expect(contractActions({ ...base, status: "draft" }, true)).toEqual(["activate", "generate-pdf"]);
    expect(contractActions(base, true)).toEqual(["renew", "terminate", "generate-pdf"]);
    expect(contractActions({ ...base, kind: "indefinite" }, true)).toEqual(["terminate", "generate-pdf"]);
    expect(contractActions({ ...base, probation_until: "2026-11-07" }, true)).toEqual(["pass-probation", "extend-probation", "renew", "terminate", "generate-pdf"]);
    expect(contractActions({ ...base, probation_until: "2026-11-07", probation_passed_at: "2026-11-01T09:00:00Z" }, true)).toEqual(["renew", "terminate", "generate-pdf"]);
    expect(contractActions({ ...base, status: "ended" }, true)).toEqual(["renew"]);
    expect(contractActions({ ...base, status: "terminated" }, true)).toEqual([]);
    expect(contractActions({ ...base, status: "draft", template: null }, true)).toEqual(["activate"]);
  });

  it("offers nothing to someone who only reads", () => {
    expect(contractActions({ ...base, status: "draft" }, false)).toEqual([]);
    expect(contractActions(base, false)).toEqual([]);
  });

  it("says when probation is running", () => {
    expect(onProbation({ status: "active", probation_until: "2026-11-07", probation_passed_at: null })).toBe(true);
    expect(onProbation({ status: "draft", probation_until: "2026-11-07", probation_passed_at: null })).toBe(false);
    expect(onProbation({ status: "active", probation_until: null, probation_passed_at: null })).toBe(false);
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
