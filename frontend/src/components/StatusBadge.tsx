import { Badge } from './ui/Badge';

const labels: Record<string, string> = {
  queued: '等待中',
  parsing: '解析中',
  running: '生成中',
  cancelling: '取消中',
  ready: '已就绪',
  completed: '已完成',
  partial: '部分完成',
  warning: '有提示',
  failed: '失败',
  cancelled: '已取消',
  archived: '已归档',
  draft: '草稿',
  passed: '审查通过',
  pending: '待审查',
  needs_revision: '需返修',
  in_progress: '答题中',
  submitted: '已交卷',
};

const tones: Record<string, React.ComponentProps<typeof Badge>['tone']> = {
  queued: 'neutral',
  parsing: 'info',
  running: 'info',
  cancelling: 'warning',
  ready: 'success',
  completed: 'success',
  passed: 'success',
  partial: 'warning',
  warning: 'warning',
  needs_revision: 'warning',
  failed: 'danger',
  cancelled: 'neutral',
  archived: 'neutral',
  draft: 'neutral',
  pending: 'neutral',
  in_progress: 'info',
  submitted: 'success',
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={tones[status] ?? 'neutral'}>{labels[status] ?? status}</Badge>;
}
