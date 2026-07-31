import { useMutation, useQuery } from '@tanstack/react-query';
import { Calendar, FileCheck2, Play, Shield, Sparkles } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { Badge } from '../components/ui/Badge';
import { Button, buttonVariants } from '../components/ui/Button';
import { Card, CardBody } from '../components/ui/Card';
import { ErrorState, EmptyState, PageLoader } from '../components/ui/States';
import { api } from '../lib/api';
import { cn, formatDate, toErrorMessage } from '../lib/utils';

export function PapersPage() {
  const navigate = useNavigate();
  const papers = useQuery({ queryKey: ['papers'], queryFn: api.listPapers });
  const start = useMutation({
    mutationFn: ({ paperId, mode }: { paperId: string; mode: 'practice' | 'exam' }) => api.createPracticeSession(paperId, mode),
    onSuccess: (session) => navigate(`/practice/${session.id}`),
    onError: (error) => toast.error(toErrorMessage(error)),
  });
  if (papers.isLoading) return <PageLoader label="正在整理模拟卷…" />;
  if (papers.error) return <ErrorState message={toErrorMessage(papers.error)} onRetry={() => void papers.refetch()} />;
  return (
    <div className="animate-fade-in">
      <PageHeader eyebrow="试卷中心" title="模拟卷" description="复核每一道题，或直接进入练习与考试模式。" actions={<Link to="/generate" className={buttonVariants()}><Sparkles className="h-4 w-4" />新建试卷</Link>} />
      {papers.data?.length ? (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {papers.data.map((paper) => (
            <Card key={paper.id} className="flex flex-col overflow-hidden transition hover:-translate-y-0.5 hover:border-stone-300">
              <CardBody className="flex flex-1 flex-col">
                <div className="flex items-start justify-between gap-3">
                  <span className="grid h-11 w-11 place-items-center rounded-xl bg-pine-50 text-pine-700"><FileCheck2 className="h-5 w-5" /></span>
                  <StatusBadge status={paper.status} />
                </div>
                <Link to={`/papers/${paper.id}`} className="mt-5 line-clamp-2 text-lg font-bold leading-7 text-ink hover:text-pine-700">{paper.title}</Link>
                <p className="mt-2 line-clamp-2 min-h-10 text-sm leading-5 text-stone-400">{paper.source_summary || '由权威正文生成并保留逐题出处。'}</p>
                <div className="mt-5 flex flex-wrap gap-2"><Badge tone="info">{paper.question_count} 题</Badge><Badge tone="success"><Shield className="mr-1 h-3 w-3" />AI 已审查</Badge></div>
                <p className="mt-4 flex items-center gap-1.5 text-xs text-stone-400"><Calendar className="h-3.5 w-3.5" />{formatDate(paper.created_at)}</p>
                <div className="mt-5 grid grid-cols-2 gap-2 border-t border-stone-100 pt-4">
                  <Button variant="secondary" onClick={() => start.mutate({ paperId: paper.id, mode: 'practice' })} disabled={start.isPending}><Play className="h-4 w-4" />练习</Button>
                  <Button onClick={() => start.mutate({ paperId: paper.id, mode: 'exam' })} disabled={start.isPending}>模拟考试</Button>
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      ) : <EmptyState title="还没有模拟卷" description="选择重点和正文资料，创建第一套可追溯试卷。" action={<Link to="/generate" className={cn(buttonVariants(), 'inline-flex')}>开始出题</Link>} />}
    </div>
  );
}
