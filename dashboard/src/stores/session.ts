/**
 * The signed-in person. The access token lives only in memory (plan §7.3); the refresh token is an
 * httpOnly cookie the browser sends to /api/v1/owner/auth/ by itself.
 */
import { defineStore } from "pinia";
import { computed, ref, shallowRef } from "vue";

import { refreshAccess } from "@/api/http";
import { shellApi } from "@/api/shell";
import type { Language, Me } from "@/api/types";

export type SessionStatus = "idle" | "booting" | "ready";

export const useSessionStore = defineStore("session", () => {
  const accessToken = shallowRef<string | null>(null);
  const me = shallowRef<Me | null>(null);
  const status = ref<SessionStatus>("idle");
  let booting: Promise<void> | null = null;

  const signedIn = computed(() => me.value !== null && accessToken.value !== null);
  const companies = computed(() => me.value?.companies ?? []);

  function setAccess(token: string | null): void {
    accessToken.value = token;
  }

  async function loadMe(): Promise<Me> {
    const next = await shellApi.me();
    me.value = next;
    return next;
  }

  /**
   * Runs once per page load. `refreshAccess` uses the refresh cookie on the desktop and posts
   * Telegram's initData inside Telegram (http's `relogin`). A failure leaves the person signed out.
   */
  function boot(): Promise<void> {
    booting ??= (async () => {
      status.value = "booting";
      try {
        const token = await refreshAccess();
        if (token) await loadMe();
      } catch {
        accessToken.value = null;
        me.value = null;
      } finally {
        status.value = "ready";
      }
    })();
    return booting;
  }

  async function devLogin(telegramId: number): Promise<void> {
    const { access } = await shellApi.devLogin(telegramId);
    setAccess(access);
    await loadMe();
  }

  /** The server rejected the refresh: forget everything (the router sends the person to /login). */
  function endSession(): void {
    accessToken.value = null;
    me.value = null;
  }

  async function logout(): Promise<void> {
    try {
      await shellApi.logout();
    } finally {
      endSession();
    }
  }

  function setLanguage(language: Language): void {
    if (me.value) me.value = { ...me.value, language };
  }

  return { accessToken, me, status, signedIn, companies, setAccess, loadMe, boot, devLogin, endSession, logout, setLanguage };
});
