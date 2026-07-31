import { AlertCircle, Inbox, LoaderCircle, RefreshCw } from 'lucide-react';
import { Button } from './Button';

export function PageLoader({ label = '正在读取资料…' }: { label?: string }) {
  return (
    <div className="flex min-h-64 items-center justify-center rounded-2xl border border-dashed border-stone-200 bg-white/50">
      <div className="flex items-center gap-3 text-sm font-medium text-stone-500">
        <LoaderCircle aria-hidden="true" className="h-5 w-5 animate-spin text-pine-600" />
        {label}
      </div>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex min-h-52 flex-col items-center justify-center rounded-2xl border border-red-100 bg-red-50/70 p-6 text-center">
      <AlertCircle aria-hidden="true" className="mb-3 h-7 w-7 text-red-500" />
      <p className="font-semibold text-red-800">暂时无法读取数据</p>
      <p className="mt-1 max-w-md text-sm leading-6 text-red-600">{message}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry}>
          <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" />
          重试
        </Button>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-52 flex-col items-center justify-center rounded-2xl border border-dashed border-stone-300 bg-white/55 p-6 text-center">
      <Inbox aria-hidden="true" className="mb-3 h-7 w-7 text-stone-400" />
      <p className="font-semibold text-ink">{title}</p>
      <p className="mt-1 max-w-md text-sm leading-6 text-stone-500">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
