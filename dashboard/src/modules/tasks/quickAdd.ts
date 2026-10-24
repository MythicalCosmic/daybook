/**
 * Quick add (cross-area contract 1): a title is read while it's typed, so "Ertaga 15:00 dorilarni
 * sanash !!" gives the deadline, the urgency and the title without those words. The server reads
 * it in the company's timezone (a laptop's clock or zone is often wrong) and saves nothing; the
 * dialog shows what it understood and creates the task only when asked. A backend without the
 * endpoint (404) quietly switches it off for the session.
 */
import { computed, onScopeDispose, ref, watch, type Ref } from "vue";

import { isApiError } from "@/api/http";

import { tasksApi } from "./api";
import type { QuickAddParse } from "./types";

export const QUICK_ADD_DEBOUNCE_MS = 300;

/** Companies whose backend has no parse endpoint: not asked again until the page reloads. */
const unavailable = new Set<number>();

/** Forget which backends lacked the endpoint (tests; a deploy would reload the page anyway). */
export function forgetQuickAddAvailability(): void {
  unavailable.clear();
}

/** Whether the parser found anything worth showing: a deadline, an urgency or a repeat. */
export function recognised(result: QuickAddParse | null | undefined): result is QuickAddParse {
  return !!result && (!!result.due_at || !!result.priority || !!result.repeat);
}

/** A result's identity: the same words understood the same way. */
export function resultKey(result: QuickAddParse | null): string | null {
  return result ? `${result.due_at ?? ""}|${result.priority ?? ""}|${result.repeat ?? ""}` : null;
}

export function useQuickAdd(text: Ref<string>, companyId: Ref<number>) {
  const result = ref<QuickAddParse | null>(null);
  const pending = ref(false);
  const available = ref(!unavailable.has(companyId.value));
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | null = null;
  let inflight: Promise<void> = Promise.resolve();

  async function read(value: string): Promise<void> {
    timer = undefined;
    controller?.abort();
    const cid = companyId.value;
    if (!cid || unavailable.has(cid) || value.trim().length < 2) {
      result.value = null;
      pending.value = false;
      return;
    }
    const own = new AbortController();
    controller = own;
    pending.value = true;
    try {
      const answer = await tasksApi.parse(cid, value.trim(), own.signal);
      if (own.signal.aborted) return;
      result.value = recognised(answer) ? answer : null;
    } catch (error) {
      if (own.signal.aborted) return;
      if (isApiError(error) && (error.status === 404 || error.status === 405)) {
        unavailable.add(cid);
        available.value = false;
      }
      result.value = null;
    } finally {
      if (controller === own) {
        controller = null;
        pending.value = false;
      }
    }
  }

  watch(text, (value) => {
    clearTimeout(timer);
    if (!value.trim() || !available.value) {
      timer = undefined;
      controller?.abort();
      controller = null;
      result.value = null;
      pending.value = false;
      return;
    }
    pending.value = true;
    timer = setTimeout(() => (inflight = read(value)), QUICK_ADD_DEBOUNCE_MS);
  });

  /** Before saving: read what is typed now if the pause hasn't passed yet, and wait for it. */
  async function settle(): Promise<void> {
    if (timer !== undefined) {
      clearTimeout(timer);
      inflight = read(text.value);
    }
    await inflight;
  }

  function reset(): void {
    clearTimeout(timer);
    timer = undefined;
    controller?.abort();
    controller = null;
    result.value = null;
    pending.value = false;
  }

  onScopeDispose(reset);
  return { result, pending, available: computed(() => available.value), settle, reset };
}
