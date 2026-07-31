import type { ReactNode } from 'react';

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-7 flex flex-col justify-between gap-4 md:flex-row md:items-end">
      <div>
        {eyebrow ? <p className="mb-2 text-xs font-bold uppercase tracking-[.18em] text-pine-600">{eyebrow}</p> : null}
        <h1 className="font-display text-3xl font-semibold tracking-tight text-ink sm:text-4xl">{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-sm leading-6 text-stone-500 sm:text-base">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
