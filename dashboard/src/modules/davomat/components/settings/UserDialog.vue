<script setup lang="ts">
/**
 * Adds a person who signs in to this app, or changes one (docs/DAVOMAT.md §1.3): name, username,
 * a first password (new users), the role and, for managers and viewers, the locations they see.
 * A new user ends on their sign-in details with Copy, so the admin can pass them on.
 */
import { Check, Copy, Crown, Eye, KeyRound, ScanFace, ShieldCheck, UserCog } from "@lucide/vue";
import { computed, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import ComboBox from "@/components/ComboBox.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import RadioCards, { type RadioCardOption } from "@/components/RadioCards.vue";
import type { OptionSource } from "@/components/options";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useForm } from "@/lib/useForm";
import { useCompanyStore } from "@/stores/company";

import { createUser, listEmployees, updateUser, type RoleOption } from "../../api";
import { suggestUsername, USERNAME_PATTERN, MIN_LENGTH } from "../../lib/password";
import type { Employee, User } from "../../types";
import PasswordField from "../fields/PasswordField.vue";
import { assignableRoles, roleKind, SCOPED, type KnownKind } from "./roles";

const open = defineModel<boolean>("open", { default: false });

const props = defineProps<{ user: User | null; roles: RoleOption[] }>();
const emit = defineEmits<{ saved: [user: User, created: boolean] }>();

const { t } = useI18n();
const company = useCompanyStore();

const creating = computed(() => props.user === null);
const isOwner = computed(() => props.user?.role?.kind === "owner");
/** Nobody changes their own role or locations (they could lock themselves out). */
const isSelf = computed(() => !!props.user && (props.user.is_self ?? props.user.id === company.current?.membership_id));
const roleLocked = computed(() => isOwner.value || isSelf.value);
// Only an owner gives the owner's role (the server refuses it to anyone else).
const choices = computed(() => assignableRoles(props.roles, { owner: company.current?.is_owner ?? false }));
const kindOf = (roleId: number | null): KnownKind | null => {
  if (roleId === null) return null;
  if (props.user?.role && props.user.role.id === roleId) return props.user.role.kind;
  const role = props.roles.find((r) => r.id === roleId);
  return role ? roleKind(role) : null;
};

const ICONS: Record<KnownKind, Component> = { owner: Crown, admin: ShieldCheck, manager: UserCog, viewer: Eye, other: KeyRound };
const roleOptions = computed<RadioCardOption<number>[]>(() =>
  choices.value.map((role) => ({
    value: role.id,
    label: role.name,
    description: t(`davomat.users.role.${role.roleKind}.hint`),
    icon: ICONS[role.roleKind],
  })),
);

const branchOptions = computed(() => (company.current?.branches ?? []).map((b) => ({ value: b.id, label: b.name })));

const schema = z
  .object({
    first_name: z.string().trim().min(1, "common.form.required").max(150, "common.form.tooLong"),
    last_name: z.string().trim().max(150, "common.form.tooLong"),
    username: z.string().trim().min(3, "davomat.users.usernameShort").max(150, "common.form.tooLong").regex(USERNAME_PATTERN, "davomat.users.usernameInvalid"),
    password: z.string(),
    role_id: z.number().nullable(),
    branch_ids: z.array(z.number()),
    employee_id: z.number().nullable(),
  })
  .superRefine((values, ctx) => {
    if (creating.value && fromEmployee.value && values.employee_id === null) ctx.addIssue({ code: "custom", path: ["employee_id"], message: "davomat.users.employeeRequired" });
    if (creating.value && values.password.length < MIN_LENGTH) ctx.addIssue({ code: "custom", path: ["password"], message: "davomat.password.tooShort" });
    if (!roleLocked.value && values.role_id === null) ctx.addIssue({ code: "custom", path: ["role_id"], message: "davomat.users.roleRequired" });
    const kind = kindOf(values.role_id);
    if (!roleLocked.value && kind && SCOPED.includes(kind) && values.branch_ids.length === 0) {
      ctx.addIssue({ code: "custom", path: ["branch_ids"], message: "davomat.users.branchesRequired" });
    }
  });

type Values = z.input<typeof schema>;

function initial(user: User | null): Values {
  const branches = company.current?.branches ?? [];
  return {
    first_name: user?.first_name ?? "",
    last_name: user?.last_name ?? "",
    username: user?.username ?? "",
    password: "",
    role_id: user?.role?.id ?? null,
    // One location: nothing to choose, the manager sees it.
    branch_ids: user ? [...user.branch_ids] : branches.length === 1 ? [branches[0]!.id] : [],
    employee_id: null,
  };
}

// ─── An employee who also signs in ────────────────────────────────────────────

/** Give someone who already scans at the terminals a sign-in, instead of adding a new person. */
const fromEmployee = ref(false);
const employees = new Map<number, Employee>();
const employeeSource: OptionSource<number> = async (query, signal) => {
  const page = await listEmployees(company.currentId ?? 0, { search: query.trim() || undefined, status: "active", page_size: 20 }, signal);
  return page.results
    .filter((employee) => !employee.is_user)
    .map((employee) => {
      employees.set(employee.id, employee);
      return {
        value: employee.id,
        label: employee.full_name,
        description: [employee.position?.name, employee.face_numbers.join(", ")].filter(Boolean).join(" · ") || undefined,
        avatar: { name: employee.full_name, src: employee.photo_url },
      };
    });
};
function pickEmployee(id: number | null): void {
  const employee = id === null ? undefined : employees.get(id);
  if (!employee) return;
  form.values.first_name = employee.first_name;
  form.values.last_name = employee.last_name;
  if (!usernameEdited.value) form.values.username = suggestUsername(employee.first_name, employee.last_name);
}

/** The details shown after a new user is created (with the password they were given). */
const created = ref<{ name: string; username: string; password: string } | null>(null);

const form = useForm(schema, initial(props.user), {
  onSubmit: async (values) => {
    const cid = company.currentId ?? 0;
    const kind = kindOf(values.role_id);
    const scoped = kind !== null && SCOPED.includes(kind);
    const body = {
      first_name: values.first_name.trim(),
      last_name: values.last_name.trim(),
      username: values.username.trim(),
      role_id: values.role_id ?? props.user?.role?.id ?? 0,
      // Administrators see every location; the server keeps their list empty.
      branch_ids: scoped ? values.branch_ids : [],
    };
    if (props.user) {
      const saved = await updateUser(cid, props.user.id, roleLocked.value ? { first_name: body.first_name, last_name: body.last_name, username: body.username } : body);
      emit("saved", saved, false);
      open.value = false;
      return;
    }
    const saved = await createUser(cid, { ...body, password: values.password, ...(fromEmployee.value && values.employee_id ? { employee_id: values.employee_id } : {}) });
    emit("saved", saved, true);
    created.value = { name: [body.first_name, body.last_name].filter(Boolean).join(" "), username: saved.username || body.username, password: values.password };
  },
});

// The username follows the name until it is typed by hand.
const usernameEdited = ref(!!props.user);

// A new dialog each time it opens: the user's current values, or a blank form.
watch(open, (isOpen) => {
  if (!isOpen) return;
  created.value = null;
  fromEmployee.value = false;
  usernameEdited.value = !!props.user;
  form.reset(initial(props.user));
});

watch(
  () => [form.values.first_name, form.values.last_name] as const,
  ([first, last]) => {
    if (!usernameEdited.value && creating.value) form.values.username = suggestUsername(first, last);
  },
);

const scopedRole = computed(() => {
  const kind = kindOf(form.values.role_id);
  return kind !== null && SCOPED.includes(kind);
});

const signInUrl = computed(() => `${window.location.origin}/dashboard/login`);
const copied = ref(false);
async function copyDetails(): Promise<void> {
  if (!created.value) return;
  const text = [
    `${t("davomat.users.details.address")}: ${signInUrl.value}`,
    `${t("davomat.users.fields.username")}: ${created.value.username}`,
    `${t("davomat.users.fields.password")}: ${created.value.password}`,
  ].join("\n");
  try {
    await navigator.clipboard.writeText(text);
    copied.value = true;
    setTimeout(() => (copied.value = false), 2000);
  } catch {
    // No clipboard: everything is on screen.
  }
}

const title = computed(() => (created.value ? t("davomat.users.details.title") : props.user ? t("davomat.users.editTitle") : t("davomat.users.createTitle")));
const description = computed(() =>
  created.value ? t("davomat.users.details.hint", { name: created.value.name }) : props.user ? undefined : t("davomat.users.createHint"),
);
</script>

<template>
  <UiDialog v-model:open="open" :title="title" :description="description" size="md">
    <!-- Created: the sign-in details to pass on -->
    <div v-if="created" class="flex flex-col gap-4" data-created>
      <dl class="divide-y divide-line overflow-hidden rounded-[12px] border border-line bg-surface-2/60">
        <div class="flex items-center justify-between gap-4 px-4 py-3">
          <dt class="text-sm text-muted">{{ t("davomat.users.details.address") }}</dt>
          <dd class="min-w-0 truncate font-mono text-sm text-fg">{{ signInUrl }}</dd>
        </div>
        <div class="flex items-center justify-between gap-4 px-4 py-3">
          <dt class="text-sm text-muted">{{ t("davomat.users.fields.username") }}</dt>
          <dd class="min-w-0 truncate font-mono text-base font-semibold text-fg" data-username>{{ created.username }}</dd>
        </div>
        <div class="flex items-center justify-between gap-4 px-4 py-3">
          <dt class="text-sm text-muted">{{ t("davomat.users.fields.password") }}</dt>
          <dd class="min-w-0 truncate font-mono text-base font-semibold tracking-wide text-fg" data-password>{{ created.password }}</dd>
        </div>
      </dl>
      <InlineAlert tone="info" size="sm" :description="t('davomat.users.details.once')" />
    </div>

    <form v-else id="davomat-user-form" class="flex flex-col gap-5" novalidate @submit="form.submit">
      <InlineAlert v-if="form.formError.value" tone="danger" :description="form.formError.value" />

      <!-- Someone who already scans at the terminals -->
      <div v-if="creating" class="flex flex-col gap-3 rounded-[12px] border border-line bg-surface-2/50 p-3.5">
        <div class="flex items-start gap-3">
          <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-accent-soft text-accent-fg"><ScanFace :size="16" /></span>
          <ToggleSwitch v-model="fromEmployee" class="min-w-0 flex-1" layout="row" :label="t('davomat.users.fromEmployee')" :description="t('davomat.users.fromEmployeeHint')" data-from-employee />
        </div>
        <FormField v-if="fromEmployee" :label="t('davomat.users.fields.employee')" :error="form.errors.employee_id" required>
          <ComboBox
            v-model="form.values.employee_id"
            :source="employeeSource"
            :placeholder="t('davomat.users.employeePlaceholder')"
            :search-placeholder="t('davomat.users.employeePlaceholder')"
            data-field="employee"
            @update:model-value="pickEmployee"
          />
        </FormField>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('davomat.users.fields.firstName')" :error="form.errors.first_name" required>
          <TextInput v-model="form.values.first_name" autocomplete="off" :maxlength="150" @blur="form.touch('first_name')" />
        </FormField>
        <FormField :label="t('davomat.users.fields.lastName')" :error="form.errors.last_name">
          <TextInput v-model="form.values.last_name" autocomplete="off" :maxlength="150" @blur="form.touch('last_name')" />
        </FormField>
      </div>

      <FormField :label="t('davomat.users.fields.username')" :hint="t('davomat.users.usernameHint')" :error="form.errors.username" required>
        <TextInput
          v-model="form.values.username"
          mono
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          :maxlength="150"
          data-field="username"
          @input="usernameEdited = true"
          @blur="form.touch('username')"
        />
      </FormField>

      <FormField v-if="creating" :label="t('davomat.users.fields.password')" :hint="t('davomat.users.passwordHint')" :error="form.errors.password" required>
        <PasswordField v-model="form.values.password" generator :username="form.values.username" :invalid="!!form.errors.password" data-field="password" />
      </FormField>

      <InlineAlert v-if="roleLocked" tone="neutral" size="sm" :icon="isOwner ? Crown : ShieldCheck" :description="isOwner ? t('davomat.users.ownerLocked') : t('davomat.users.selfLocked')" />
      <template v-else>
        <FormField :label="t('davomat.users.fields.role')" :error="form.errors.role_id" required>
          <RadioCards v-model="form.values.role_id" :options="roleOptions" :columns="1" />
        </FormField>

        <Transition name="fade-slide">
          <FormField
            v-if="scopedRole"
            :label="t('davomat.users.fields.branches')"
            :hint="t('davomat.users.branchesHint')"
            :error="form.errors.branch_ids"
            required
          >
            <MultiSelect v-model="form.values.branch_ids" :options="branchOptions" :placeholder="t('davomat.users.branchesPlaceholder')" display="chips" />
          </FormField>
          <p v-else-if="form.values.role_id !== null" class="-mt-1 text-sm text-muted">{{ t("davomat.users.allBranchesNote") }}</p>
        </Transition>
      </template>
    </form>

    <template #footer>
      <template v-if="created">
        <UiButton variant="ghost" :icon="copied ? Check : Copy" data-copy-details @click="copyDetails">{{ copied ? t("common.copied") : t("davomat.users.details.copy") }}</UiButton>
        <UiButton variant="primary" @click="open = false">{{ t("common.done") }}</UiButton>
      </template>
      <template v-else>
        <UiButton variant="ghost" :disabled="form.submitting.value" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" type="submit" form="davomat-user-form" :loading="form.submitting.value">
          {{ user ? t("common.save") : t("davomat.users.create") }}
        </UiButton>
      </template>
    </template>
  </UiDialog>
</template>

<style scoped>
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition:
    opacity 180ms var(--ease-out),
    transform 180ms var(--ease-out);
}
.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
:root[data-motion="reduced"] .fade-slide-enter-from,
:root[data-motion="reduced"] .fade-slide-leave-to {
  transform: none;
}
</style>
