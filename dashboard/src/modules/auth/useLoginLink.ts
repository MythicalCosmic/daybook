/**
 * The desktop sign-in as a small state machine (plan §7.1):
 *
 *   starting ─▶ waiting ──(Telegram: right number)──▶ approved ─▶ signing-in ─▶ done
 *                  │  └─(wrong number / "It wasn't me")─▶ denied
 *                  └─(3 minutes pass)─▶ expired
 *   starting ─▶ unavailable (no bot configured) | throttled | offline
 *   signing-in ─▶ no-access (lost access in between)
 *
 * It creates a link, polls `{status}` every 1.5 s, counts down the link's 3 minutes and, once
 * approved, claims the session once and hands the access token to `onSignedIn`. Nothing here
 * touches the router or the session store, so it is easy to test with fake timers.
 */
import { computed, onScopeDispose, ref, shallowRef } from "vue";

import { isApiError } from "@/api/http";

import { claimLoginLink, createLoginLink, pollLoginLink, type LoginLink } from "./api";

export type LoginPhase =
  | "starting"
  | "waiting"
  | "approved"
  | "signing-in"
  | "done"
  | "denied"
  | "expired"
  | "no-access"
  | "unavailable"
  | "throttled"
  | "offline";

export const POLL_MS = 1500;
/** A link lives 3 minutes on the server; the browser counts from when it got it. */
export const LIFETIME_MS = 180_000;

export interface LoginLinkOptions {
  onSignedIn: (access: string) => void | Promise<void>;
  now?: () => number;
}

export function useLoginLink(options: LoginLinkOptions) {
  const now = options.now ?? (() => Date.now());
  const phase = ref<LoginPhase>("starting");
  const link = shallowRef<LoginLink | null>(null);
  const deadline = ref(0);
  const clock = ref(now());
  /** The last poll failed on the network: the page says it is reconnecting, polling goes on. */
  const reconnecting = ref(false);

  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let tickTimer: ReturnType<typeof setInterval> | null = null;
  let generation = 0;

  const remainingMs = computed(() => Math.max(0, deadline.value - clock.value));
  const remaining = computed(() => Math.ceil(remainingMs.value / 1000));
  /** 1 → 0 over the link's life (the countdown ring). */
  const progress = computed(() => (phase.value === "waiting" ? remainingMs.value / LIFETIME_MS : 0));

  function stopTimers(): void {
    if (pollTimer) clearTimeout(pollTimer);
    if (tickTimer) clearInterval(tickTimer);
    pollTimer = null;
    tickTimer = null;
  }

  function finish(next: LoginPhase): void {
    stopTimers();
    phase.value = next;
  }

  function schedulePoll(delay = POLL_MS): void {
    const mine = generation;
    pollTimer = setTimeout(() => void poll(mine), delay);
  }

  async function poll(mine: number): Promise<void> {
    const current = link.value;
    if (mine !== generation || !current || phase.value !== "waiting") return;
    try {
      const { status } = await pollLoginLink(current);
      if (mine !== generation) return;
      reconnecting.value = false;
      if (status === "approved") return void claim(mine);
      if (status === "denied") return finish("denied");
      if (status === "expired" || status === "consumed") return finish("expired");
      schedulePoll();
    } catch (error) {
      if (mine !== generation) return;
      if (isApiError(error) && error.status === 404) return finish("expired");
      if (isApiError(error) && error.status === 429) return schedulePoll(POLL_MS * 2);
      reconnecting.value = isApiError(error) ? error.isNetwork : false;
      schedulePoll(POLL_MS * 2);
    }
  }

  async function claim(mine: number): Promise<void> {
    const current = link.value;
    if (!current) return;
    stopTimers();
    phase.value = "approved";
    try {
      const { access } = await claimLoginLink(current);
      if (mine !== generation) return;
      phase.value = "signing-in";
      await options.onSignedIn(access);
      if (mine === generation) phase.value = "done";
    } catch (error) {
      if (mine !== generation) return;
      const code = isApiError(error) ? error.code : null;
      if (isApiError(error) && error.status === 403) return finish("no-access");
      if (code === "denied") return finish("denied");
      finish("expired");
    }
  }

  async function start(): Promise<void> {
    generation += 1;
    const mine = generation;
    stopTimers();
    phase.value = "starting";
    reconnecting.value = false;
    link.value = null;
    try {
      const created = await createLoginLink();
      if (mine !== generation) return;
      link.value = created;
      deadline.value = now() + LIFETIME_MS;
      clock.value = now();
      phase.value = "waiting";
      tickTimer = setInterval(() => {
        clock.value = now();
        if (phase.value === "waiting" && clock.value >= deadline.value) finish("expired");
      }, 250);
      schedulePoll();
    } catch (error) {
      if (mine !== generation) return;
      if (isApiError(error) && error.status === 503) return finish("unavailable");
      if (isApiError(error) && error.status === 429) return finish("throttled");
      finish("offline");
    }
  }

  function stop(): void {
    generation += 1;
    stopTimers();
  }

  onScopeDispose(stop);

  return { phase, link, remaining, progress, reconnecting, start, stop };
}
