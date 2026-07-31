import { useMutation, useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  BookOpenText,
  CheckCircle2,
  Clock3,
  FileCheck2,
  FilePlus2,
  Layers3,
  Play,
  Sparkles,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { Button, buttonVariants } from '../components/ui/Button';
import { Card, CardBody } from '../components/ui/Card';
import { ErrorState, EmptyState, PageLoader } from '../components/ui/States';
import { api } from '../lib/api';
import { cn, formatDate, toErrorMessage } from '../lib/utils';
import type { Job } from '../types/api';

function jobSummary(job: Job) {
  if (job.status === 'completed') return '模拟卷生成完成';
  if (job.status === 'partial') return '模拟卷部分完成';
  if (job.status === 'cancelled') return '任务已取消';
  if (job.status === 'failed') {
    if (/ReadTimeout|timed?\s*out|超时/i.test(job.error || '')) return '模型响应超时，可重试';
    if (/UniqueViolation|duplicate key/i.test(job.error || '')) return '结果保存冲突';
    return '生成任务失败';
  }
  const stages: Record<string, string> = {
    validating: '正在校验资料与模型',
    blueprint: '正在规划考点蓝图',
    retrieval: '正在检索正文证据',
    authoring: '正在生成候选题',
    reviewing: '正在独立审题',
    finalizing: '正在组装模拟卷',
    queued: '等待后台处理',
    running: '正在生成模拟卷',
  };
  return stages[job.stage] || '正在处理生成任务';
}

export function DashboardPage() {
  const navigate = useNavigate();
  const libraries = useQuery({ queryKey: ['libraries'], queryFn: api.listLibraries });
  const documents = useQuery({ queryKey: ['documents'], queryFn: () => api.listDocuments() });
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: api.listJobs, refetchInterval: 10_000 });
  const papers = useQuery({ queryKey: ['papers'], queryFn: api.listPapers });
  const practice = useMutation({
    mutationFn: (paperId: string) => api.createPracticeSession(paperId, 'practice'),
    onSuccess: (session) => navigate(`/practice/${session.id}`),
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const isLoading = libraries.isLoading || documents.isLoading || jobs.isLoading || papers.isLoading;
  const error = libraries.error || documents.error || jobs.error || papers.error;
  const retry = () => {
    void libraries.refetch();
    void documents.refetch();
    void jobs.refetch();
    void papers.refetch();
  };

  if (isLoading) return <PageLoader label="正在整理你的知识工作台…" />;
  if (error) return <ErrorState message={toErrorMessage(error)} onRetry={retry} />;

  const readyDocs = documents.data?.filter((item) => item.status === 'ready').length ?? 0;
  const completedPapers = papers.data?.filter((item) => ['ready', 'partial'].includes(item.status)).length ?? 0;
  const runningJobs = jobs.data?.filter((item) => ['queued', 'running'].includes(item.status)).length ?? 0;
  const recentPapers = [...(papers.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4);
  const recentJobs = [...(jobs.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4);

  return (
    <div className="animate-fade-in">
      <PageHeader eyebrow="个人知识训练场" title="把资料读懂，再把重点练熟。" />

      <section className="subtle-grid relative overflow-hidden rounded-3xl bg-pine-900 p-6 text-white shadow-card sm:p-9 lg:p-11">
        <div className="relative z-10 max-w-2xl">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-semibold text-pine-100">
            <Sparkles aria-hidden="true" className="h-3.5 w-3.5" />
            AI 出题 · 独立审查 · 原文溯源
          </div>
          <h2 className="font-display text-3xl font-semibold leading-tight sm:text-5xl">
            从一摞复习资料，
            <br className="hidden sm:block" />
            到一套有据可查的模拟卷。
          </h2>
          <p className="mt-4 max-w-xl text-sm leading-7 text-pine-100/80 sm:text-base">
            重点资料告诉 AI 考什么，权威正文保证每个答案有出处。生成、审查、练习都在一个地方完成。
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link to="/generate" className={cn(buttonVariants({ size: 'lg' }), 'bg-white text-pine-900 hover:bg-pine-50')}>
              <FilePlus2 aria-hidden="true" className="h-4 w-4" />
              新建模拟卷
            </Link>
            <Link
              to="/knowledge"
              className={cn(buttonVariants({ variant: 'ghost', size: 'lg' }), 'border border-white/20 text-white hover:bg-white/10 hover:text-white')}
            >
              管理资料
              <ArrowRight aria-hidden="true" className="h-4 w-4" />
            </Link>
          </div>
        </div>
        <div aria-hidden="true" className="absolute -bottom-24 -right-16 h-80 w-80 rounded-full border-[48px] border-pine-500/20" />
        <div aria-hidden="true" className="absolute right-20 top-10 h-16 w-16 rotate-12 rounded-2xl border border-white/10 bg-white/5" />
      </section>

      <section aria-label="概览数据" className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: '资料库', value: libraries.data?.length ?? 0, detail: '个知识空间', icon: Layers3, color: 'bg-pine-50 text-pine-700' },
          { label: '就绪资料', value: readyDocs, detail: `共 ${documents.data?.length ?? 0} 份文档`, icon: BookOpenText, color: 'bg-sky-50 text-sky-700' },
          { label: '可用试卷', value: completedPapers, detail: '均已完成 AI 审查', icon: FileCheck2, color: 'bg-violet-50 text-violet-700' },
          { label: '运行任务', value: runningJobs, detail: runningJobs ? '正在后台处理' : '当前没有排队', icon: Clock3, color: 'bg-amber-50 text-amber-600' },
        ].map(({ label, value, detail, icon: Icon, color }) => (
          <Card key={label}>
            <CardBody className="flex items-center gap-4 p-4 sm:p-5">
              <div className={cn('grid h-11 w-11 shrink-0 place-items-center rounded-xl', color)}>
                <Icon aria-hidden="true" className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs font-semibold text-stone-500">{label}</p>
                <p className="mt-0.5 text-2xl font-bold tracking-tight text-ink">{value}</p>
                <p className="text-xs text-stone-400">{detail}</p>
              </div>
            </CardBody>
          </Card>
        ))}
      </section>

      <div className="mt-8 grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <section aria-labelledby="recent-papers-title" className="min-w-0">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="recent-papers-title" className="text-lg font-bold text-ink">最近试卷</h2>
            <Link to="/papers" className="text-sm font-semibold text-pine-600 hover:text-pine-700">查看全部</Link>
          </div>
          {recentPapers.length ? (
            <div className="space-y-3">
              {recentPapers.map((paper) => (
                <Card key={paper.id} className="transition hover:border-stone-300">
                  <CardBody className="flex flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center sm:p-5">
                    <div className="flex min-w-0 items-center gap-4">
                      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-stone-100 text-stone-600">
                        <FileCheck2 aria-hidden="true" className="h-5 w-5" />
                      </span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link to={`/papers/${paper.id}`} className="truncate font-semibold text-ink hover:text-pine-700">{paper.title}</Link>
                          <StatusBadge status={paper.status} />
                        </div>
                        <p className="mt-1 text-xs text-stone-400">{paper.question_count} 题 · {formatDate(paper.created_at)}</p>
                      </div>
                    </div>
                    <Button
                      className="shrink-0 whitespace-nowrap"
                      variant="secondary"
                      size="sm"
                      onClick={() => practice.mutate(paper.id)}
                      loading={practice.isPending}
                    >
                      <Play aria-hidden="true" className="h-3.5 w-3.5" />
                      开始练习
                    </Button>
                  </CardBody>
                </Card>
              ))}
            </div>
          ) : (
            <EmptyState
              title="还没有模拟卷"
              description="准备好资料后，创建第一套可追溯的模拟卷。"
              action={<Link to="/generate" className={buttonVariants({ size: 'sm' })}>创建试卷</Link>}
            />
          )}
        </section>

        <section aria-labelledby="recent-jobs-title" className="min-w-0">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="recent-jobs-title" className="text-lg font-bold text-ink">任务动态</h2>
            <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-stone-400" />
          </div>
          <Card className="min-w-0 overflow-hidden">
            <CardBody className="min-w-0 p-2">
              {recentJobs.length ? (
                <ul className="divide-y divide-stone-100">
                  {recentJobs.map((job) => (
                    <li key={job.id}>
                      <Link
                        to={`/jobs/${job.id}`}
                        className="flex min-w-0 items-center justify-between gap-3 overflow-hidden rounded-xl px-3 py-3 transition hover:bg-stone-50"
                        title={job.error || job.message || undefined}
                      >
                        <div className="min-w-0 flex-1 overflow-hidden">
                          <p className="truncate text-sm font-semibold text-ink">{jobSummary(job)}</p>
                          <p className="mt-1 text-xs text-stone-400">{formatDate(job.created_at)}</p>
                        </div>
                        <span className="shrink-0"><StatusBadge status={job.status} /></span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="py-12 text-center text-sm text-stone-400">暂无任务记录</div>
              )}
            </CardBody>
          </Card>
        </section>
      </div>
    </div>
  );
}
