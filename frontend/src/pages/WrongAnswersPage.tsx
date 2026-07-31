import { useMutation, useQuery } from '@tanstack/react-query';
import { BookOpen, RotateCcw, Target } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { CitationDrawer } from '../components/CitationDrawer';
import { PageHeader } from '../components/PageHeader';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card, CardBody } from '../components/ui/Card';
import { ErrorState, EmptyState, PageLoader } from '../components/ui/States';
import { api } from '../lib/api';
import { formatDate, toErrorMessage } from '../lib/utils';
import type { CitationAnchor } from '../types/api';

export function WrongAnswersPage() {
  const navigate = useNavigate();
  const [citation, setCitation] = useState<CitationAnchor | null>(null);
  const wrong = useQuery({ queryKey: ['wrong-answers'], queryFn: api.listWrongAnswers });
  const retry = useMutation({ mutationFn: (ids: string[]) => api.createWrongAnswerSession(ids), onSuccess: (session) => navigate(`/practice/${session.id}`), onError: (error) => toast.error(toErrorMessage(error)) });
  if (wrong.isLoading) return <PageLoader label="正在整理错题…" />;
  if (wrong.error) return <ErrorState message={toErrorMessage(wrong.error)} onRetry={() => void wrong.refetch()} />;
  return <div className="animate-fade-in"><PageHeader eyebrow="巩固薄弱点" title="错题回看" description="反复做错的知识点会留在这里，可以随时查看解析和原文出处。" actions={wrong.data?.length ? <Button onClick={() => retry.mutate(wrong.data!.map((item) => item.question.id))} loading={retry.isPending}><RotateCcw className="h-4 w-4" />全部重练</Button> : undefined} />{wrong.data?.length ? <div className="space-y-4">{wrong.data.map((record) => <Card key={record.question.id}><CardBody><div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start"><div className="min-w-0"><div className="flex flex-wrap gap-2"><Badge tone="danger">错 {record.wrong_count} 次</Badge><Badge>{record.question.knowledge_point}</Badge><span className="text-xs text-stone-400">最近 {formatDate(record.last_answered_at)}</span></div><h2 className="mt-3 font-bold leading-7 text-ink">{record.question.stem}</h2><p className="mt-2 text-sm"><span className="text-red-600">上次选择 {record.selected_answer || '未答'}</span><span className="mx-2 text-stone-300">·</span><span className="font-bold text-pine-700">正确答案 {record.question.correct_answer}</span></p><p className="mt-3 text-sm leading-7 text-stone-500">{record.question.explanation}</p><div className="mt-3 flex flex-wrap gap-2">{record.question.citations.map((item) => <Button key={item.id} variant="soft" size="sm" onClick={() => setCitation(item)}><BookOpen className="h-3.5 w-3.5" />查看出处</Button>)}</div></div><Button variant="secondary" size="sm" onClick={() => retry.mutate([record.question.id])}><Target className="h-3.5 w-3.5" />再练一次</Button></div></CardBody></Card>)}</div> : <EmptyState title="暂无错题" description="完成练习或模拟考试后，答错的题目会自动汇总在这里。" />}<CitationDrawer citation={citation} open={Boolean(citation)} onOpenChange={(open) => { if (!open) setCitation(null); }} /></div>;
}
