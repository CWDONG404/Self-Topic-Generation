import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function formatBytes(bytes?: number) {
  if (bytes == null) return '—';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function clampProgress(value?: number) {
  if (value == null || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

export function getInitials(name: string) {
  return name.trim().slice(0, 2).toUpperCase() || '知题';
}

export function toErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return '发生未知错误，请稍后重试。';
}
