import { ProgressRing } from "../ui/Progress";

/** The home screen's "3/10" progress ring. */
export function Ring({ done, total }: { done: number; total: number }) {
  return <ProgressRing value={done} total={total} />;
}
