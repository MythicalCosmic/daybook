/** Shared test data: a `me` with an owner company and a manager company. */
import type { Company, Me } from "@/api/types";
import type { Perm } from "@/core/perms";

export function company(overrides: Partial<Company> = {}): Company {
  return {
    id: 1,
    name: "Demo Dorixona",
    logo: null,
    timezone: "Asia/Tashkent",
    base_currency: "UZS",
    features: ["finance", "sales", "attendance", "hr", "payroll", "ai"],
    role: { id: 1, name: "Owner" },
    is_owner: true,
    permissions: [],
    branch_scope: null,
    branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
    home_branch: { id: 1, name: "Chilonzor" },
    pending: 0,
    setup_completed: true,
    membership_id: 11,
    ...overrides,
  };
}

export function manager(permissions: Perm[], overrides: Partial<Company> = {}): Company {
  return company({ id: 2, name: "Demo Distribyutor", role: { id: 2, name: "Manager" }, is_owner: false, permissions, membership_id: 21, ...overrides });
}

export function me(companies: Company[] = [company()]): Me {
  return {
    user: { id: 7, telegram_id: 1001, first_name: "Dilnoza", last_name: "Karimova", full_name: "Dilnoza Karimova", username: "dilnoza_k", photo_url: null },
    language: "en",
    companies,
  };
}

/** A JSON response for fetch stubs. */
export function json(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
