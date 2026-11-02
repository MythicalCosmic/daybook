<script setup lang="ts">
/**
 * Which documents each position needs (the compliance matrix's columns): grouped by position,
 * "Everyone" first; add one (a position, or everyone, and a kind) or take one away.
 */
import { ListChecks, Plus, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import type { SelectOption } from "@/components/options";
import PositionPicker from "@/components/PositionPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";

import { hrApi, useHrMutation, useRequired } from "../api";
import { kindGroup } from "../lib";
import { DOCUMENT_KINDS, type DocumentKind, type RequiredDocument } from "../types";

const open = defineModel<boolean>("open", { default: false });

const { t, locale } = useI18n();
const query = useRequired(open);

const groups = computed(() => {
  const collator = new Intl.Collator(locale.value);
  const map = new Map<string, { key: string; name: string | null; rows: RequiredDocument[] }>();
  for (const row of query.data.value ?? []) {
    const key = row.position ? `p${row.position.id}` : "all";
    const group = map.get(key) ?? { key, name: row.position?.name ?? null, rows: [] };
    group.rows.push(row);
    map.set(key, group);
  }
  return [...map.values()].sort((a, b) => (a.name === null ? -1 : b.name === null ? 1 : collator.compare(a.name, b.name)));
});

const position = ref<number | null>(null);
const kind = ref<DocumentKind | null>(null);
const kindOptions = computed<SelectOption<DocumentKind>[]>(() =>
  DOCUMENT_KINDS.map((value) => ({ value, label: t(`hr.kind.${value}`), group: t(`hr.kindGroup.${kindGroup(value)}`) })),
);

const add = useHrMutation((cid, input: { kind: string; position_id: number | null }) => hrApi.addRequired(cid, input));
const remove = useHrMutation((cid, id: number) => hrApi.removeRequired(cid, id));

async function submit(): Promise<void> {
  if (!kind.value) return;
  try {
    await add.mutateAsync({ kind: kind.value, position_id: position.value });
    toast.success(t("hr.required.added"));
    kind.value = null;
  } catch {
    // The HTTP layer showed why (already required, for example).
  }
}

async function drop(row: RequiredDocument): Promise<void> {
  try {
    await remove.mutateAsync(row.id);
  } catch {
    // Shown by the HTTP layer.
  }
}
</script>

<template>
  <UiDrawer v-model:open="open" size="md" :title="t('hr.required.title')" :description="t('hr.required.description')">
    <div class="flex flex-col gap-5 p-5">
      <section class="flex flex-col gap-3 rounded-card border border-line p-3.5">
        <h3 class="text-sm font-semibold text-fg">{{ t("hr.required.add") }}</h3>
        <FormField :label="t('hr.required.position')" :hint="t('hr.required.positionHint')">
          <PositionPicker v-model="position" :placeholder="t('hr.required.everyone')" />
        </FormField>
        <FormField :label="t('hr.field.kind')">
          <SelectBox v-model="kind" :options="kindOptions" :placeholder="t('hr.document.kindPlaceholder')" />
        </FormField>
        <UiButton variant="primary" class="w-fit" :icon="Plus" :disabled="!kind" :loading="add.isPending.value" @click="submit">{{ t("hr.required.addButton") }}</UiButton>
      </section>

      <div v-if="query.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 4" :key="n" height="40px" /></div>
      <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
      <EmptyState v-else-if="!groups.length" size="sm" tone="neutral" :icon="ListChecks" :title="t('hr.required.emptyTitle')" :description="t('hr.required.emptyBody')" />
      <section v-for="group in groups" v-else :key="group.key" class="flex flex-col gap-1.5">
        <h3 class="text-xs font-semibold uppercase tracking-[0.04em] text-subtle">{{ group.name ?? t("hr.required.everyone") }}</h3>
        <ul class="flex flex-col divide-y divide-line rounded-[10px] border border-line">
          <li v-for="row in group.rows" :key="row.id" class="flex min-h-11 items-center gap-2 py-1 pl-3 pr-1">
            <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ t(`hr.kind.${row.kind}`) }}</span>
            <IconButton :icon="Trash2" size="md" :label="t('hr.required.remove', { kind: t(`hr.kind.${row.kind}`) })" @click="drop(row)" />
          </li>
        </ul>
      </section>
    </div>
  </UiDrawer>
</template>
