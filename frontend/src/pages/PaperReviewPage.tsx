import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Play, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { CitationDrawer } from '../components/CitationDrawer';
import { PageHeader } from '../components/PageHeader';
import { QuestionReviewCard } from '../components/QuestionReviewCard';
import { StatusBadge } from '../components/StatusBadge';
import { Button } from '../components/ui/Button';
import { ErrorState, EmptyState, PageLoader } from '../components/ui/States';
import { api } from '../lib/api';
import { toErrorMessage } from '../lib/utils';
import type { CitationAnchor } from '../types/api';

export function PaperReviewPage() {
  const { paperId = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [citation, setCitation] = useState<CitationAnchor | null>(null);
  const paper = useQuery({ queryKey: ['paper', paperId], queryFn: () => api.getPaper(paperId), enabled: Boolean(paperId) });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['paper', paperId] });
  const action = useMutation({
    mutationFn: ({ kind, id, payload }: { kind: 'save' | 'review' | 'regenerate' | 'disable'; id: string; payload?: Record<string, unknown> }) => {
      if (kind === 'save') return api.updateQuestion(id, payload ?? {});
      if (kind === 'review') return api.reviewQuestion(id);
      if (kind === 'regenerate') return api.regenerateQuestion(id);
      return api.disableQuestion(id);
    },
    onSuccess: () => { toast.success('题目已更新'); refresh(); },
    onError: (error) => toast.error(toErrorMessage(error)),
  });
  const start = useMutation({
    mutationFn: () => api.createPracticeSession(paperId, 'practice'),
    onSuccess: (session) => navigate(`/practice/${session.id}`),
    onError: (error) => toast.error(toErrorMessage(error)),
  });
  if (paper.isLoading) return <PageLoader label="正在读取试卷…" />;
  if (paper.error || !paper.data) return <ErrorState message={toErrorMessage(paper.error ?? new Error('试卷不存在'))} onRetry={() => void paper.refetch()} />;
  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="题目复核"
        title={paper.data.title}
        description={`共 ${paper.data.question_count} 题。AI 审查通过的题可直接练习，也可人工编辑并重新审查。`}
        actions={<><StatusBadge status={paper.data.status} /><Button onClick={() => start.mutate()} loading={start.isPending}><Play className="h-4 w-4" />开始练习</Button></>}
      />
      <div className="mb-5 flex items-center gap-2 rounded-xl border border-pine-100 bg-pine-50 p-4 text-sm text-pine-700"><ShieldCheck className="h-4 w-4 shrink-0" />点击任一“出处”即可在侧边定位原文；PDF 会跳转到对应页并叠加高亮框。</div>
      {paper.data.questions?.length ? (
        <div className="space-y-5">
          {paper.data.questions.map((question, index) => (
            <QuestionReviewCard
              key={question.id}
              question={question}
              index={index}
              onCitation={setCitation}
              busy={action.isPending}
              onSave={(payload) => action.mutate({ kind: 'save', id: question.id, payload: payload as Record<string, unknown> })}
              onReview={() => action.mutate({ kind: 'review', id: question.id })}
              onRegenerate={() => action.mutate({ kind: 'regenerate', id: question.id })}
              onDisable={() => action.mutate({ kind: 'disable', id: question.id })}
            />
          ))}
        </div>
      ) : <EmptyState title="试卷里还没有题目" description="生成任务可能仍在运行，或当前资料证据不足。" />}
      <CitationDrawer citation={citation} open={Boolean(citation)} onOpenChange={(open) => { if (!open) setCitation(null); }} />
    </div>
  );
}
