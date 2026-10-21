/**
 * The demo people `seed_demo` creates (backend/apps/core/management/commands/seed_demo.py), by
 * company, for the development sign-in. Only demo ids: a real person's Telegram id never goes in
 * the repository (anyone can still type any id into the field). People without dashboard access
 * get the server's refusal, which is how to see that screen.
 */
export interface DemoPerson {
  id: number;
  name: string;
  /** An `auth.dev.*` key: the person's position or role in the demo. */
  role: string;
}

export const DEMO_COMPANIES: ReadonlyArray<{ name: string; people: readonly DemoPerson[] }> = [
  {
    name: "Demo Dorixona",
    people: [
      { id: 1001, name: "Dilnoza Karimova", role: "auth.dev.owner" },
      { id: 1002, name: "Bekzod Mirzayev", role: "auth.dev.headOfPharmacy" },
      { id: 4242, name: "Alisher Valiyev", role: "auth.dev.pharmacist" },
      { id: 1004, name: "Madina Saidova", role: "auth.dev.seniorPharmacist" },
      { id: 1005, name: "Jasur Tursunov", role: "auth.dev.courier" },
      { id: 1006, name: "Nigora Azimova", role: "auth.dev.nightPharmacist" },
    ],
  },
  {
    name: "Demo Distribyutor",
    people: [
      { id: 2001, name: "Sardor Qodirov", role: "auth.dev.warehouseManager" },
      { id: 2002, name: "Kamola Yusupova", role: "auth.dev.storekeeper" },
      { id: 2003, name: "Otabek Rahimov", role: "auth.dev.salesManager" },
    ],
  },
];

/** Sign-up states: someone joining without details, someone waiting for approval, a stranger. */
export const DEMO_STRANGERS: ReadonlyArray<Omit<DemoPerson, "name">> = [
  { id: 5001, role: "auth.dev.applicant" },
  { id: 5002, role: "auth.dev.waiting" },
  { id: 5003, role: "auth.dev.outsider" },
];
