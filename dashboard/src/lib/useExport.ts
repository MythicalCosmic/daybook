/**
 * Server exports (plan §4.2): `POST exports/ {kind, format, params, deliver_telegram}` → 202 `{id}`;
 * the file is built in the background (`GET exports/{id}/` until `ready` or `failed`) and offered
 * for download here; it also lands in the Exports page for 7 days. It goes to Telegram only when
 * the person ticked "Also send to Telegram" (off by default, §3.5).
 */
import { ref } from "vue";

import { http, ownerPath } from "@/api/http";
import type { ExportFormat, ExportJob } from "@/api/types";
import { toast } from "@/components/useToast";
import { t } from "@/i18n";
import { useCompanyStore } from "@/stores/company";

export type { ExportFormat, ExportJob };

export interface ExportRequest {
  kind: string;
  format?: Exclude<ExportFormat, "zip">;
  params?: Record<string, unknown>;
  /** Also send the file to the person in Telegram (opt-in; never for sensitive exporters by default). */
  deliverTelegram?: boolean;
}

const POLL_MS = 1500;
const GIVE_UP_MS = 5 * 60_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function exportsApi(companyId: number) {
  return {
    create: (request: ExportRequest) =>
      http.post<{ id: number }>(ownerPath(companyId, "exports/"), {
        kind: request.kind,
        format: request.format ?? "xlsx",
        params: request.params ?? {},
        deliver_telegram: request.deliverTelegram ?? false,
      }),
    get: (id: number, signal?: AbortSignal) => http.get<ExportJob>(ownerPath(companyId, `exports/${id}/`), undefined, { signal }),
  };
}

/** Opens a ready export's signed link (valid 10 minutes; the server checks access again). */
export function downloadExport(job: Pick<ExportJob, "file_url">): void {
  if (job.file_url) window.open(job.file_url, "_blank", "noopener");
}

export function useExport() {
  const company = useCompanyStore();
  const running = ref(false);

  async function start(request: ExportRequest): Promise<ExportJob | null> {
    const companyId = company.currentId;
    if (companyId === null || running.value) return null;
    running.value = true;
    const api = exportsApi(companyId);
    const toastId = toast.info(t("common.export.preparing"), { duration: 0 });
    try {
      const { id } = await api.create(request);
      const started = Date.now();
      while (Date.now() - started < GIVE_UP_MS) {
        await sleep(POLL_MS);
        const job = await api.get(id);
        if (job.status === "ready" && job.file_url) {
          toast.success(t("common.export.ready"), {
            id: toastId,
            description: job.deliver_telegram ? t("common.export.telegram") : (job.file_name ?? undefined),
            action: { label: t("common.export.download"), onClick: () => downloadExport(job) },
            duration: 10_000,
          });
          return job;
        }
        if (job.status === "failed") {
          toast.error(t("common.export.failed"), { id: toastId, description: job.error || undefined });
          return null;
        }
      }
      toast.error(t("common.export.failed"), { id: toastId });
      return null;
    } catch {
      // The HTTP layer already showed the server's reason.
      toast.dismiss(toastId);
      return null;
    } finally {
      running.value = false;
    }
  }

  return { start, running };
}
