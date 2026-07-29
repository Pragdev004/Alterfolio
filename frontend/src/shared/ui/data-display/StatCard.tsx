import { memo } from "react";

export type StatCardTone = "default" | "positive" | "negative";

type StatCardProps = {
  label: string;
  value: string;
  tone?: StatCardTone;
};

export const StatCard = memo(function StatCard({
  label,
  value,
  tone = "default",
}: StatCardProps) {
  return (
    <article className={`stat-card stat-card-${tone}`}>
      <p className="stat-card-label">{label}</p>
      <p className="stat-card-value">{value}</p>
    </article>
  );
});
