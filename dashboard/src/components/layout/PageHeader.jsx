export default function PageHeader({ title, description, actions }) {
  return (
    <header className="flex shrink-0 flex-col gap-3 border-b border-surface-border/80 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div className="min-w-0">
        <h1 className="text-lg font-semibold tracking-tight text-white">{title}</h1>
        {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
