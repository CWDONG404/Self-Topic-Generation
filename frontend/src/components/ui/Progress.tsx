import { cn, clampProgress } from '../../lib/utils';

export function Progress({ value, className, label }: { value?: number; className?: string; label?: string }) {
  const progress = clampProgress(value);
  return (
    <div className={cn('space-y-2', className)}>
      {label ? (
        <div className="flex items-center justify-between text-xs font-medium text-stone-500">
          <span>{label}</span>
          <span>{Math.round(progress)}%</span>
        </div>
      ) : null}
      <div
        className="h-2 overflow-hidden rounded-full bg-stone-100"
        role="progressbar"
        aria-label={label ?? '进度'}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress)}
      >
        <div
          className="h-full rounded-full bg-pine-500 transition-[width] duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}
