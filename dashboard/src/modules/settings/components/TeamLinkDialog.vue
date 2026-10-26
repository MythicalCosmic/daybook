<script setup lang="ts">
/**
 * Make or change a team link (Settings › Invite staff): a name, whether people are added straight
 * away (on by default), the branch and role they get, an optional position, how many places and
 * how long it works (7 days by default). A new link's name follows the chosen branch until it is
 * typed over. Saving a new link hands it to the panel, which opens its live screen: the owner's
 * next step is to show it. An edit sends only what changed.
 */
import { Check, QrCode, ShieldAlert } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import { useScopedBranches } from "@/components/pickers";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { addDays, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useActivePositions, useJoinLinkMutations, useLinkRoles } from "../api";
import { DEFAULT_END_TIME, MAX_AHEAD_DAYS, VALID_FOR, defaultName, expiresAt, expiryProblem, validForOf, whenText, type ValidFor } from "../teamLinks";
import type { JoinLink, JoinLinkInput, JoinLinkPatch } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ link?: JoinLink | null }>();
const emit = defineEmits<{ saved: [link: JoinLink, created: boolean] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const branches = useScopedBranches();
const roles = useLinkRoles();
const positions = useActivePositions();
const { create, update } = useJoinLinkMutations();

/** The role choice that means "the company's default role when they join" (`role_id: null`). */
const DEFAULT_ROLE = 0;
const PLACE_CHIPS = [10, 20, 50] as const;

const editing = computed(() => !!props.link);
const tz = computed(() => company.timezone);
const today = computed(() => todayIn(tz.value));
const todayLabel = computed(() => fmt.day(today.value, "short"));
const severalBranches = computed(() => branches.value.length > 1);
const onlyBranch = computed(() => (branches.value.length === 1 ? branches.value[0]! : null));

const startEnd = validForOf(props.link ?? null, company.timezone);
const form = reactive({
  name: props.link?.name ?? defaultName(t, todayLabel.value, onlyBranch.value?.name),
  auto: props.link?.auto_approve ?? true,
  branchId: props.link?.branch?.id ?? onlyBranch.value?.id ?? null,
  role: props.link?.role?.id ?? DEFAULT_ROLE,
  positionId: props.link?.position?.id ?? null,
  maxUses: props.link ? props.link.max_uses : null,
  validFor: startEnd.choice,
  endDay: startEnd.day ?? addDays(today.value, 1),
  endTime: startEnd.time ?? DEFAULT_END_TIME,
});
const errors = reactive<Record<string, string | undefined>>({});
/** A new link's name follows its branch until someone types one. */
const nameTyped = ref(editing.value);
/** An edited link keeps its end unless the "Works for" choice is touched. */
const endTouched = ref(false);

watch(
  () => form.branchId,
  (id) => {
    if (nameTyped.value) return;
    form.name = defaultName(t, todayLabel.value, branches.value.find((b) => b.id === id)?.name);
  },
);

const roleOptions = computed(() => {
  const list = roles.data.value ?? [];
  const fallback = list.find((role) => role.is_default);
  const options = [{ value: DEFAULT_ROLE, label: fallback ? t("settings.teamLinks.field.defaultRole", { name: fallback.name }) : t("settings.teamLinks.field.defaultRoleBare") }];
  // Never the Owner role: a link that anyone may open must not hand out the whole company.
  for (const role of list) if (role.can_assign && !role.is_default && !role.is_owner) options.push({ value: role.id, label: role.name });
  // An edited link whose role is the default one by id still shows a choice.
  if (props.link?.role && !options.some((option) => option.value === props.link!.role!.id)) options.push({ value: props.link.role.id, label: props.link.role.name });
  return options;
});
const positionOptions = computed(() => (positions.data.value ?? []).filter((p) => p.is_active).map((p) => ({ value: p.id, label: p.name })));

const validForOptions = computed(() => VALID_FOR.map((value) => ({ value, label: t(`settings.teamLinks.validFor.${value}`) })));
/**
 * A link that adds people straight away needs a branch once the company has two; someone limited
 * to some branches always gives one of theirs (the backend refuses a link without one from them).
 */
const branchRequired = computed(() => (form.auto && severalBranches.value) || (company.current?.branch_scope ?? null) !== null);
const endIso = (now: number) => expiresAt(form.validFor, now, { day: form.endDay, time: form.endTime, tz: tz.value });
const endPreview = computed(() => {
  if (form.validFor === "none") return t("settings.teamLinks.validFor.noneHint");
  const iso = endIso(Date.now());
  return iso ? t("settings.teamLinks.end.until", { when: whenText(iso, tz.value, fmt.lang.value) }) : "";
});
/** Anyone with the link could join for ever: suggest a limit or an end. */
const wideOpen = computed(() => form.auto && form.maxUses === null && form.validFor === "none");
const busy = computed(() => create.isPending.value || update.isPending.value);

function pickValidFor(value: ValidFor): void {
  form.validFor = value;
  endTouched.value = true;
  errors.expires_at = undefined;
}

function validate(now: number): boolean {
  for (const key of Object.keys(errors)) errors[key] = undefined;
  if (!form.name.trim()) errors.name = t("common.form.required");
  if (branchRequired.value && !form.branchId) errors.branch_id = t("settings.teamLinks.field.branchRequired");
  if (form.validFor === "date" && (!form.endDay || !form.endTime)) errors.expires_at = t("common.form.required");
  else if (!editing.value || endTouched.value) {
    const problem = expiryProblem(endIso(now), now);
    if (problem) errors.expires_at = t(problem === "past" ? "settings.teamLinks.error.past" : "settings.teamLinks.error.tooFar");
  }
  return !Object.values(errors).some(Boolean);
}

function input(now: number): JoinLinkInput {
  return {
    name: form.name.trim(),
    auto_approve: form.auto,
    branch_id: form.branchId,
    role_id: form.role === DEFAULT_ROLE ? null : form.role,
    position_id: form.positionId,
    max_uses: form.maxUses,
    expires_at: endIso(now),
  };
}

/** Only the fields that differ from the link as it was. */
function changes(link: JoinLink, next: JoinLinkInput): JoinLinkPatch {
  const patch: JoinLinkPatch = {};
  if (next.name !== link.name) patch.name = next.name;
  if (next.auto_approve !== link.auto_approve) patch.auto_approve = next.auto_approve;
  if (next.branch_id !== (link.branch?.id ?? null)) patch.branch_id = next.branch_id;
  if (next.role_id !== (link.role?.id ?? null) && !(next.role_id === null && link.role === null)) patch.role_id = next.role_id;
  if (next.position_id !== (link.position?.id ?? null)) patch.position_id = next.position_id;
  if (next.max_uses !== link.max_uses) patch.max_uses = next.max_uses;
  if (endTouched.value && next.expires_at !== link.expires_at) patch.expires_at = next.expires_at;
  return patch;
}

async function submit(): Promise<void> {
  const now = Date.now();
  if (!validate(now)) return;
  const body = input(now);
  try {
    if (props.link) {
      const patch = changes(props.link, body);
      const saved = Object.keys(patch).length ? await update.mutateAsync({ id: props.link.id, patch }) : props.link;
      emit("saved", saved, false);
    } else {
      emit("saved", await create.mutateAsync(body), true);
    }
    open.value = false;
  } catch (error) {
    // Field messages go next to their fields; a sentence was already shown as a toast.
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t(editing ? 'settings.teamLinks.dialog.editTitle' : 'settings.teamLinks.dialog.newTitle')" size="md">
    <form id="team-link-form" class="flex flex-col gap-4" novalidate @submit.prevent="submit">
      <FormField :label="t('settings.teamLinks.field.name')" :hint="t('settings.teamLinks.field.nameHint')" :error="errors.name" required>
        <TextInput v-model="form.name" :maxlength="100" :placeholder="t('settings.teamLinks.field.namePlaceholder', { day: todayLabel })" @input="nameTyped = true" />
      </FormField>

      <div class="rounded-[12px] border border-line p-3.5" data-auto-approve>
        <ToggleSwitch
          v-model="form.auto"
          layout="row"
          :label="t('settings.teamLinks.field.auto')"
          :description="t(form.auto ? 'settings.teamLinks.field.autoOn' : 'settings.teamLinks.field.autoOff')"
        />
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField v-if="!onlyBranch" :label="t('settings.teamLinks.field.branch')" :error="errors.branch_id" :required="branchRequired" :optional="!branchRequired">
          <BranchPicker v-model="form.branchId" :clearable="!branchRequired" :placeholder="branchRequired ? undefined : t('settings.teamLinks.field.branchLater')" />
        </FormField>
        <FormField :label="t('settings.teamLinks.field.role')" :hint="t('settings.teamLinks.field.roleHint')" :error="errors.role_id">
          <SelectBox v-model="form.role" :options="roleOptions" />
        </FormField>
        <FormField :label="t('settings.teamLinks.field.position')" :hint="t('settings.teamLinks.field.positionHint')" :error="errors.position_id" optional>
          <SelectBox v-model="form.positionId" :options="positionOptions" :placeholder="t('settings.teamLinks.field.positionAny')" clearable />
        </FormField>
      </div>

      <FormField :label="t('settings.teamLinks.field.places')" :hint="t('settings.teamLinks.field.placesHint')" :error="errors.max_uses">
        <div class="flex flex-wrap items-center gap-1.5" role="group" :aria-label="t('settings.teamLinks.field.places')">
          <button type="button" :class="['team-chip pressable', form.maxUses === null && 'is-on']" :aria-pressed="form.maxUses === null" @click="form.maxUses = null">
            {{ t("settings.teamLinks.field.noLimit") }}
          </button>
          <button v-for="n in PLACE_CHIPS" :key="n" type="button" :class="['team-chip pressable tabular-nums', form.maxUses === n && 'is-on']" :aria-pressed="form.maxUses === n" @click="form.maxUses = n">
            {{ n }}
          </button>
          <NumberInput v-model="form.maxUses" class="!w-[132px]" :min="1" :max="500" :placeholder="t('settings.teamLinks.field.placesOther')" :suffix="t('settings.teamLinks.field.placesUnit')" size="sm" />
        </div>
      </FormField>

      <FormField :label="t('settings.teamLinks.field.validFor')" :error="form.validFor === 'date' ? undefined : errors.expires_at">
        <div class="flex flex-col gap-2">
          <div class="flex flex-wrap gap-1.5" role="group" :aria-label="t('settings.teamLinks.field.validFor')">
            <button v-for="option in validForOptions" :key="option.value" type="button" :class="['team-chip pressable', form.validFor === option.value && 'is-on']" :aria-pressed="form.validFor === option.value" @click="pickValidFor(option.value)">
              {{ option.label }}
            </button>
          </div>
          <p v-if="form.validFor !== 'date'" class="text-sm text-muted" data-end-preview>{{ endPreview }}</p>
        </div>
      </FormField>
      <div v-if="form.validFor === 'date'" class="-mt-1 grid grid-cols-[minmax(0,1fr)_128px] items-start gap-3" data-end-at>
        <FormField :label="t('settings.teamLinks.field.endDay')" :error="errors.expires_at">
          <DatePicker v-model="form.endDay" :min="today" :max="addDays(today, MAX_AHEAD_DAYS)" @update:model-value="endTouched = true" />
        </FormField>
        <FormField :label="t('settings.teamLinks.field.endTime')">
          <TimePicker v-model="form.endTime" :step="30" @update:model-value="endTouched = true" />
        </FormField>
      </div>

      <InlineAlert v-if="wideOpen" tone="warning" size="sm" :icon="ShieldAlert" :description="t('settings.teamLinks.field.wideOpen')" />
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="team-link-form" :icon="editing ? Check : QrCode" :loading="busy">
        {{ editing ? t("common.save") : t("settings.teamLinks.dialog.create") }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.team-chip {
  display: inline-flex;
  height: 30px;
  align-items: center;
  border-radius: 999px;
  border: 1px solid var(--c-border-strong);
  background: var(--c-surface);
  padding: 0 12px;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--c-text);
  white-space: nowrap;
  transition:
    background-color var(--dur-fade) var(--ease-standard),
    border-color var(--dur-fade) var(--ease-standard),
    color var(--dur-fade) var(--ease-standard);
}
.team-chip:hover {
  background: var(--c-highlight);
}
.team-chip.is-on {
  border-color: var(--c-primary);
  background: var(--c-accent-soft);
  color: var(--c-accent-fg);
}
</style>
