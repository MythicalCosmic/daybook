/**
 * Server exports (plan §4.2): `POST exports/ {kind, format, params, deliver_telegram}` → 202 `{id}`;
 * the file is built in the background and offered for download here. It is also sent to Telegram
 * only when the person ticked "Also send to Telegram" (off by default, §3.5).
 */
import { ref } from "vue";

import { http, ownerPath } from "@/api/http";
import { toast } from "@/components/useToast";
import { t } from "@/i18n";
import { useCompanyStore } from "@/stores/company";

export type ExportFormat = "xlsx" | "csv";

export interface ExportJob {
  id: number;
  kind: string;
  format: ExportFormat;
  status: "pending" | "running" | "ready" | "failed";
  rows: number | null;
  file_url: string | null;
  error?: string;
}

export interface ExportRequest {
  kind: string;
  format?: ExportFormat;
  params?: Record<string, unknown>;
  /** Also send the file to the person in Telegram (opt-in; never for sensitive exporters by default). */
  deliverTelegram?: boolean;
}

const POLL_MS = 1500;
const GIVE_UP_MS = 5 * 60_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function useExport() {
  const company = useCompanyStore();
  const running = ref(false);

  async function start(request: ExportRequest): Promise<ExportJob | null> {
    const companyId = company.currentId;
    if (companyId === null || running.value) return null;
    running.value = true;
    const toastId = toast.info(t("common.export.preparing"), { duration: 0 });
    try {
      const { id } = await http.post<{ id: number }>(ownerPath(companyId, "exports/"), {
        kind: request.kind,
        format: request.format ?? "xlsx",
        params: request.params ?? {},
        deliver_telegram: request.deliverTelegram ?? false,
      });
      const started = Date.now();
      while (Date.now() - started < GIVE_UP_MS) {
        await sleep(POLL_MS);
        const job = await http.get<ExportJob>(ownerPath(companyId, `exports/${id}/`));
        if (job.status === "ready" && job.file_url) {
          const url = job.file_url;
          toast.success(t("common.export.ready"), {
            id: toastId,
            description: request.deliverTelegram ? t("common.export.telegram") : undefined,
            action: {
              label: t("common.export.download"),
              onClick: () => {
                window.open(url, "_blank", "noopener");
              },
            },
            duration: 10_000,
          });
          return job;
        }
        if (job.status === "failed") break;
      }
      toast.error(t("common.export.failed"), { id: toastId });
      return null;
    } catch {
      toast.dismiss(toastId);
      return null;
    } finally {
      running.value = false;
    }
  }

  return { start, running };
}
