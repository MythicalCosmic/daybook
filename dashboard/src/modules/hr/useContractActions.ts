/**
 * Running a contract action from anywhere (the overview's one-tap buttons, the table's menu, the
 * contract drawer): the simple ones ask "are you sure" and go; renew, terminate and extend
 * probation open ContractActionDialog for their date (and reason). The host renders the dialog
 * with `v-model:request`.
 */
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import type { PersonRef } from "@/api/types";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";

import { hrApi, useHrMutation } from "./api";
import { ACTION_ICONS } from "./icons";
import type { Contract, ContractAction, ContractKind } from "./types";

/** What an action needs to know about the contract (overview rows carry only this much). */
export interface ContractRef {
  id: number;
  member: PersonRef;
  kind?: ContractKind;
  starts_on?: string;
  ends_on?: string | null;
  probation_until?: string | null;
}

export type DialogAction = "renew" | "terminate" | "extend-probation";
export interface ActionRequest {
  contract: ContractRef;
  action: DialogAction;
}

const DIALOG_ACTIONS: readonly ContractAction[] = ["renew", "terminate", "extend-probation"];

export function useContractActions(onDone?: (contract: Contract) => void) {
  const { t } = useI18n();
  const confirm = useConfirm();
  const request = ref<ActionRequest | null>(null);
  const mutation = useHrMutation((cid, input: { id: number; action: ContractAction; payload?: Record<string, unknown> }) =>
    hrApi.contractAction(cid, input.id, input.action, input.payload),
  );

  async function perform(contract: ContractRef, action: ContractAction, payload?: Record<string, unknown>): Promise<Contract | null> {
    try {
      const result = await mutation.mutateAsync({ id: contract.id, action, payload });
      toast.success(t(`hr.contract.done.${action}`, { name: contract.member.name }));
      onDone?.(result);
      return result;
    } catch {
      // The HTTP layer showed the server's reason.
      return null;
    }
  }

  async function run(contract: ContractRef, action: ContractAction): Promise<void> {
    if (DIALOG_ACTIONS.includes(action)) {
      request.value = { contract, action: action as DialogAction };
      return;
    }
    const answer = await confirm({
      title: t(`hr.contract.confirm.${action}.title`, { name: contract.member.name }),
      message: t(`hr.contract.confirm.${action}.body`),
      confirmLabel: t(`hr.contract.action.${action}`),
      icon: ACTION_ICONS[action],
    });
    if (answer) await perform(contract, action);
  }

  return { request, run, perform, pending: mutation.isPending };
}
