/**
 * "Remember me" on the password sign-in (Davomat). The refresh cookie lives as long as the server
 * says; a person who unticks "Remember me" wants the session to end with the browser. This browser
 * keeps the choice, plus a session cookie (shared by every tab, gone when the browser closes): when
 * the console starts without that cookie and the person had not asked to be remembered, it signs
 * out first, so the next person at a shared computer starts at the sign-in page.
 */
import { request } from "@/api/http";
import { readStored, writeStored } from "@/lib/storage";

const KEY = "remember";
const MARK = "dvm_alive";

function markAlive(): void {
  try {
    document.cookie = `${MARK}=1; path=/; SameSite=Strict`;
  } catch {
    // Cookies blocked: the session simply stays (as with "Remember me").
  }
}

function isAlive(): boolean {
  try {
    return document.cookie.split(";").some((part) => part.trim() === `${MARK}=1`);
  } catch {
    return true;
  }
}

/** Saves the choice made at sign-in. */
export function rememberSession(remember: boolean): void {
  writeStored(KEY, remember ? null : false);
  markAlive();
}

/** Whether a restart of the browser signs the person out. */
export function forgetsOnClose(): boolean {
  return readStored<boolean>(KEY, true, (v): v is boolean => typeof v === "boolean") === false;
}

/** At startup: signs out when the browser was closed since a sign-in without "Remember me". */
export async function endForgottenSession(): Promise<boolean> {
  if (!forgetsOnClose() || isAlive()) {
    markAlive();
    return false;
  }
  writeStored(KEY, null);
  markAlive();
  try {
    await request<void>("/owner/auth/logout/", { method: "POST", json: {}, anonymous: true, toast: false });
  } catch {
    // Offline: the refresh that follows fails too, or the session ends on the server's schedule.
  }
  return true;
}
