<script setup lang="ts">
/** The top three on steps of three heights: second, first, third, with their pictures and levels. */
import { Crown } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";

import type { BoardRow } from "../types";

const props = defineProps<{ rows: BoardRow[] }>();
const emit = defineEmits<{ open: [row: BoardRow] }>();
const { t } = useI18n();
const fmt = useFormat();
const order = computed(() => [props.rows[1], props.rows[0], props.rows[2]].filter((row): row is BoardRow => row !== undefined));
</script>

<template>
  <div class="rcg-podium" data-testid="podium">
    <button v-for="row in order" :key="row.member.id" type="button" class="rcg-podium-place" :class="`rcg-podium-place--${row.place}`" @click="emit('open', row)">
      <span class="relative inline-flex">
        <Crown v-if="row.place === 1" :size="22" :stroke-width="2.4" class="rcg-podium-crown" aria-hidden="true" />
        <UserAvatar :name="row.member.name" :src="row.member.avatar_url" :size="row.place === 1 ? 64 : 48" />
      </span>
      <span class="max-w-full truncate font-semibold text-fg">{{ row.member.name }}</span>
      <span class="text-xs text-muted">{{ t("recognition.board.levelShort", { number: row.level.number, name: row.level.name }) }}</span>
      <span class="text-sm font-semibold tabular-nums text-fg">{{ t("recognition.points", { n: fmt.number(row.points) }, row.points) }}</span>
      <span class="rcg-podium-step tabular-nums">{{ row.place }}</span>
    </button>
  </div>
</template>

<style scoped>
.rcg-podium {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: end;
  gap: 12px;
  max-width: 640px;
  margin: 0 auto;
  padding-top: 20px;
}
.rcg-podium-place {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-width: 0;
  border-radius: 12px;
  padding: 4px;
  cursor: pointer;
}
.rcg-podium-place:focus-visible {
  outline: 2px solid var(--c-ring);
}
.rcg-podium-crown {
  position: absolute;
  top: -20px;
  left: 50%;
  transform: translateX(-50%) rotate(-8deg);
  color: #d39b22;
}
.rcg-podium-step {
  display: grid;
  place-items: center;
  width: 100%;
  margin-top: 6px;
  border-radius: 12px 12px 4px 4px;
  font-size: 22px;
  font-weight: 700;
  color: #3a2a1a;
}
.rcg-podium-place--1 .rcg-podium-step {
  height: 96px;
  background: linear-gradient(180deg, #ffe08a, #d39b22);
}
.rcg-podium-place--2 .rcg-podium-step {
  height: 72px;
  background: linear-gradient(180deg, #eef1f4, #a5adb6);
}
.rcg-podium-place--3 .rcg-podium-step {
  height: 56px;
  background: linear-gradient(180deg, #e8b07a, #b7733d);
}
@media (prefers-reduced-motion: no-preference) {
  .rcg-podium-step {
    animation: rcg-rise 480ms cubic-bezier(0.22, 1, 0.36, 1) both;
  }
  .rcg-podium-place--2 .rcg-podium-step {
    animation-delay: 70ms;
  }
  .rcg-podium-place--3 .rcg-podium-step {
    animation-delay: 140ms;
  }
}
@media (hover: hover) {
  .rcg-podium-place:hover {
    background: var(--c-surface-2);
  }
}
@keyframes rcg-rise {
  from {
    transform: translateY(16px);
    opacity: 0;
  }
  to {
    transform: none;
    opacity: 1;
  }
}
</style>
