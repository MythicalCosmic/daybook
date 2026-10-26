<script setup lang="ts">
/**
 * A team link's live screen ("Show QR"): made to be shown to a room on a big screen or held up on
 * a phone. The company, the link's name, a QR code as large as fits, one line on how to scan (in
 * the company's language, then Russian or Uzbek, as on the poster) and live progress: how many
 * joined, the places left or the end, and the newest people as they arrive. It asks every 3 s while
 * open and visible (useLiveJoinLink); a full, ended or stopped link dims its code and says so.
 * Esc or the close button closes it; the screen is kept awake where the browser allows.
 */
import { X } from "@lucide/vue";
import { useWindowSize } from "@vueuse/core";
import { DialogContent, DialogDescription, DialogPortal, DialogRoot, DialogTitle } from "reka-ui";
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import CompanyLogo from "@/components/CompanyLogo.vue";
import IconButton from "@/components/IconButton.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";
import { useTween } from "@/lib/useTween";
import { useCompanyStore } from "@/stores/company";

import { useLiveJoinLink, useSettings } from "../api";
import { useRoomLanguages } from "../roomLanguages";
import { STATUS_TONE, endText, livePeople, placesLeft } from "../teamLinks";
import type { JoinLink, JoinLinkPerson } from "../types";

const QrCode = defineAsyncComponent(() => import("@/components/QrCode.vue"));

const props = defineProps<{ link: JoinLink }>();
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const settings = useSettings();
const { width, height } = useWindowSize();

const query = useLiveJoinLink(
  () => props.link.id,
  () => props.link,
);
const data = computed(() => query.data.value ?? { ...props.link, people: [] as JoinLinkPerson[] });
const phone = computed(() => width.value < 768);

/** As large as fits: most of the width on a phone, the height of the left column on a screen. */
const qrSize = computed(() => {
  const size = phone.value ? Math.min(width.value - 88, height.value * 0.44) : Math.min(height.value - 300, width.value * 0.46 - 96);
  return Math.round(Math.max(176, Math.min(size, 640)));
});

const status = computed(() => data.value.status);
const open = computed(() => status.value === "active");
const left = computed(() => placesLeft(data.value));
const count = useTween(() => data.value.uses);
const shownCount = computed(() => fmt.number(Math.round(count.value.value ?? data.value.uses)));
const people = computed(() => livePeople(data.value.people, phone.value ? 3 : 6));

const { languages: room, say } = useRoomLanguages(() => settings.data.value?.default_language ?? "uz");

/** Places left only while people can still come in; a closed link says why over its code instead. */
const placesLine = computed(() => (!open.value || left.value === null ? null : t("settings.teamLinks.live.left", { n: left.value }, left.value)));
const endLine = computed(() => endText(data.value, t, company.timezone, fmt.lang.value));
/** Why nobody new gets in, when the link can't take anyone. */
const closedTitle = computed(() => (open.value ? null : t(`settings.teamLinks.live.closed.${status.value}`)));
const closedHint = computed(() => (open.value ? null : t(`settings.teamLinks.live.closedHint.${status.value}`)));

function personLine(person: JoinLinkPerson): string {
  if (!person.onboarded) return t("settings.teamLinks.live.filling");
  if (person.status === "pending") return t("settings.teamLinks.live.pending");
  return person.position?.name ?? t("settings.teamLinks.live.joinedNow");
}

/**
 * People who arrive while the screen is open glow for a moment; those already there when it opened
 * don't. The seed (the list row, before the first answer) has no people, so it doesn't count.
 */
const seen = new Set<number>();
const fresh = ref(new Set<number>());
let primed = false;
watch(
  () => [data.value.people, query.isPlaceholderData.value] as const,
  ([list, seed]) => {
    if (seed) return;
    for (const person of list) {
      if (seen.has(person.id)) continue;
      seen.add(person.id);
      if (!primed) continue;
      fresh.value = new Set([...fresh.value, person.id]);
      setTimeout(() => {
        const next = new Set(fresh.value);
        next.delete(person.id);
        fresh.value = next;
      }, 4_000);
    }
    primed = true;
  },
  { immediate: true },
);

// Keep the screen awake while it's shown (best effort: not every browser has a wake lock, and the
// lock lapses whenever the tab is hidden, so it is asked for again when the tab comes back).
let lock: WakeLockSentinel | null = null;
async function stayAwake(): Promise<void> {
  if (typeof navigator === "undefined" || !("wakeLock" in navigator) || document.visibilityState !== "visible") return;
  try {
    lock = await navigator.wakeLock.request("screen");
  } catch {
    lock = null;
  }
}
function onVisibility(): void {
  if (document.visibilityState === "visible" && (!lock || lock.released)) void stayAwake();
}
onMounted(() => {
  void stayAwake();
  document.addEventListener("visibilitychange", onVisibility);
});
onBeforeUnmount(() => {
  document.removeEventListener("visibilitychange", onVisibility);
  void lock?.release().catch(() => undefined);
  lock = null;
});

function onOpenChange(value: boolean): void {
  if (!value) emit("close");
}

/** Focus the screen itself, not the close button: no focus ring on a screen shown to a room. */
function focusSelf(event: Event): void {
  event.preventDefault();
  (event.target as HTMLElement | null)?.focus({ preventScroll: true });
}
</script>

<template>
  <DialogRoot :open="true" @update:open="onOpenChange">
    <DialogPortal>
      <DialogContent
        class="team-live anim-fade fixed inset-0 z-[66] flex flex-col overflow-y-auto bg-canvas text-fg outline-none"
        tabindex="-1"
        data-team-live
        @open-auto-focus="focusSelf"
      >
        <!-- Top: whose link this is, its state and the way out -->
        <header :class="['flex shrink-0 items-center gap-3', phone ? 'px-4 pb-2 pt-[calc(14px+var(--safe-top,0px))]' : 'px-10 pb-2 pt-7']">
          <CompanyLogo :name="company.current?.name ?? ''" :src="company.current?.logo ?? null" :size="phone ? 36 : 48" />
          <div class="min-w-0 flex-1">
            <p :class="['truncate font-medium text-muted', phone ? 'text-sm' : 'text-base']">{{ company.current?.name }}</p>
            <DialogTitle :class="['truncate font-semibold tracking-[-0.01em] text-fg', phone ? 'text-md leading-6' : 'text-xl']">{{ data.name }}</DialogTitle>
          </div>
          <StatusPill v-if="!phone" :tone="STATUS_TONE[status]" :label="t(`settings.teamLinks.status.${status}`)" :live="open" />
          <IconButton v-if="phone" :icon="X" :label="t('common.close')" variant="secondary" size="lg" data-live-close @click="emit('close')" />
          <UiButton v-else :icon="X" kbd="Esc" data-live-close @click="emit('close')">{{ t("common.close") }}</UiButton>
        </header>

        <main
          :class="[
            'flex-1',
            phone ? 'flex flex-col items-center gap-6 px-4 pb-[calc(24px+var(--safe-bottom,0px))] pt-3' : 'grid grid-cols-[minmax(0,1.2fr)_minmax(340px,0.8fr)] items-center gap-14 px-14 pb-12',
          ]"
        >
          <!-- The code, as large as fits, and how to use it -->
          <section class="flex flex-col items-center text-center">
            <div class="relative">
              <div :class="['transition-[opacity,filter] duration-300', !open && 'opacity-[0.18] grayscale']" :aria-hidden="!open || undefined">
                <QrCode :value="data.link" :size="qrSize" level="M" />
              </div>
              <div v-if="closedTitle" class="absolute inset-0 grid place-items-center p-4" role="status" data-live-closed>
                <div class="max-w-[320px] rounded-[16px] bg-surface px-5 py-4 shadow-palette">
                  <p class="text-lg font-semibold text-fg">{{ closedTitle }}</p>
                  <p class="mt-1 text-sm text-muted">{{ closedHint }}</p>
                </div>
              </div>
            </div>
            <DialogDescription as="div" :class="['flex flex-col transition-opacity duration-300', phone ? 'mt-4 gap-0.5' : 'mt-7 gap-1', !open && 'opacity-35']">
              <p v-for="(lang, index) in room" :key="lang" :lang="lang" :class="index === 0 ? (phone ? 'font-display text-[22px] leading-tight' : 'font-display text-[34px] leading-tight') : phone ? 'text-sm text-muted' : 'text-lg text-muted'">
                {{ say("settings.teamLinks.live.scan", lang) }}
              </p>
            </DialogDescription>
          </section>

          <!-- Live progress -->
          <aside :class="['flex w-full flex-col', phone ? 'max-w-[440px] gap-5' : 'gap-9']">
            <div :class="phone ? 'flex items-end justify-between gap-4 rounded-[16px] bg-surface p-4 shadow-[var(--sh-raised)]' : ''" aria-live="polite" data-live-count>
              <div class="min-w-0">
                <p :class="['font-semibold uppercase tracking-[0.08em] text-muted', phone ? 'text-xs' : 'text-sm']">{{ t(data.auto_approve ? "settings.teamLinks.live.joined" : "settings.teamLinks.live.asked") }}</p>
                <p :class="['font-display leading-none tabular-nums text-fg', phone ? 'mt-1 text-[56px]' : 'mt-2 text-[112px]']">{{ shownCount }}</p>
              </div>
              <div :class="['flex min-w-0 flex-col', phone ? 'items-end gap-1 pb-1 text-right' : 'mt-5 gap-2.5']">
                <ProgressBar v-if="data.max_uses !== null && !phone && (open || status === 'full')" :value="data.uses" :max="data.max_uses" size="md" :tone="status === 'full' ? 'warning' : 'success'" class="max-w-[420px]" />
                <p :class="['font-medium text-fg', phone ? 'text-sm' : 'text-lg']">
                  <span v-if="placesLine">{{ placesLine }}</span>
                  <span v-if="placesLine && !phone" class="px-2 text-subtle" aria-hidden="true">·</span>
                  <span :class="phone && placesLine ? 'block text-muted' : 'text-muted'">{{ endLine }}</span>
                </p>
              </div>
            </div>

            <section :aria-label="t('settings.teamLinks.live.latest')">
              <p :class="['mb-2 font-semibold text-muted', phone ? 'text-xs uppercase tracking-[0.08em]' : 'text-sm']">{{ t("settings.teamLinks.live.latest") }}</p>
              <TransitionGroup name="live" tag="ul" class="relative flex flex-col gap-1.5">
                <li
                  v-for="person in people"
                  :key="person.id"
                  :class="['live-person flex items-center gap-3 rounded-[12px] px-3', phone ? 'py-2' : 'py-2.5', fresh.has(person.id) ? 'is-fresh' : 'bg-surface']"
                  data-live-person
                >
                  <UserAvatar :name="person.name" :src="person.photo_url" :size="phone ? 34 : 42" />
                  <div class="min-w-0 flex-1">
                    <p :class="['truncate font-semibold text-fg', phone ? 'text-base' : 'text-md']">{{ person.name }}</p>
                    <p class="truncate text-sm text-muted">{{ personLine(person) }}</p>
                  </div>
                </li>
              </TransitionGroup>
              <p v-if="!people.length" :class="['rounded-[12px] border border-dashed border-line-strong px-4 text-muted', phone ? 'py-3 text-sm' : 'py-5 text-base']" data-live-waiting>
                {{ t(open ? "settings.teamLinks.live.waiting" : "settings.teamLinks.live.nobody") }}
              </p>
            </section>
          </aside>
        </main>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
.live-person {
  transition: background-color 1.2s var(--ease-standard);
}
.live-person.is-fresh {
  background: var(--c-accent-soft);
  transition-duration: var(--dur-fade);
}
.live-move,
.live-enter-active,
.live-leave-active {
  transition:
    opacity 360ms var(--ease-out),
    transform 360ms var(--ease-out);
}
.live-enter-from {
  opacity: 0;
  transform: translate3d(0, -10px, 0) scale(0.98);
}
.live-leave-to {
  opacity: 0;
}
.live-leave-active {
  position: absolute;
  inset-inline: 0;
}
:root[data-motion="reduced"] .live-enter-from {
  transform: none;
}
</style>
