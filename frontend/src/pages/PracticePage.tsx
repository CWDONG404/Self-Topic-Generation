import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, BookOpen, Check, Clock3, Flag, Send } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { CitationDrawer } from '../components/CitationDrawer';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card, CardBody } from '../components/ui/Card';
import { ErrorState, PageLoader } from '../components/ui/States';
import { Progress } from '../components/ui/Progress';
import { api } from '../lib/api';
import { createAnswerSaveQueue } from '../lib/practiceSaveQueue';
import { cn, toErrorMessage } from '../lib/utils';
import type { CitationAnchor } from '../types/api';

export function PracticePage() {
  const { sessionId = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [pendingSaves, setPendingSaves] = useState(0);
  const [citation, setCitation] = useState<CitationAnchor | null>(null);
  const session = useQuery({ queryKey: ['practice-session', sessionId], queryFn: () => api.getPracticeSession(sessionId), enabled: Boolean(sessionId) });
  const answerSaveQueue = useMemo(
    () => createAnswerSaveQueue((questionId, answer) => api.savePracticeAnswer(sessionId, questionId, answer)),
    [sessionId],
  );

  useEffect(() => {
    if (!session.data) return;
    setAnswers(Object.fromEntries(session.data.answers.filter((item) => item.selected_answer).map((item) => [item.question_id, item.selected_answer!])))
    setCurrentIndex(session.data.current_question_index ?? 0);
  }, [session.data]);

  const submit = useMutation({
    mutationFn: async () => {
      await answerSaveQueue.flush(answers);
      return api.submitPracticeSession(sessionId);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['practice-session', sessionId] }); navigate(`/results/${sessionId}`); },
    onError: (error) => toast.error(`交卷前保存答案失败：${toErrorMessage(error)}`),
  });

  if (session.isLoading) return <PageLoader label="正在准备题目…" />;
  if (session.error || !session.data) return <ErrorState message={toErrorMessage(session.error ?? new Error('练习不存在'))} onRetry={() => void session.refetch()} />;
  if (session.data.status === 'submitted') { navigate(`/results/${sessionId}`, { replace: true }); return null; }
  const questions = session.data.paper?.questions?.filter((item) => item.enabled) ?? [];
  if (!questions.length) return <ErrorState message="当前练习没有可用题目。" />;
  const question = questions[Math.min(currentIndex, questions.length - 1)];
  const selected = answers[question.id];
  const answeredCount = Object.values(answers).filter(Boolean).length;
  const practiceMode = session.data.mode !== 'exam';

  const choose = (answer: string) => {
    setAnswers((current) => ({ ...current, [question.id]: answer }));
    setPendingSaves((count) => count + 1);
    void answerSaveQueue.enqueue(question.id, answer)
      .catch((error) => toast.error(`答案保存失败，将在交卷前重试：${toErrorMessage(error)}`))
      .finally(() => setPendingSaves((count) => Math.max(0, count - 1)));
  };
  const finish = () => {
    if (answeredCount < questions.length && !window.confirm(`还有 ${questions.length - answeredCount} 题未作答，确认交卷吗？`)) return;
    submit.mutate();
  };

  return (
    <div className="animate-fade-in">
      <header className="mb-5 flex flex-col justify-between gap-4 rounded-2xl border border-stone-200 bg-white p-4 shadow-card sm:flex-row sm:items-center sm:px-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2"><Badge tone={practiceMode ? 'success' : 'warning'}>{practiceMode ? '练习模式' : '考试模式'}</Badge><span className="text-xs text-stone-400">{pendingSaves ? `正在保存 ${pendingSaves} 项…` : '已自动保存'}</span></div>
          <h1 className="mt-2 truncate text-lg font-bold text-ink">{session.data.paper?.title ?? '答题练习'}</h1>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-xs font-semibold text-stone-500"><Clock3 className="h-3.5 w-3.5" />{answeredCount} / {questions.length} 已答</span>
          <Button variant="secondary" size="sm" onClick={finish} loading={submit.isPending}><Send className="h-3.5 w-3.5" />交卷</Button>
        </div>
      </header>

      <Progress value={(answeredCount / questions.length) * 100} className="mb-5" label="答题进度" />
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_17rem]">
        <Card>
          <CardBody className="p-5 sm:p-8">
            <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-bold uppercase tracking-[.15em] text-pine-600">第 {currentIndex + 1} 题</span><Badge>{question.knowledge_point}</Badge></div>
            <h2 className="mt-4 text-lg font-bold leading-8 text-ink">{question.stem}</h2>
            <fieldset className="mt-6 space-y-3" disabled={submit.isPending}>
              <legend className="sr-only">请选择答案</legend>
              {question.options.map((option) => {
                const chosen = selected === option.key;
                const showCorrect = practiceMode && Boolean(selected) && option.key === question.correct_answer;
                const showWrong = practiceMode && chosen && selected !== question.correct_answer;
                return (
                  <label key={option.key} className={cn('flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition', showCorrect ? 'border-pine-400 bg-pine-50' : showWrong ? 'border-red-300 bg-red-50' : chosen ? 'border-pine-500 bg-pine-50' : 'border-stone-200 bg-white hover:border-stone-300')}>
                    <input className="sr-only" type="radio" name={`question-${question.id}`} value={option.key} checked={chosen} onChange={() => choose(option.key)} />
                    <span className={cn('grid h-7 w-7 shrink-0 place-items-center rounded-full border text-xs font-bold', chosen || showCorrect ? 'border-pine-600 bg-pine-600 text-white' : 'border-stone-300 text-stone-500')}>
                      {showCorrect ? <Check className="h-4 w-4" /> : option.key}
                    </span>
                    <span className="pt-0.5 text-sm leading-6 text-stone-700">{option.text}</span>
                  </label>
                );
              })}
            </fieldset>

            {practiceMode && selected ? (
              <div className={cn('mt-6 rounded-2xl border p-5', selected === question.correct_answer ? 'border-pine-100 bg-pine-50' : 'border-red-100 bg-red-50')}>
                <p className={cn('text-sm font-bold', selected === question.correct_answer ? 'text-pine-700' : 'text-red-700')}>{selected === question.correct_answer ? '回答正确' : `正确答案是 ${question.correct_answer}`}</p>
                <p className="mt-2 text-sm leading-7 text-stone-600">{question.explanation}</p>
                <div className="mt-3 flex flex-wrap gap-2">{question.citations.map((item, index) => <Button key={item.id} variant="secondary" size="sm" onClick={() => setCitation(item)}><BookOpen className="h-3.5 w-3.5" />查看出处 {index + 1}</Button>)}</div>
              </div>
            ) : null}

            <div className="mt-7 flex items-center justify-between border-t border-stone-100 pt-5">
              <Button variant="secondary" disabled={currentIndex === 0} onClick={() => setCurrentIndex((index) => index - 1)}><ArrowLeft className="h-4 w-4" />上一题</Button>
              {currentIndex < questions.length - 1 ? <Button onClick={() => setCurrentIndex((index) => index + 1)}>下一题<ArrowRight className="h-4 w-4" /></Button> : <Button onClick={finish} loading={submit.isPending}>交卷<Flag className="h-4 w-4" /></Button>}
            </div>
          </CardBody>
        </Card>

        <aside className="xl:sticky xl:top-8">
          <Card>
            <CardBody>
              <h2 className="text-sm font-bold text-ink">答题卡</h2>
              <div className="mt-4 grid grid-cols-5 gap-2 sm:grid-cols-10 xl:grid-cols-5">
                {questions.map((item, index) => (
                  <button key={item.id} onClick={() => setCurrentIndex(index)} aria-label={`跳到第 ${index + 1} 题`} aria-current={index === currentIndex ? 'step' : undefined} className={cn('grid aspect-square place-items-center rounded-lg text-xs font-bold transition', index === currentIndex ? 'bg-ink text-white ring-2 ring-ink ring-offset-2' : answers[item.id] ? 'bg-pine-100 text-pine-700' : 'bg-stone-100 text-stone-400 hover:bg-stone-200')}>{index + 1}</button>
                ))}
              </div>
              <div className="mt-4 flex items-center justify-between text-xs text-stone-400"><span>已答 {answeredCount}</span><span>未答 {questions.length - answeredCount}</span></div>
            </CardBody>
          </Card>
        </aside>
      </div>
      <CitationDrawer citation={citation} open={Boolean(citation)} onOpenChange={(open) => { if (!open) setCitation(null); }} />
    </div>
  );
}
