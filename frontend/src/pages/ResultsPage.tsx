import { useMutation, useQuery } from '@tanstack/react-query';
import { BookOpen, CheckCircle2, Home, RotateCcw, Target, XCircle } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { CitationDrawer } from '../components/CitationDrawer';
import { PageHeader } from '../components/PageHeader';
import { Badge } from '../components/ui/Badge';
import { Button, buttonVariants } from '../components/ui/Button';
import { Card, CardBody } from '../components/ui/Card';
import { ErrorState, PageLoader } from '../components/ui/States';
import { Progress } from '../components/ui/Progress';
import { api } from '../lib/api';
import { toErrorMessage } from '../lib/utils';
import type { CitationAnchor } from '../types/api';

export function ResultsPage() {
  const { sessionId = '' } = useParams();
  const navigate = useNavigate();
  const [citation, setCitation] = useState<CitationAnchor | null>(null);
  const session = useQuery({ queryKey: ['practice-session', sessionId], queryFn: () => api.getPracticeSession(sessionId), enabled: Boolean(sessionId) });
  const retryWrong = useMutation({
    mutationFn: () => api.retryPracticeMistakes(sessionId),
    onSuccess: (next) => navigate(`/practice/${next.id}`),
    onError: (error) => toast.error(toErrorMessage(error)),
  });
  const wrongQuestions = useMemo(() => {
    if (!session.data?.paper?.questions) return [];
    const answerMap = new Map(session.data.answers.map((item) => [item.question_id, item]));
    return session.data.paper.questions.filter((question) => answerMap.get(question.id)?.selected_answer !== question.correct_answer);
  }, [session.data]);
  if (session.isLoading) return <PageLoader label="正在计算成绩…" />;
  if (session.error || !session.data) return <ErrorState message={toErrorMessage(session.error ?? new Error('结果不存在'))} onRetry={() => void session.refetch()} />;
  const result = session.data.result;
  if (!result) return <ErrorState message="本次练习尚未交卷，暂时没有成绩。" />;
  const answerMap = new Map(session.data.answers.map((item) => [item.question_id, item.selected_answer]));
  return (
    <div className="animate-fade-in">
      <PageHeader eyebrow="练习结果" title="这次练到哪里了？" description={session.data.paper?.title} actions={<Link to="/" className={buttonVariants({ variant: 'secondary' })}><Home className="h-4 w-4" />返回总览</Link>} />
      <Card className="overflow-hidden">
        <div className="subtle-grid bg-pine-900 p-7 text-white sm:p-10">
          <div className="grid gap-8 lg:grid-cols-[15rem_1fr] lg:items-center">
            <div className="mx-auto grid h-44 w-44 place-items-center rounded-full border-[14px] border-white/15 bg-white/5 text-center">
              <div><p className="font-display text-5xl font-semibold">{Math.round(result.score)}</p><p className="mt-1 text-xs font-bold uppercase tracking-[.18em] text-pine-100/70">得分</p></div>
            </div>
            <div>
              <h2 className="font-display text-3xl font-semibold">{result.score >= 80 ? '掌握得不错，继续保持。' : result.score >= 60 ? '基础已经形成，错题值得再练。' : '先从错题出处开始补齐知识。'}</h2>
              <div className="mt-6 grid grid-cols-3 gap-3">
                <div className="rounded-xl bg-white/10 p-4"><CheckCircle2 className="h-4 w-4 text-emerald-300" /><p className="mt-3 text-2xl font-bold">{result.correct_count}</p><p className="text-xs text-pine-100/60">正确</p></div>
                <div className="rounded-xl bg-white/10 p-4"><XCircle className="h-4 w-4 text-red-300" /><p className="mt-3 text-2xl font-bold">{result.incorrect_count}</p><p className="text-xs text-pine-100/60">错误</p></div>
                <div className="rounded-xl bg-white/10 p-4"><Target className="h-4 w-4 text-amber-300" /><p className="mt-3 text-2xl font-bold">{result.unanswered_count}</p><p className="text-xs text-pine-100/60">未答</p></div>
              </div>
            </div>
          </div>
        </div>
      </Card>

      {result.knowledge_points?.length ? (
        <section className="mt-6"><h2 className="mb-3 text-lg font-bold text-ink">知识点表现</h2><Card><CardBody className="grid gap-4 md:grid-cols-2">{result.knowledge_points.map((item) => <div key={item.name}><div className="mb-1 flex justify-between gap-3 text-xs"><span className="font-semibold text-ink">{item.name}</span><span className="text-stone-400">{item.correct}/{item.total}</span></div><Progress value={(item.correct / item.total) * 100} /></div>)}</CardBody></Card></section>
      ) : null}

      <section className="mt-7">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-bold text-ink">错题与未答题</h2>{wrongQuestions.length ? <Button onClick={() => retryWrong.mutate()} loading={retryWrong.isPending}><RotateCcw className="h-4 w-4" />重练本次错题</Button> : null}</div>
        {wrongQuestions.length ? <div className="space-y-4">{wrongQuestions.map((question, index) => <Card key={question.id}><CardBody><div className="flex flex-wrap gap-2"><Badge tone="danger">第 {index + 1} 题</Badge><Badge>{question.knowledge_point}</Badge></div><h3 className="mt-3 font-bold leading-7 text-ink">{question.stem}</h3><div className="mt-3 flex flex-wrap gap-3 text-sm"><span className="text-red-600">你的答案：{answerMap.get(question.id) || '未答'}</span><span className="font-bold text-pine-700">正确答案：{question.correct_answer}</span></div><p className="mt-3 rounded-xl bg-stone-50 p-4 text-sm leading-7 text-stone-600">{question.explanation}</p><div className="mt-3 flex flex-wrap gap-2">{question.citations.map((item, citationIndex) => <Button key={item.id} variant="soft" size="sm" onClick={() => setCitation(item)}><BookOpen className="h-3.5 w-3.5" />出处 {citationIndex + 1}</Button>)}</div></CardBody></Card>)}</div> : <Card><CardBody className="py-12 text-center"><CheckCircle2 className="mx-auto h-9 w-9 text-pine-500" /><p className="mt-3 font-bold text-ink">全部答对</p><p className="mt-1 text-sm text-stone-400">这套题已经掌握得很扎实。</p></CardBody></Card>}
      </section>
      <CitationDrawer citation={citation} open={Boolean(citation)} onOpenChange={(open) => { if (!open) setCitation(null); }} />
    </div>
  );
}
