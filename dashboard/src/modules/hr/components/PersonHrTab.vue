<script setup lang="ts">
/**
 * Person 360 › HR (registered by this module): the HR profile (personal details, IDs masked with a
 * reveal for hr.sensitive that the server audits), emergency contacts, the contract and the
 * documents. hr.manage edits; everyone else with hr.view reads.
 */
import { CircleCheck, Eye, EyeOff, FilePlus2, FileSignature, FileText, IdCard, LockKeyhole, Pencil, Phone, Plus, ShieldAlert, UserRound } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { formatPhone } from "@/lib/format";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { hrApi, useContracts, useDocuments, useOverview, useProfile } from "../api";
import { CONTRACT_TONES, groupDigits, hrAccess, idDisplay, onProbation, SENSITIVE_FIELDS } from "../lib";
import type { HrDocument, HrSensitive, SensitiveField } from "../types";
import ContractFormDialog from "./ContractFormDialog.vue";
import DaysChip from "./DaysChip.vue";
import DocumentDrawer from "./DocumentDrawer.vue";
import DocumentFormDrawer from "./DocumentFormDrawer.vue";
import EmergencyContacts from "./EmergencyContacts.vue";
import ProfileEditDrawer from "./ProfileEditDrawer.vue";

const props = defineProps<{ memberId: number }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();
const access = computed(() => hrAccess((perm) => company.can(perm)));

const query = useProfile(() => props.memberId);
const profile = computed(() => query.data.value ?? null);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const overview = useOverview();
const warn = computed(() => overview.data.value?.warn_days ?? { documents: 30, contracts: 30, probation: 7 });

const documents = useDocuments(() => ({ member: props.memberId, page_size: 50, ordering: "expires_on" }));
const contracts = useContracts(() => ({ member: props.memberId, page_size: 20, ordering: "-starts_on" }));
/** The contract in force, else the newest one. */
const contract = computed(() => {
  const rows = contracts.data.value?.results ?? [];
  return rows.find((row) => row.status === "active") ?? rows.find((row) => row.status === "draft") ?? rows[0] ?? null;
});
const olderContracts = computed(() => Math.max(0, (contracts.data.value?.count ?? 0) - 1));

// IDs: masked; hr.sensitive may reveal them (each reveal is audited on the server).
const revealed = ref<HrSensitive | null>(null);
const revealing = ref(false);
watch(
  () => props.memberId,
  () => (revealed.value = null),
);
async function reveal(): Promise<void> {
  revealing.value = true;
  try {
    revealed.value = await hrApi.sensitive(cid.value, props.memberId);
  } catch {
    // The HTTP layer said why.
  } finally {
    revealing.value = false;
  }
}
function hide(): void {
  revealed.value = null;
  toast.info(t("hr.profile.hidden"));
}
const ids = computed(() =>
  profile.value
    ? SENSITIVE_FIELDS.map((field: SensitiveField) => ({ field, ...idDisplay(profile.value!, field, revealed.value, access.value.sensitive) }))
    : [],
);
const canReveal = computed(() => ids.value.some((id) => id.canReveal));
const anyRevealed = computed(() => ids.value.some((id) => id.revealed));

const details = computed<DescriptionItem[]>(() => {
  const p = profile.value;
  if (!p) return [];
  return [
    { key: "number", label: t("hr.profile.employeeNumber"), value: p.employee_number || null },
    { key: "hire", label: t("hr.profile.hireDate"), value: p.hire_date ? fmt.day(p.hire_date, "long") : null },
    { key: "type", label: t("hr.profile.employmentType"), value: t(`hr.employmentType.${p.employment_type}`) },
    { key: "birth", label: t("hr.profile.birthDate"), value: p.birth_date ? fmt.day(p.birth_date, "long") : null, hint: p.birth_date && !p.show_birthday ? t("hr.profile.birthdayHidden") : undefined },
    { key: "gender", label: t("hr.profile.gender"), value: p.gender ? t(`hr.gender.${p.gender}`) : null },
    { key: "middle", label: t("hr.profile.middleName"), value: p.middle_name || null },
    { key: "phone", label: t("hr.profile.personalPhone"), value: p.personal_phone ? formatPhone(p.personal_phone) : null },
    { key: "email", label: t("hr.profile.email"), value: p.email || null },
    { key: "address", label: t("hr.profile.address"), value: [p.address, p.city].filter(Boolean).join(", ") || null, wide: true },
    ...(p.terminated_on ? [{ key: "terminated", label: t("hr.profile.terminatedOn"), value: fmt.day(p.terminated_on, "long"), hint: p.termination_reason ? t(`hr.terminationReason.${p.termination_reason}`) : undefined }] : []),
  ];
});

const editing = ref(false);
const uploading = ref(false);
const editingDoc = ref<HrDocument | null>(null);
const editDocOpen = computed({
  get: () => editingDoc.value !== null,
  set: (value: boolean) => {
    if (!value) editingDoc.value = null;
  },
});
const creatingContract = ref(false);
const member = computed(() => (profile.value ? { id: profile.value.member.id, name: profile.value.member.name } : null));
function openDocument(id: number): void {
  void router.push({ query: { ...route.query, document: String(id) } });
}
const contractLink = computed(() => (contract.value ? { path: `/c/${company.currentId}/hr/contracts`, query: { contract: String(contract.value.id), status: "all" } } : null));
</script>

<template>
  <div v-if="skeleton" class="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
    <div class="ui-card flex flex-col gap-4 p-5"><SkeletonBlock v-for="n in 6" :key="n" height="18px" /></div>
    <div class="ui-card flex flex-col gap-4 p-5"><SkeletonBlock v-for="n in 4" :key="n" height="18px" /></div>
  </div>
  <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
  <div v-else-if="profile" class="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
    <div class="flex min-w-0 flex-col gap-4">
      <!-- Profile -->
      <section class="ui-card overflow-hidden" data-hr-profile>
        <header class="flex items-center gap-2 border-b border-line px-5 py-3">
          <UserRound :size="16" class="text-subtle" aria-hidden="true" />
          <h2 class="flex-1 text-md font-semibold text-fg">{{ t("hr.profile.title") }}</h2>
          <UiButton v-if="access.manage" size="sm" :icon="Pencil" @click="editing = true">{{ t("common.edit") }}</UiButton>
        </header>
        <div class="p-5">
          <DescriptionList :items="details" :columns="2">
            <template #value-phone="{ item }">
              <a v-if="profile.personal_phone" :href="`tel:${profile.personal_phone}`" class="inline-flex items-center gap-1.5 tabular-nums hover:text-primary"><Phone :size="14" class="text-subtle" />{{ item.value }}</a>
              <span v-else class="text-subtle">—</span>
            </template>
          </DescriptionList>
        </div>
      </section>

      <!-- IDs: masked, revealed only for hr.sensitive (audited) -->
      <section class="ui-card overflow-hidden" data-hr-ids>
        <header class="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
          <IdCard :size="16" class="text-subtle" aria-hidden="true" />
          <h2 class="flex-1 text-md font-semibold text-fg">{{ t("hr.profile.ids") }}</h2>
          <UiButton v-if="anyRevealed" size="sm" variant="ghost" :icon="EyeOff" @click="hide">{{ t("hr.profile.hide") }}</UiButton>
          <UiButton v-else-if="canReveal" size="sm" :icon="Eye" :loading="revealing" data-reveal @click="reveal">{{ t("hr.profile.reveal") }}</UiButton>
        </header>
        <div class="flex flex-col gap-3 p-5">
          <dl class="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            <div v-for="id in ids" :key="id.field" class="min-w-0">
              <dt class="text-xs font-medium text-muted">{{ t(`hr.profile.id.${id.field}`) }}</dt>
              <dd class="mt-1 flex min-w-0 items-center gap-1.5 text-base text-fg" :data-id-field="id.field">
                <template v-if="id.text">
                  <LockKeyhole v-if="!id.revealed" :size="13" class="shrink-0 text-subtle" aria-hidden="true" />
                  <span :class="['min-w-0 truncate font-mono text-[0.92em] tabular-nums', id.revealed && 'text-fg', !id.revealed && 'text-muted']">{{ groupDigits(id.text) }}</span>
                </template>
                <span v-else class="text-subtle">{{ t("hr.profile.notRecorded") }}</span>
              </dd>
              <p v-if="id.field === 'payout_card'" class="mt-0.5 text-xs text-subtle">{{ t(`hr.payout.${profile.payout_method}`) }}</p>
            </div>
            <div class="min-w-0">
              <dt class="text-xs font-medium text-muted">{{ t("hr.profile.id.tin") }}</dt>
              <dd class="mt-1 font-mono text-[0.92em] tabular-nums text-fg">{{ profile.tin || "—" }}</dd>
            </div>
          </dl>
          <p v-if="anyRevealed" class="flex items-center gap-1.5 text-xs text-warning"><ShieldAlert :size="13" aria-hidden="true" />{{ t("hr.profile.revealAudited") }}</p>
          <p v-else-if="!access.sensitive" class="text-xs text-subtle">{{ t("hr.profile.maskedHint") }}</p>
        </div>
      </section>

      <EmergencyContacts :member-id="memberId" :contacts="profile.emergency_contacts" :can-manage="access.manage" />
    </div>

    <div class="flex min-w-0 flex-col gap-4">
      <!-- Contract -->
      <section class="ui-card overflow-hidden" data-hr-contract>
        <header class="flex items-center gap-2 border-b border-line px-5 py-3">
          <FileSignature :size="16" class="text-subtle" aria-hidden="true" />
          <h2 class="flex-1 text-md font-semibold text-fg">{{ t("hr.profile.contract") }}</h2>
          <UiButton v-if="access.manage && contract?.status !== 'active'" size="sm" :icon="Plus" @click="creatingContract = true">{{ t("hr.contract.new") }}</UiButton>
        </header>
        <div v-if="contracts.isPending.value" class="flex flex-col gap-2 p-5"><SkeletonBlock height="18px" width="60%" /><SkeletonBlock height="14px" width="80%" /></div>
        <ErrorState v-else-if="contracts.isError.value" compact class="m-4" :error="contracts.error.value" :retry="() => contracts.refetch()" />
        <EmptyState v-else-if="!contract" size="sm" tone="neutral" :icon="FileSignature" :title="t('hr.profile.noContract')" :description="t('hr.profile.noContractBody')" />
        <RouterLink v-else :to="contractLink!" class="flex flex-col gap-2 p-5 transition-colors hover:bg-highlight/60">
          <div class="flex flex-wrap items-center gap-2">
            <p class="min-w-0 flex-1 truncate text-base font-semibold text-fg">{{ t(`hr.contractKind.${contract.kind}`) }}<span v-if="contract.number" class="font-normal text-muted"> · № {{ contract.number }}</span></p>
            <StatusPill :tone="CONTRACT_TONES[contract.status]" size="sm" :label="t(`hr.contractStatus.${contract.status}`)" />
          </div>
          <p class="text-sm tabular-nums text-muted">{{ contract.ends_on ? fmt.range({ from: contract.starts_on, to: contract.ends_on }) : t("hr.contract.since", { date: fmt.day(contract.starts_on, "medium") }) }}</p>
          <div class="flex flex-wrap items-center gap-1.5">
            <DaysChip v-if="contract.ends_on && contract.status === 'active'" :day="contract.ends_on" :warn-days="warn.contracts" prefix="ends" />
            <DaysChip v-if="onProbation(contract)" :day="contract.probation_until!" :warn-days="warn.probation" prefix="probation" always />
            <StatusPill v-if="contract.acknowledged_at" tone="success" size="sm" :icon="CircleCheck" :dot="false" :label="t('hr.contract.acknowledged')" />
            <StatusPill v-else-if="contract.status === 'active'" tone="neutral" size="sm" :label="t('hr.contract.notAcknowledged')" />
            <StatusPill v-if="contract.file" tone="neutral" variant="outline" size="sm" :dot="false" :icon="FileText" label="PDF" />
          </div>
          <p v-if="olderContracts" class="text-xs text-subtle">{{ t("hr.profile.olderContracts", { n: olderContracts }, olderContracts) }}</p>
        </RouterLink>
      </section>

      <!-- Documents -->
      <section class="ui-card overflow-hidden" data-hr-documents>
        <header class="flex items-center gap-2 border-b border-line px-5 py-3">
          <FileText :size="16" class="text-subtle" aria-hidden="true" />
          <h2 class="flex-1 text-md font-semibold text-fg">{{ t("hr.nav.documents") }}</h2>
          <UiButton v-if="access.manage" size="sm" :icon="FilePlus2" @click="uploading = true">{{ t("hr.document.upload") }}</UiButton>
        </header>
        <div v-if="documents.isPending.value" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 3" :key="n" height="40px" /></div>
        <ErrorState v-else-if="documents.isError.value" compact class="m-4" :error="documents.error.value" :retry="() => documents.refetch()" />
        <EmptyState v-else-if="!documents.data.value?.results.length" size="sm" tone="neutral" :icon="FileText" :title="t('hr.profile.noDocuments')" :description="t('hr.profile.noDocumentsBody')" />
        <ul v-else class="divide-y divide-[var(--c-border)]">
          <li v-for="doc in documents.data.value!.results" :key="doc.id">
            <button type="button" class="flex min-h-12 w-full items-center gap-3 px-5 py-2.5 text-left transition-colors hover:bg-highlight" @click="openDocument(doc.id)">
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-fg">{{ doc.title || t(`hr.kind.${doc.kind}`) }}</p>
                <p class="truncate text-xs text-muted">
                  {{ doc.expires_on ? t("hr.document.expiresShort", { date: fmt.day(doc.expires_on, "medium") }) : t("hr.document.noExpiry") }}
                  <template v-if="doc.verified_at"> · {{ t("hr.document.verified") }}</template>
                </p>
              </div>
              <DaysChip v-if="doc.expires_on" :day="doc.expires_on" :warn-days="warn.documents" prefix="expires" />
              <LockKeyhole v-if="!doc.file && !access.sensitive && ['passport', 'id_card', 'military_id'].includes(doc.kind)" :size="14" class="shrink-0 text-subtle" aria-hidden="true" />
            </button>
          </li>
        </ul>
      </section>
    </div>

    <ProfileEditDrawer v-if="access.manage" v-model:open="editing" :profile="profile" />
    <DocumentFormDrawer v-if="access.manage" v-model:open="uploading" :member="member" />
    <ContractFormDialog v-if="access.manage" v-model:open="creatingContract" :member="member" />
    <DocumentFormDrawer v-if="access.manage" v-model:open="editDocOpen" :document="editingDoc" />
    <DocumentDrawer :warn-days="warn.documents" @edit="editingDoc = $event" />
  </div>
</template>
