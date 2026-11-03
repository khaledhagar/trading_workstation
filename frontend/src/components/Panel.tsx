export function Panel({
  title,
  right,
  children,
  className = "",
  bodyClassName = "",
  testId,
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  testId?: string;
}) {
  return (
    <section
      data-testid={testId}
      className={`flex min-h-0 flex-col rounded-md border border-border bg-panel ${className}`}
    >
      <header className="flex h-8 shrink-0 items-center justify-between border-b border-border px-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">{title}</h2>
        {right}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-4 text-center text-xs text-muted">
      {children}
    </div>
  );
}
