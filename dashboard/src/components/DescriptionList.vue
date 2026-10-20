<script setup lang="ts">
/**
 * Facts about a record ("Position · Cashier", "Hired · 12 Mar 2024", "Phone · +998 …"): a grid of
 * label-over-value (`layout="grid"`) or label-left rows with dividers (`layout="rows"`, drawers).
 * `copy: true` adds a copy button; `#value-<key>` slots render rich values (pills, people, money).
 *
 *   <DescriptionList :items="[{ key: 'phone', label: t('people.phone'), value: fmt.phone, copy: true }, …]" />
 */
import { Check, Copy } from "@lucide/vue";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

export interface DescriptionItem {
  key: string;
  label: string;
  value?: string | number | null;
  hint?: string;
  copy?: boolean;
  /** Grid layout: take the whole row. */
  wide?: boolean;
  mono?: boolean;
}

withDefaults(defineProps<{ items: DescriptionItem[]; layout?: "grid" | "rows"; columns?: 1 | 2 | 3 | 4 }>(), { layout: "grid", columns: 2 });

defineSlots<{ [name: `value-${string}`]: ((props: { item: DescriptionItem }) => unknown) | undefined }>();

const { t } = useI18n();
const copied = ref<string | null>(null);

async function copy(item: DescriptionItem): Promise<void> {
  try {
    await navigator.clipboard.writeText(String(item.value ?? ""));
    copied.value = item.key;
    setTimeout(() => copied.value === item.key && (copied.value = null), 1500);
  } catch {
    // Clipboard blocked: nothing to do.
  }
}

const grid = { 1: "", 2: "sm:grid-cols-2", 3: "sm:grid-cols-2 lg:grid-cols-3", 4: "sm:grid-cols-2 lg:grid-cols-4" } as const;
</script>

<template>
  <dl v-if="layout === 'grid'" :class="['grid grid-cols-1 gap-x-6 gap-y-4', grid[columns]]">
    <div v-for="item in items" :key="item.key" :class="['min-w-0', item.wide && 'sm:col-span-full']">
      <dt class="text-xs font-medium text-muted">{{ item.label }}</dt>
      <dd class="group mt-1 flex min-w-0 items-center gap-1.5 text-base text-fg">
        <slot :name="`value-${item.key}`" :item="item">
          <span :class="['min-w-0 truncate', item.mono && 'font-mono text-[0.92em]', (item.value === null || item.value === undefined || item.value === '') && 'text-subtle']">{{
            item.value === null || item.value === undefined || item.value === "" ? "—" : item.value
          }}</span>
        </slot>
        <button
          v-if="item.copy && item.value"
          type="button"
          class="grid size-6 shrink-0 place-items-center rounded-[6px] text-subtle opacity-0 transition-opacity hover:bg-highlight hover:text-fg focus-visible:opacity-100 group-hover:opacity-100"
          :aria-label="copied === item.key ? t('common.copied') : t('common.copy')"
          @click="copy(item)"
        >
          <Check v-if="copied === item.key" :size="13" class="text-success" />
          <Copy v-else :size="13" />
        </button>
      </dd>
      <p v-if="item.hint" class="mt-0.5 text-xs text-subtle">{{ item.hint }}</p>
    </div>
  </dl>
  <dl v-else class="divide-y divide-[var(--c-border)]">
    <div v-for="item in items" :key="item.key" class="flex min-w-0 items-start gap-4 py-2.5">
      <dt class="w-[38%] shrink-0 pt-px text-sm text-muted">{{ item.label }}</dt>
      <dd class="group flex min-w-0 flex-1 items-center justify-end gap-1.5 text-right text-base text-fg">
        <slot :name="`value-${item.key}`" :item="item">
          <span :class="['min-w-0 truncate', item.mono && 'font-mono text-[0.92em]', (item.value === null || item.value === undefined || item.value === '') && 'text-subtle']">{{
            item.value === null || item.value === undefined || item.value === "" ? "—" : item.value
          }}</span>
        </slot>
        <button
          v-if="item.copy && item.value"
          type="button"
          class="grid size-6 shrink-0 place-items-center rounded-[6px] text-subtle hover:bg-highlight hover:text-fg"
          :aria-label="copied === item.key ? t('common.copied') : t('common.copy')"
          @click="copy(item)"
        >
          <Check v-if="copied === item.key" :size="13" class="text-success" />
          <Copy v-else :size="13" />
        </button>
      </dd>
    </div>
  </dl>
</template>
