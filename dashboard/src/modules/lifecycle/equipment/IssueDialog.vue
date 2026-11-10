<script setup lang="ts">
/**
 * Give one or more things to someone: who, what (uniforms and keys by count from the stock — the
 * first free ones are taken — or exact items; devices one by one with their serial), the state
 * they are in, a photo and a note. They hear it in the staff bot and confirm in the app; the page
 * shows when they did.
 */
import { ChevronDown, HandHelping, Minus, Plus, Search, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import CheckBox from "@/components/CheckBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyToday } from "@/stores/company";

import { equipmentApi, useEquipmentMutation, useStock } from "./api";
import { categoryIcon, issueErrors, issuePayload, naturalOrder, type IssueErrors, type IssueForm } from "./lib";
import PhotoField from "./PhotoField.vue";
import type { Condition, Holder, IssueInput, StockItem } from "./types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ person?: { id: number; name: string } | null; items?: number[] }>(), { person: null, items: () => [] });
const emit = defineEmits<{ saved: [holder: Holder] }>();

const { t } = useI18n();
const today = useCompanyToday();

const blank = (): IssueForm => ({ person: props.person?.id ?? null, items: [...props.items], on: today.value, condition: "good", note: "", photo: null });
const form = ref<IssueForm>(blank());
const errors = ref<IssueErrors>({});
const query = ref("");
const expanded = ref(new Set<number>());
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    form.value = blank();
    errors.value = {};
    query.value = "";
    expanded.value = new Set();
  },
  { immediate: true },
);

const stock = useStock("stock", open);
const groups = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase();
  const map = new Map<number, { category: StockItem["category"]; items: StockItem[] }>();
  for (const item of [...(stock.data.value ?? [])].sort(naturalOrder)) {
    if (needle && ![item.name, item.number, item.serial, item.category.name].some((text) => text.toLocaleLowerCase().includes(needle))) continue;
    const group = map.get(item.category.id) ?? { category: item.category, items: [] };
    group.items.push(item);
    map.set(item.category.id, group);
  }
  return [...map.values()];
});
const byId = computed(() => new Map((stock.data.value ?? []).map((item) => [item.id, item])));
const chosen = computed(() => form.value.items.map((id) => byId.value.get(id)).filter((item): item is StockItem => !!item));
const countIn = (group: { items: StockItem[] }) => group.items.filter((item) => form.value.items.includes(item.id)).length;

/** Uniforms and keys by count: one more takes the first free one, one less puts the last back. */
function step(group: { items: StockItem[] }, by: 1 | -1): void {
  const ids = group.items.map((item) => item.id);
  if (by === 1) {
    const next = ids.find((id) => !form.value.items.includes(id));
    if (next !== undefined) form.value.items = [...form.value.items, next];
  } else {
    const last = [...form.value.items].reverse().find((id) => ids.includes(id));
    if (last !== undefined) form.value.items = form.value.items.filter((id) => id !== last);
  }
}
function toggleItem(id: number, on: boolean): void {
  form.value.items = on ? [...new Set([...form.value.items, id])] : form.value.items.filter((each) => each !== id);
}
function toggleGroup(id: number): void {
  const next = new Set(expanded.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expanded.value = next;
}

const conditions = computed(() => (["new", "good", "worn"] as Condition[]).map((value) => ({ value, label: t(`lifecycle.equipment.condition.${value}`) })));
const message = (key: string | undefined) => (key ? t(`lifecycle.equipment.error.${key}`) : null);
const save = useEquipmentMutation((cid, input: IssueInput) => equipmentApi.issue(cid, input));

async function submit(): Promise<void> {
  errors.value = issueErrors(form.value, today.value);
  if (Object.keys(errors.value).length) return;
  try {
    const holder = await save.mutateAsync(issuePayload(form.value));
    toast.success(t("lifecycle.equipment.issue.done", { name: holder.person.name, n: form.value.items.length }, form.value.items.length));
    emit("saved", holder);
    open.value = false;
  } catch {
    // The HTTP layer showed why (someone took it meanwhile, they no longer work here).
  }
}
const title = computed(() => (props.person ? t("lifecycle.equipment.issue.titleFor", { name: props.person.name }) : t("lifecycle.equipment.issue.title")));
</script>

<template>
  <UiDialog v-model:open="open" size="md" :title="title" :description="t('lifecycle.equipment.issue.description')">
    <div class="flex flex-col gap-4">
      <FormField v-if="!person" :label="t('lifecycle.equipment.field.person')" :error="message(errors.person)" required>
        <PersonPicker v-model="form.person" :invalid="!!errors.person" />
      </FormField>

      <FormField :label="t('lifecycle.equipment.issue.what')" :error="message(errors.items)" required>
        <div class="flex flex-col gap-2">
          <TextInput v-if="(stock.data.value?.length ?? 0) > 8" v-model="query" type="search" size="sm" :icon="Search" clearable :placeholder="t('lifecycle.equipment.issue.search')" />
          <div v-if="stock.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="46px" radius="12px" /></div>
          <div v-else-if="!groups.length" class="rounded-[12px] border border-dashed border-line-strong">
            <EmptyState size="sm" tone="neutral" :title="query ? t('lifecycle.equipment.issue.noMatch') : t('lifecycle.equipment.issue.noStock')" :description="query ? undefined : t('lifecycle.equipment.issue.noStockBody')" />
          </div>
          <ul v-else class="flex max-h-[min(22rem,42dvh)] flex-col gap-1.5 overflow-y-auto pr-0.5" data-issue-groups>
            <li v-for="group in groups" :key="group.category.id" class="rounded-[12px] border border-line" :data-issue-group="group.category.id">
              <div class="flex items-center gap-2.5 px-3 py-2">
                <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-surface-2 text-muted dark:bg-surface-3"><component :is="categoryIcon(group.category.icon)" :size="16" aria-hidden="true" /></span>
                <button type="button" class="min-w-0 flex-1 text-left" @click="toggleGroup(group.category.id)">
                  <span class="block truncate text-sm font-semibold text-fg">{{ group.category.name }}</span>
                  <span class="block truncate text-xs text-muted">{{ t("lifecycle.equipment.inStock", { n: group.items.length }, group.items.length) }}</span>
                </button>
                <div v-if="group.category.kind === 'low_value'" class="flex shrink-0 items-center rounded-[9px] border border-line" data-stepper>
                  <button type="button" class="grid size-8 place-items-center text-muted hover:text-fg disabled:opacity-40" :disabled="!countIn(group)" :aria-label="t('lifecycle.equipment.issue.less', { name: group.category.name })" @click="step(group, -1)">
                    <Minus :size="14" />
                  </button>
                  <span class="min-w-6 text-center text-sm font-semibold tabular-nums text-fg" data-count>{{ countIn(group) }}</span>
                  <button type="button" class="grid size-8 place-items-center text-muted hover:text-fg disabled:opacity-40" :disabled="countIn(group) >= group.items.length" :aria-label="t('lifecycle.equipment.issue.more', { name: group.category.name })" data-more @click="step(group, 1)">
                    <Plus :size="14" />
                  </button>
                </div>
                <button type="button" class="grid size-8 shrink-0 place-items-center rounded-[8px] text-muted hover:bg-surface-2" :aria-expanded="expanded.has(group.category.id) || group.category.kind !== 'low_value'" :aria-label="t('lifecycle.equipment.issue.choose', { name: group.category.name })" @click="toggleGroup(group.category.id)">
                  <ChevronDown :size="15" :class="['transition-transform', expanded.has(group.category.id) || group.category.kind !== 'low_value' ? 'rotate-180' : '']" />
                </button>
              </div>
              <ul v-if="expanded.has(group.category.id) || group.category.kind !== 'low_value'" class="flex flex-col border-t border-line px-2 py-1.5">
                <li v-for="item in group.items" :key="item.id">
                  <label class="flex cursor-pointer items-center gap-2.5 rounded-[8px] px-1.5 py-1.5 hover:bg-surface-2/70" :data-issue-item="item.id">
                    <CheckBox :model-value="form.items.includes(item.id)" :aria-label="item.name" @update:model-value="(on: boolean) => toggleItem(item.id, on)" />
                    <span class="min-w-0 flex-1">
                      <span class="block truncate text-sm text-fg">{{ item.model ? `${item.name} · ${item.model}` : item.name }}</span>
                      <span class="block truncate text-xs text-muted">{{ [item.number, item.serial ? t("lifecycle.equipment.serial", { serial: item.serial }) : "", item.notes, item.branch?.name].filter(Boolean).join(" · ") }}</span>
                    </span>
                  </label>
                </li>
              </ul>
            </li>
          </ul>
          <div v-if="chosen.length" class="flex flex-wrap gap-1.5" data-issue-chosen>
            <span v-for="item in chosen" :key="item.id" class="inline-flex max-w-full items-center gap-1 rounded-full bg-accent-soft py-0.5 pl-2.5 pr-1 text-xs font-medium text-accent-fg">
              <span class="truncate">{{ item.name }}</span>
              <button type="button" class="grid size-5 place-items-center rounded-full hover:bg-surface/60" :aria-label="t('lifecycle.equipment.issue.remove', { name: item.name })" @click="toggleItem(item.id, false)"><X :size="12" /></button>
            </span>
          </div>
        </div>
      </FormField>

      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('lifecycle.equipment.field.condition')">
          <SegmentedControl v-model="form.condition" :options="conditions" size="sm" block :aria-label="t('lifecycle.equipment.field.condition')" />
        </FormField>
        <FormField :label="t('lifecycle.equipment.field.day')" :error="message(errors.on)" required>
          <DatePicker v-model="form.on" :max="today" :invalid="!!errors.on" />
        </FormField>
      </div>
      <FormField :label="t('lifecycle.equipment.field.photo')" :hint="t('lifecycle.equipment.issue.photoHint')" optional>
        <PhotoField v-model="form.photo" />
      </FormField>
      <FormField :label="t('lifecycle.equipment.field.note')" optional>
        <TextArea v-model="form.note" :rows="2" :maxlength="300" :placeholder="t('lifecycle.equipment.issue.notePlaceholder')" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="HandHelping" :loading="save.isPending.value" data-issue-submit @click="submit">
        {{ form.items.length ? t("lifecycle.equipment.issue.submitN", { n: form.items.length }, form.items.length) : t("lifecycle.equipment.issue.submit") }}
      </UiButton>
    </template>
  </UiDialog>
</template>
