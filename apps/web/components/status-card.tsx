type Props = {
  label: string;
  value: string;
  tone: "checking" | "online" | "unavailable";
};

export function StatusCard({ label, value, tone }: Props) {
  const colors = {
    checking: "bg-amber-300",
    online: "bg-emerald-300",
    unavailable: "bg-rose-300",
  };
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-xl shadow-black/10">
      <div className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">{label}</div>
      <div className="flex items-center gap-3 text-lg font-medium">
        <span className={`h-2.5 w-2.5 rounded-full ${colors[tone]}`} aria-hidden />
        {value}
      </div>
    </div>
  );
}

