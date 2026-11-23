/**
 * Asks for a clip and follows it (docs/KOZ.md §6.6): POST once, then GET every 2 s while the box
 * is still looking for the video or sending it, until it is ready or failed. A new request (or
 * closing the player) stops the old one; a poll that fails for a moment (offline) just tries again,
 * five failures in a row end it.
 */
import { computed, getCurrentScope, onScopeDispose, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from "vue";

import { useCompanyId } from "@/stores/company";

import { createClip, getClip } from "../api";
import type { Clip, ClipRequest } from "../types";
import { CLIP_POLL_MS, clipPhase, shouldPoll } from "./clip";

export function useClip(request: MaybeRefOrGetter<ClipRequest | null>) {
  const companyId = useCompanyId();
  const clip = shallowRef<Clip | null>(null);
  const error = ref<unknown>(null);
  const phase = computed(() => clipPhase(clip.value, error.value));

  let run = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function stop(): void {
    run++;
    clearTimeout(timer);
  }

  function schedule(id: number, failures: number): void {
    if (id !== run || !shouldPoll(phase.value)) return;
    timer = setTimeout(() => void poll(id, failures), CLIP_POLL_MS);
  }

  async function poll(id: number, failures: number): Promise<void> {
    const current = clip.value;
    if (!current) return;
    try {
      const next = await getClip(companyId.value, current.id);
      if (id !== run) return;
      clip.value = next;
      schedule(id, 0);
    } catch (failure) {
      if (id !== run) return;
      if (failures + 1 >= 5) error.value = failure;
      else schedule(id, failures + 1);
    }
  }

  async function start(body: ClipRequest): Promise<void> {
    stop();
    const id = run;
    clip.value = null;
    error.value = null;
    try {
      const created = await createClip(companyId.value, body);
      if (id !== run) return;
      clip.value = created;
      schedule(id, 0);
    } catch (failure) {
      if (id === run) error.value = failure;
    }
  }

  watch(
    () => JSON.stringify(toValue(request)),
    () => {
      const body = toValue(request);
      if (body) void start(body);
      else {
        stop();
        clip.value = null;
        error.value = null;
      }
    },
    { immediate: true },
  );

  if (getCurrentScope()) onScopeDispose(stop);
  return {
    clip,
    error,
    phase,
    retry: () => {
      const body = toValue(request);
      if (body) void start(body);
    },
  };
}
