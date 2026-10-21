import { ProgressRing } from "../ui/Progress";

/** The home screen's "3/10" progress ring; empty, without numbers, while they load. */
export function Ring({ done, total, loading = false }: { done: number; total: number; loading?: boolean }) {
  return <ProgressRing value={done} total={total} label={loading ? "" : undefined} />;
}
