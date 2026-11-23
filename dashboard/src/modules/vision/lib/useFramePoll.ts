/**
 * Polls one camera's latest picture (`cameras/<id>/frame/`, docs/KOZ.md §6.3) one request at a
 * time, every `interval` ms while it is wanted and the tab is visible: each call also keeps the
 * camera "watched" on the box, which is what turns its frames on. A 204 (no fresh frame yet, the box
 * is starting to send) keeps the last picture for a few seconds, then says it is waiting.
 */
import { useDocumentVisibility } from "@vueuse/core";
import { computed, getCurrentScope, onScopeDispose, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from "vue";

import { isApiError } from "@/api/http";
import { useCompanyId } from "@/stores/company";

import { getFrame } from "../api";
import type { Frame } from "../types";

export type FrameStatus = "idle" | "connecting" | "live" | "waiting" | "denied" | "error";

/** How long the last picture stays up when the box stops sending. */
const KEEP_MS = 4_000;

/**
 * `frame` and `receivedAt` (`Date.now()` when it arrived: the waits tick from it), the time
 * between the last two frames (`interval`, for the glide) and what the poll is doing.
 */
export function useFramePoll(cameraId: MaybeRefOrGetter<number | null>, options: { interval?: MaybeRefOrGetter<number>; enabled?: MaybeRefOrGetter<boolean> } = {}) {
  const companyId = useCompanyId();
  const visibility = useDocumentVisibility();
  const frame = shallowRef<Frame | null>(null);
  const receivedAt = ref(0);
  const gap = ref<number | null>(null);
  const status = ref<FrameStatus>("idle");
  const active = computed(() => !!toValue(cameraId) && (toValue(options.enabled) ?? true) && visibility.value !== "hidden" && companyId.value > 0);

  let run = 0;
  let controller: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lastFrameAt = 0;

  function stop(): void {
    run++;
    controller?.abort();
    controller = null;
    clearTimeout(timer);
  }

  async function loop(id: number, camera: number): Promise<void> {
    while (id === run) {
      const started = performance.now();
      controller = new AbortController();
      let wait = toValue(options.interval) ?? 500;
      try {
        const next = await getFrame(companyId.value, camera, controller.signal);
        if (id !== run) return;
        if (next) {
          const now = performance.now();
          if (lastFrameAt) gap.value = now - lastFrameAt;
          lastFrameAt = now;
          frame.value = next;
          // The browser's wall clock, as the one-second clock the waits tick on.
          receivedAt.value = Date.now();
          status.value = "live";
        } else if (!frame.value || performance.now() - lastFrameAt > KEEP_MS) {
          frame.value = null;
          status.value = "waiting";
        }
      } catch (error) {
        if (id !== run || (error instanceof DOMException && error.name === "AbortError")) return;
        if (isApiError(error) && error.status === 403) {
          status.value = "denied";
          return;
        }
        status.value = frame.value ? status.value : "error";
        wait = 3_000;
      }
      const spent = performance.now() - started;
      await new Promise<void>((resolve) => (timer = setTimeout(resolve, Math.max(0, wait - spent))));
    }
  }

  watch(
    [active, () => toValue(cameraId)],
    ([on, camera], [, before]) => {
      if (camera !== before) {
        frame.value = null;
        gap.value = null;
        lastFrameAt = 0;
        status.value = "idle";
      }
      stop();
      if (!on || !camera) return;
      if (!frame.value) status.value = "connecting";
      void loop(run, camera);
    },
    { immediate: true },
  );

  if (getCurrentScope()) onScopeDispose(stop);
  return { frame, receivedAt, interval: gap, status, active };
}
