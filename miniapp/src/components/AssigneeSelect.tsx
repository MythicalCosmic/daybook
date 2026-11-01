import type { Ref } from "react";

import { useI18n } from "../i18n";
import { haptic } from "../telegram";
import { Select } from "../ui";

export type AssigneeOption = { id: number; name: string; position: string | null };

/**
 * Who a new task is for, as the (+) sheet asks it: "Me" first, then the people this person may
 * give work to ("Alisher Valiyev · Farmatsevt"). Null is "Me". The chevron makes "Me" read as a
 * choice, not as plain text.
 */
export function AssigneeSelect({
  id,
  value,
  people,
  onChange,
  invalid,
  ref,
}: {
  id?: string;
  value: number | null;
  people: readonly AssigneeOption[];
  onChange: (assignee: number | null) => void;
  invalid?: boolean;
  /** The select itself, for a "Choose a person" that opens it. */
  ref?: Ref<HTMLSelectElement>;
}) {
  const { t } = useI18n();
  return (
    <Select
      ref={ref}
      id={id}
      value={value ?? ""}
      invalid={invalid}
      onChange={(event) => {
        haptic.select();
        onChange(event.target.value ? Number(event.target.value) : null);
      }}
    >
      <option value="">{t("add.forMe")}</option>
      {people.map((person) => (
        <option key={person.id} value={person.id}>
          {person.position ? `${person.name} · ${person.position}` : person.name}
        </option>
      ))}
    </Select>
  );
}
