import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  BookOpenCheck,
  BrainCircuit,
  Check,
  CheckCircle2,
  Circle,
  FileSearch,
  ListChecks,
  LoaderCircle,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { Badge } from '../components/ui/Badge';
import { Button, buttonVariants } from '../components/ui/Button';
import { Card, CardBody, CardHeader } from '../components/ui/Card';
import { ErrorState, PageLoader } from '../components/ui/States';
import { api, subscribeToJobEvents } from '../lib/api';
import { cn, clampProgress, formatDate, toErrorMessage } from '../lib/utils';
import type { JobEvent } from '../types/api';

const stages = [
  { keys: ['validating', 'validation'], label: '校验配置', icon: ListChecks, description: '检查资料、配额与模型能力' },
  { keys: ['blueprint', 'planning'], label: '理解考点', icon: BrainCircuit, description: '重点蓝图 Agent 正在映射正文' },
  { keys: ['retrieval', 'retrieving', 'evidence'], label: '检索证据', icon: FileSearch, description: '为每个考点寻找可靠原文' },
  { keys: ['generating', 'generation'], label: '生成候选题', icon: Sparkles, description: '出题 Agent 根据证据编写题目' },
  { keys: ['reviewing', 'review'], label: '独立审题', icon: ShieldCheck, description: '审题 Agent 独立作答并核对解析' },
  { keys: ['deduplicating', 'dedupe'], label: '去重补题', icon: SearchCheck, description: '拒绝重复并补足文档配额' },
  { keys: ['assembling', 'completed', 'complete'], label: '组装试卷', icon: BookOpenCheck, description: '保存引用、随机种子与审查记录' },
];

function stageIndex(stage: string) {
  const normalized = stage.toLowerCase();
  return stages.findIndex((item) => item.keys.some((key) => normalized.includes(key)));
}

export function JobPage() {
  const { jobId = '' } = useParams();
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [streamInterrupted, setStreamInterrupted] = useState(false);
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.getJob(jobId),
    enabled: Boolean(jobId),
    refetchInterval: (query) => ['queued', 'running', 'cancelling'].includes(query.state.data?.status ?? '') ? 8_000 : false,
  });

  useEffect(() => {
    if (!jobId || !['queued', 'running', 'cancelling'].includes(job.data?.status ?? '')) return;
    const unsubscribe = subscribeToJobEvents(jobId, {
      onEvent: (event) => {
        setStreamInterrupted(false);
        setEvents((current) => {
          if (current.some((item) => item.sequence === event.sequence)) return current;
          return [...current, event].sort((a, b) => a.sequence - b.sequence).slice(-100);
        });
        void queryClient.invalidateQueries({ queryKey: ['job', jobId] });
      },
      onError: () => setStreamInterrupted(true),
    });
    return unsubscribe;
  }, [jobId, job.data?.status, queryClient]);

  const cancel = useMutation({
    mutationFn: () => api.cancelJob(jobId),
    onSuccess: () => { toast.success('已提交取消请求'); void job.refetch(); },
    onError: (error) => toast.error(toErrorMessage(error)),
  });
  const retry = useMutation({
    mutationFn: () => api.retryJob(jobId),
    onSuccess: (nextJob) => { toast.success('任务已重新进入队列'); window.location.assign(`/jobs/${nextJob.id}`); },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const current = events.at(-1);
  const displayStage = current?.stage ?? job.data?.stage ?? 'queued';
  const progress = Math.max(clampProgress(job.data?.progress), clampProgress(current?.progress));
  const counts = { ...(job.data?.counts ?? {}), ...(current?.counts ?? {}) };
  const activeIndex = useMemo(() => stageIndex(displayStage), [displayStage]);

  if (job.isLoading) return <PageLoader label="正在连接任务…" />;
  if (job.error || !job.data) return <ErrorState message={toErrorMessage(job.error ?? new Error('任务不存在'))} onRetry={() => void job.refetch()} />;
  const terminal = ['completed', 'partial', 'failed', 'cancelled'].includes(job.data.status);

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="后台任务"
        title={terminal ? '生成任务结果' : '正在锻造这套试卷'}
        description={job.data.message || current?.message || '页面可以安全刷新；任务状态和检查点都保存在服务端。'}
        actions={
          <>
            <StatusBadge status={job.data.status} />
            {!terminal && job.data.status !== 'cancelling' ? (
              <Button variant="secondary" onClick={() => cancel.mutate()} loading={cancel.isPending}>
                <Ban aria-hidden="true" className="h-4 w-4" />取消任务
              </Button>
            ) : null}
          </>
        }
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="space-y-5">
          <Card className="overflow-hidden">
            <div className="subtle-grid bg-pine-900 p-6 text-white sm:p-8">
              <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[.16em] text-pine-100/70">实时进度</p>
                  <p className="mt-2 font-display text-3xl font-semibold sm:text-4xl">{Math.round(progress)}%</p>
                  <p className="mt-2 text-sm text-pine-100/70">{current?.message || job.data.message || stages[Math.max(activeIndex, 0)]?.description || '准备任务环境'}</p>
                </div>
                {!terminal ? <LoaderCircle aria-hidden="true" className="h-8 w-8 animate-spin text-pine-100/60" /> : <CheckCircle2 aria-hidden="true" className="h-9 w-9 text-pine-100" />}
              </div>
              <div className="mt-6 h-3 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-white transition-[width] duration-700"
                  role="progressbar"
                  aria-label="出题总进度"
                  aria-valuenow={Math.round(progress)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  style={{ width: `${progress}%` }}
                />
              </div>
              {streamInterrupted && !terminal ? <p className="mt-3 text-xs text-amber-100">实时连接正在重试，页面仍会定时同步任务状态。</p> : null}
            </div>
            <CardBody>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  ['目标', counts.target ?? job.data.request?.question_count ?? 0],
                  ['已通过', counts.accepted ?? 0],
                  ['已驳回', counts.rejected ?? 0],
                  ['已返修', counts.revised ?? 0],
                ].map(([label, value]) => (
                  <div key={String(label)} className="rounded-xl bg-stone-50 px-3 py-4 text-center">
                    <p className="text-2xl font-bold tracking-tight text-ink">{value}</p>
                    <p className="mt-1 text-xs text-stone-400">{label}</p>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader><h2 className="font-bold text-ink">工作流阶段</h2></CardHeader>
            <CardBody>
              <ol className="space-y-1">
                {stages.map((stage, index) => {
                  const done = terminal && job.data.status === 'completed' ? true : index < activeIndex;
                  const active = !terminal && index === Math.max(activeIndex, 0);
                  const Icon = stage.icon;
                  return (
                    <li key={stage.label} className="relative flex gap-4 pb-5 last:pb-0">
                      {index < stages.length - 1 ? <span aria-hidden="true" className={cn('absolute left-[17px] top-9 h-[calc(100%-1.25rem)] w-px', done ? 'bg-pine-300' : 'bg-stone-200')} /> : null}
                      <span className={cn('relative z-10 grid h-9 w-9 shrink-0 place-items-center rounded-full border', done ? 'border-pine-500 bg-pine-500 text-white' : active ? 'border-pine-400 bg-pine-50 text-pine-700' : 'border-stone-200 bg-white text-stone-300')}>
                        {done ? <Check className="h-4 w-4" /> : active ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}
                      </span>
                      <div className="pt-1.5">
                        <p className={cn('text-sm font-bold', done || active ? 'text-ink' : 'text-stone-400')}>{stage.label}</p>
                        <p className="mt-0.5 text-xs leading-5 text-stone-400">{stage.description}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </CardBody>
          </Card>

          {job.data.warnings?.length || current?.warning || job.data.error ? (
            <Card className="border-amber-200 bg-amber-50/70">
              <CardBody>
                <div className="flex items-start gap-3">
                  <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
                  <div>
                    <h2 className="text-sm font-bold text-amber-700">任务提示</h2>
                    <ul className="mt-2 space-y-1 text-xs leading-5 text-amber-600">
                      {job.data.error ? <li>{job.data.error}</li> : null}
                      {current?.warning ? <li>{current.warning}</li> : null}
                      {job.data.warnings?.map((warning) => <li key={warning}>{warning}</li>)}
                    </ul>
                  </div>
                </div>
              </CardBody>
            </Card>
          ) : null}
        </div>

        <aside className="space-y-4 xl:sticky xl:top-8">
          <Card>
            <CardHeader><h2 className="text-sm font-bold text-ink">任务信息</h2></CardHeader>
            <CardBody>
              <dl className="space-y-3 text-sm">
                <div className="flex justify-between gap-3"><dt className="text-stone-400">任务编号</dt><dd className="max-w-32 truncate font-mono text-xs text-stone-600" title={job.data.id}>{job.data.id}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-stone-400">创建时间</dt><dd className="font-medium text-ink">{formatDate(job.data.created_at)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-stone-400">开始时间</dt><dd className="font-medium text-ink">{formatDate(job.data.started_at)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-stone-400">随机种子</dt><dd className="font-mono text-xs text-ink">{job.data.request?.random_seed ?? '自动'}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-stone-400">执行模式</dt><dd><Badge tone={job.data.request?.execution_mode === 'local_only' ? 'success' : 'info'}>{job.data.request?.execution_mode === 'local_only' ? '仅本地' : '云端可用'}</Badge></dd></div>
              </dl>
            </CardBody>
          </Card>

          {job.data.status === 'completed' || job.data.status === 'partial' ? (
            job.data.paper_id ? (
              <Link to={`/papers/${job.data.paper_id}`} className={cn(buttonVariants({ size: 'lg' }), 'w-full')}>
                查看并复核试卷<ArrowRight className="h-4 w-4" />
              </Link>
            ) : null
          ) : null}
          {['failed', 'cancelled'].includes(job.data.status) ? (
            <Button className="w-full" size="lg" onClick={() => retry.mutate()} loading={retry.isPending}>
              <RefreshCw className="h-4 w-4" />重新运行
            </Button>
          ) : null}
          {!terminal ? (
            <div className="flex items-center gap-2 rounded-xl border border-stone-200 bg-white px-4 py-3 text-xs leading-5 text-stone-500">
              <Circle aria-hidden="true" className="h-2.5 w-2.5 fill-pine-500 text-pine-500" />
              可离开此页面，后台任务不会中断。
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
