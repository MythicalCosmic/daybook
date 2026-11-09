/**
 * The edition this server runs (docs/DAVOMAT.md §0, §1.1): one build of the console serves Daybook
 * (the default: tasks, money, people…) and Davomat (Face ID, attendance and the team only, with
 * username and password sign-in and the organization's own branding).
 *
 * main.ts asks `GET /owner/edition/` before anything else, then `applyEdition` keeps only that
 * edition's modules in the registry, so the router, the sidebar, the palette and the settings are
 * built from them and nothing of the other edition loads. Modules declare `editions` (default
 * `["daybook"]`); nav items, settings panels, widgets and person tabs may narrow theirs.
 *
 * The answer is remembered in this browser: if the server can't be reached at the next start, the
 * console opens in the edition it knew (a Davomat install never falls back to Daybook's shell
 * because one request failed).
 */
import { shallowRef } from "vue";

import { request } from "@/api/http";
import { LANGUAGES, type Language } from "@/api/types";
import { readStored, writeStored } from "@/lib/storage";

export const EDITIONS = ["daybook", "davomat"] as const;
export type Edition = (typeof EDITIONS)[number];

/** The edition a module is in when it doesn't say. */
export const DEFAULT_EDITIONS: readonly Edition[] = ["daybook"];

/** `GET /owner/edition/` (public). */
export interface EditionInfo {
  edition: Edition;
  /** "Davomat" or "Daybook": the product name in the title, the sign-in page and the sidebar. */
  product: string;
  /** The organization of a Davomat install (null before the setup wizard, and in Daybook). */
  organization: { name: string; logo_url: string | null } | null;
  /** No organization yet: every page opens the first-run setup wizard. */
  needs_setup: boolean;
  default_language: Language;
  languages: Language[];
  telegram: { configured: boolean; bot_username: string | null };
}

export const DAYBOOK_INFO: EditionInfo = {
  edition: "daybook",
  product: "Daybook",
  organization: null,
  needs_setup: false,
  default_language: "uz",
  languages: [...LANGUAGES],
  telegram: { configured: false, bot_username: null },
};

/** What the server said (Daybook until it answers). Reactive: the shell's title and brand follow it. */
export const editionInfo = shallowRef<EditionInfo>(DAYBOOK_INFO);

export function currentEdition(): Edition {
  return editionInfo.value.edition;
}

export function isDavomat(): boolean {
  return editionInfo.value.edition === "davomat";
}

function isEdition(value: unknown): value is Edition {
  return typeof value === "string" && (EDITIONS as readonly string[]).includes(value);
}

/** The server's answer, with anything unexpected replaced by a safe value. */
export function normalizeEdition(raw: unknown): EditionInfo {
  if (!raw || typeof raw !== "object") return DAYBOOK_INFO;
  const body = raw as Partial<EditionInfo> & Record<string, unknown>;
  const edition = isEdition(body.edition) ? body.edition : "daybook";
  const languages = Array.isArray(body.languages) ? body.languages.filter((l): l is Language => (LANGUAGES as readonly string[]).includes(l as string)) : [];
  const organization = body.organization && typeof body.organization === "object" && typeof body.organization.name === "string"
    ? { name: body.organization.name, logo_url: typeof body.organization.logo_url === "string" && body.organization.logo_url ? body.organization.logo_url : null }
    : null;
  const telegram = body.telegram && typeof body.telegram === "object" ? body.telegram : null;
  return {
    edition,
    product: typeof body.product === "string" && body.product.trim() ? body.product : edition === "davomat" ? "Davomat" : "Daybook",
    organization,
    needs_setup: edition === "davomat" && body.needs_setup === true,
    default_language: (LANGUAGES as readonly string[]).includes(body.default_language as string) ? (body.default_language as Language) : "uz",
    languages: languages.length ? languages : [...LANGUAGES],
    telegram: { configured: telegram?.configured === true, bot_username: typeof telegram?.bot_username === "string" ? telegram.bot_username : null },
  };
}

/** Replaces what the console knows (after the setup wizard, a rename, a new logo or a bot token). */
export function setEditionInfo(info: EditionInfo): void {
  editionInfo.value = info;
  writeStored("edition", info.edition);
}

/** The edition this browser saw last on this server (null on a first visit). */
export function rememberedEdition(): Edition | null {
  return readStored<Edition | null>("edition", null, (v): v is Edition | null => v === null || isEdition(v));
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Asks the server once at startup (two quick retries on a network or server error). An old
 * backend without the endpoint (404) is Daybook. When the server can't be reached at all, the
 * edition remembered in this browser is used, so a Davomat console stays Davomat.
 */
export async function loadEdition(options: { retries?: number; delayMs?: number } = {}): Promise<EditionInfo> {
  const retries = options.retries ?? 2;
  const delayMs = options.delayMs ?? 400;
  for (let attempt = 0; ; attempt++) {
    try {
      const body = await request<unknown>("/owner/edition/", { anonymous: true, toast: false });
      const info = normalizeEdition(body);
      setEditionInfo(info);
      return info;
    } catch (error) {
      const status = (error as { status?: number }).status ?? 0;
      // The endpoint doesn't exist (Daybook before Davomat) or refuses: Daybook, for good.
      if (status >= 400 && status < 500) {
        setEditionInfo(DAYBOOK_INFO);
        return DAYBOOK_INFO;
      }
      if (attempt >= retries) break;
      await wait(delayMs * (attempt + 1));
    }
  }
  const remembered = rememberedEdition();
  const info = remembered === "davomat" ? { ...DAYBOOK_INFO, edition: "davomat" as const, product: "Davomat" } : DAYBOOK_INFO;
  editionInfo.value = info;
  return info;
}

/** Asks again (after the setup wizard or a settings change), keeping what it knew on a failure. */
export async function refreshEdition(): Promise<EditionInfo> {
  try {
    const info = normalizeEdition(await request<unknown>("/owner/edition/", { anonymous: true, toast: false }));
    setEditionInfo(info);
    return info;
  } catch {
    return editionInfo.value;
  }
}

/** Something that may belong to some editions only (a module, a nav item, a settings panel…). */
export interface EditionScoped {
  editions?: readonly Edition[];
}

/** A module's editions: its own, else Daybook only. */
export function moduleEditions(module: EditionScoped): readonly Edition[] {
  return module.editions ?? DEFAULT_EDITIONS;
}

/**
 * Whether an item shows in `edition`. Items without `editions` follow their module (always true
 * here); modules default to Daybook through `moduleEditions`.
 */
export function inEdition(item: EditionScoped | undefined, edition: Edition = currentEdition()): boolean {
  return !item?.editions || item.editions.includes(edition);
}

/** The browser-tab and theme-color values of the edition shown now. */
export function editionThemeColor(theme: "light" | "dark"): string {
  if (isDavomat()) return theme === "dark" ? "#0b0e14" : "#f4f6fa";
  return theme === "dark" ? "#141210" : "#f7f3ec";
}
