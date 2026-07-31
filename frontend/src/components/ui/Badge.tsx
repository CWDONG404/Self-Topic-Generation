import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'violet';

const toneClasses: Record<Tone, string> = {
  neutral: 'bg-stone-100 text-stone-600',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-600',
  danger: 'bg-red-50 text-red-700',
  info: 'bg-sky-50 text-sky-700',
  violet: 'bg-violet-50 text-violet-700',
};

export function Badge({ className, tone = 'neutral', ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn('inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', toneClasses[tone], className)}
      {...props}
    />
  );
}
