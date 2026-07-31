import * as Dialog from '@radix-ui/react-dialog';
import { BookOpen, FilePenLine, RefreshCw, ShieldCheck, Sparkles, Trash2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '../lib/utils';
import type { CitationAnchor, Question } from '../types/api';
import { StatusBadge } from './StatusBadge';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Card, CardBody } from './ui/Card';
import { Select } from './ui/Select';

const difficultyLabel = { easy: '简单', medium: '中等', hard: '较难' };

export function QuestionReviewCard({
  question,
  index,
  onCitation,
  onSave,
  onReview,
  onRegenerate,
  onDisable,
  busy,
}: {
  question: Question;
  index: number;
  onCitation: (citation: CitationAnchor) => void;
  onSave: (payload: Partial<Question>) => void;
  onReview: () => void;
  onRegenerate: () => void;
  onDisable: () => void;
  busy?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(question);
  useEffect(() => setDraft(question), [question]);

  return (
    <Card className={cn('overflow-hidden', !question.enabled && 'opacity-60')}>
      <CardBody className="p-0">
        <div className="flex flex-col gap-4 border-b border-stone-100 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <span className="grid h-8 min-w-8 place-items-center rounded-lg bg-ink px-2 text-xs font-bold text-white">{String(index + 1).padStart(2, '0')}</span>
            <Badge>{difficultyLabel[question.difficulty]}</Badge>
            <Badge tone="info">{question.knowledge_point}</Badge>
            <StatusBadge status={question.review?.status ?? 'pending'} />
            {question.similarity_relaxed ? <Badge tone="warning">相似题补足</Badge> : null}
          </div>
          <div className="flex flex-wrap gap-1">
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}><FilePenLine className="h-3.5 w-3.5" />编辑</Button>
            <Button variant="ghost" size="sm" onClick={onReview} disabled={busy}><ShieldCheck className="h-3.5 w-3.5" />复审</Button>
            <Button variant="ghost" size="sm" onClick={onRegenerate} disabled={busy}><RefreshCw className="h-3.5 w-3.5" />重生成</Button>
            <Button variant="danger" size="sm" onClick={onDisable} disabled={busy || !question.enabled}><Trash2 className="h-3.5 w-3.5" />停用</Button>
          </div>
        </div>
        <div className="p-5 sm:p-6">
          <h3 className="text-base font-bold leading-7 text-ink">{question.stem}</h3>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {question.options.map((option) => (
              <div key={option.key} className={cn('flex items-start gap-3 rounded-xl border p-3 text-sm leading-6', option.key === question.correct_answer ? 'border-pine-200 bg-pine-50 text-pine-900' : 'border-stone-200 text-stone-600')}>
                <span className={cn('grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold', option.key === question.correct_answer ? 'bg-pine-600 text-white' : 'bg-stone-100 text-stone-500')}>{option.key}</span>
                {option.text}
              </div>
            ))}
          </div>
          <div className="mt-5 rounded-xl bg-stone-50 p-4">
            <p className="text-xs font-bold uppercase tracking-[.12em] text-stone-400">答案解析</p>
            <p className="mt-2 text-sm leading-7 text-stone-600">{question.explanation}</p>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {question.citations.map((citation, citationIndex) => (
              <Button key={citation.id} variant="soft" size="sm" onClick={() => onCitation(citation)}>
                <BookOpen className="h-3.5 w-3.5" />
                出处 {citationIndex + 1} · {citation.document_name}{citation.page_number ? ` P.${citation.page_number}` : ''}
              </Button>
            ))}
          </div>
          {question.review?.comments?.length ? (
            <div className="mt-4 border-l-2 border-violet-200 pl-3 text-xs leading-5 text-stone-500">审查意见：{question.review.comments.join('；')}</div>
          ) : null}
        </div>
      </CardBody>

      <Dialog.Root open={editing} onOpenChange={setEditing}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/35 backdrop-blur-sm" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(94vw,46rem)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl bg-white p-5 shadow-2xl focus:outline-none sm:p-7">
            <div className="flex items-start justify-between gap-4">
              <div><Dialog.Title className="text-lg font-bold text-ink">编辑第 {index + 1} 题</Dialog.Title><Dialog.Description className="mt-1 text-xs text-stone-400">保存后建议重新运行独立审查。</Dialog.Description></div>
              <Dialog.Close asChild><Button variant="ghost" size="icon" aria-label="关闭编辑器"><X className="h-5 w-5" /></Button></Dialog.Close>
            </div>
            <div className="mt-6 space-y-4">
              <label><span className="field-label">题干</span><textarea rows={3} className="field-control py-3" value={draft.stem} onChange={(event) => setDraft({ ...draft, stem: event.target.value })} /></label>
              <div className="grid gap-3 sm:grid-cols-2">
                {draft.options.map((option, optionIndex) => (
                  <label key={option.key}><span className="field-label">选项 {option.key}</span><input className="field-control" value={option.text} onChange={(event) => setDraft({ ...draft, options: draft.options.map((item, index) => index === optionIndex ? { ...item, text: event.target.value } : item) })} /></label>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label><span className="field-label">正确答案</span><Select value={draft.correct_answer} onChange={(event) => setDraft({ ...draft, correct_answer: event.target.value as Question['correct_answer'] })}>{draft.options.map((option) => <option key={option.key} value={option.key}>{option.key}</option>)}</Select></label>
                <label><span className="field-label">难度</span><Select value={draft.difficulty} onChange={(event) => setDraft({ ...draft, difficulty: event.target.value as Question['difficulty'] })}><option value="easy">简单</option><option value="medium">中等</option><option value="hard">较难</option></Select></label>
              </div>
              <label><span className="field-label">知识点</span><input className="field-control" value={draft.knowledge_point} onChange={(event) => setDraft({ ...draft, knowledge_point: event.target.value })} /></label>
              <label><span className="field-label">答案解析</span><textarea rows={4} className="field-control py-3" value={draft.explanation} onChange={(event) => setDraft({ ...draft, explanation: event.target.value })} /></label>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Dialog.Close asChild><Button variant="secondary">取消</Button></Dialog.Close>
              <Button onClick={() => { onSave({ stem: draft.stem, options: draft.options, correct_answer: draft.correct_answer, difficulty: draft.difficulty, knowledge_point: draft.knowledge_point, explanation: draft.explanation }); setEditing(false); }}>
                <Sparkles className="h-4 w-4" />保存修改
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </Card>
  );
}
