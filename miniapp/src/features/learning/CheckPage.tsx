/**
 * A regular check's entry (`check:<entry id>`, the "Start" of the check notice): the quiz intro
 * for that round, with its deadline. An entry that isn't the person's (or is long closed) is "not
 * here", like any other record that isn't theirs.
 */
import { ApiError } from "../../api/client";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { LoadError, Screen, ScreenSkeleton } from "../../ui";
import type { PageProps } from "../registry";
import { useChecks } from "./api";
import { QuizIntro } from "./QuizPage";

export default function CheckPage({ params }: PageProps) {
  const member = useMember();
  const navigation = useNavigation();
  const id = Number(params.id);
  const checks = useChecks(member.companyId);
  const entry = checks.data?.find((row) => row.entry_id === id);

  if (!entry) {
    return (
      <Screen variant="detail">
        {checks.isError || checks.data ? (
          <LoadError error={checks.error ?? new ApiError(404, null)} onRetry={() => void checks.refetch()} onBack={navigation.pop} />
        ) : (
          <ScreenSkeleton variant="detail" delay={150} />
        )}
      </Screen>
    );
  }
  return <QuizIntro quizId={entry.quiz_id} assignment={null} course={null} entry={entry.entry_id} due={entry.due_at} />;
}
