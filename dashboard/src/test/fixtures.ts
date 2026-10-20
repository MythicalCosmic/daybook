/** Shared test data: a `me` with an owner company and a manager company. */
import type { Company, Me } from "@/api/types";
import type { Perm } from "@/core/perms";

export function company(overrides: Partial<Company> = {}): Company {
  return {
    id: 1,
    name: "Demo Shop",
    logo: null,
    timezone: "Asia/Tashkent",
    base_currency: "UZS",
    language: "uz",
    features: ["finance", "sales", "attendance", "hr", "payroll", "ai"],
    membership_id: 11,
    role: { id: 1, name: "Owner", is_owner: true },
    permissions: [],
    branch_scope: null,
    branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
    pending: 0,
    alerts: 0,
    ...overrides,
  };
}

export function manager(permissions: Perm[], overrides: Partial<Company> = {}): Company {
  return company({ id: 2, name: "Bahor Café", role: { id: 2, name: "Manager", is_owner: false }, permissions, ...overrides });
}

export function me(companies: Company[] = [company()]): Me {
  return {
    user: { id: 7, telegram_id: 1001, first_name: "Dilnoza", last_name: "Karimova", full_name: "Dilnoza Karimova", username: "dilnoza_k", photo_url: null },
    language: "en",
    is_platform_admin: false,
    companies,
  };
}

/** A JSON response for fetch stubs. */
export function json(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
