import * as Dialog from '@radix-ui/react-dialog';
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, FileSearch, Minus, Plus, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import 'react-pdf/dist/Page/TextLayer.css';
import { api } from '../lib/api';
import { toErrorMessage } from '../lib/utils';
import type { CitationAnchor, CitationRect } from '../types/api';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { ErrorState, PageLoader } from './ui/States';

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

function isPdf(citation: CitationAnchor) {
  return citation.document_type?.toLowerCase().includes('pdf') || citation.document_name.toLowerCase().endsWith('.pdf');
}

function rectStyle(rect: CitationRect): React.CSSProperties | null {
  const pageWidth = rect.page_width ?? (rect.x <= 1 && rect.width <= 1 ? 1 : undefined);
  const pageHeight = rect.page_height ?? (rect.y <= 1 && rect.height <= 1 ? 1 : undefined);
  if (!pageWidth || !pageHeight) return null;
  const left = (rect.x / pageWidth) * 100;
  const width = (rect.width / pageWidth) * 100;
  const height = (rect.height / pageHeight) * 100;
  const top = rect.coordinate_system === 'bottom-left'
    ? ((pageHeight - rect.y - rect.height) / pageHeight) * 100
    : (rect.y / pageHeight) * 100;
  return { left: `${left}%`, top: `${top}%`, width: `${width}%`, height: `${height}%` };
}

function HighlightedText({ text, excerpt }: { text: string; excerpt: string }) {
  const index = text.indexOf(excerpt);
  if (index < 0 || !excerpt) return <p className="whitespace-pre-wrap text-sm leading-8 text-stone-700">{text}</p>;
  return (
    <p className="whitespace-pre-wrap text-sm leading-8 text-stone-700">
      {text.slice(0, index)}
      <mark className="rounded bg-amber-100 px-0.5 text-ink">{text.slice(index, index + excerpt.length)}</mark>
      {text.slice(index + excerpt.length)}
    </p>
  );
}

export function CitationDrawer({
  citation,
  open,
  onOpenChange,
}: {
  citation: CitationAnchor | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(700);
  const [pageCount, setPageCount] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const pdf = citation ? isPdf(citation) : false;
  const content = useQuery({
    queryKey: ['citation-content', citation?.document_id, citation?.block_id],
    queryFn: () => api.getCitationContent(
      citation!.document_id,
      citation!.block_id,
      citation!.document_version_id,
    ),
    enabled: open && Boolean(citation) && !pdf,
  });

  useEffect(() => {
    if (!citation) return;
    setPageNumber(citation.page_number ?? 1);
    setZoom(1);
  }, [citation]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setContainerWidth(Math.max(280, entry.contentRect.width - 32)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [open]);

  const rectangles = useMemo(
    () => citation?.rectangles?.map(rectStyle).filter((style): style is React.CSSProperties => Boolean(style)) ?? [],
    [citation],
  );

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/35 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-[#F8F6F0] shadow-drawer focus:outline-none sm:w-[min(72vw,60rem)]">
          <header className="flex min-h-16 items-center justify-between gap-4 border-b border-stone-200 bg-white px-4 sm:px-5">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-sm font-bold text-ink">答案出处 · {citation?.document_name ?? ''}</Dialog.Title>
              <Dialog.Description className="mt-0.5 text-xs text-stone-400">
                {citation?.page_number ? `第 ${citation.page_number} 页` : citation?.block_id ? `段落 ${citation.block_id}` : '原文片段'}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="关闭出处侧栏"><X aria-hidden="true" className="h-5 w-5" /></Button>
            </Dialog.Close>
          </header>

          {citation ? (
            <>
              <div className="border-b border-stone-200 bg-amber-50 px-4 py-3 sm:px-5">
                <div className="flex items-start gap-2">
                  <FileSearch aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                  <p className="line-clamp-3 text-xs leading-5 text-amber-600">“{citation.excerpt}”</p>
                </div>
              </div>

              {pdf ? (
                <>
                  <div className="flex items-center justify-between gap-2 border-b border-stone-200 bg-white px-3 py-2">
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="icon" aria-label="上一页" disabled={pageNumber <= 1} onClick={() => setPageNumber((page) => page - 1)}><ChevronLeft className="h-4 w-4" /></Button>
                      <span className="min-w-24 text-center text-xs font-semibold text-stone-600">{pageNumber} / {pageCount || '—'}</span>
                      <Button variant="ghost" size="icon" aria-label="下一页" disabled={pageCount > 0 && pageNumber >= pageCount} onClick={() => setPageNumber((page) => page + 1)}><ChevronRight className="h-4 w-4" /></Button>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="icon" aria-label="缩小" disabled={zoom <= 0.7} onClick={() => setZoom((value) => Math.max(0.7, value - 0.1))}><Minus className="h-4 w-4" /></Button>
                      <span className="w-12 text-center text-xs font-semibold text-stone-500">{Math.round(zoom * 100)}%</span>
                      <Button variant="ghost" size="icon" aria-label="放大" disabled={zoom >= 1.8} onClick={() => setZoom((value) => Math.min(1.8, value + 0.1))}><Plus className="h-4 w-4" /></Button>
                    </div>
                  </div>
                  <div ref={containerRef} className="flex-1 overflow-auto p-4">
                    <Document
                      file={citation.file_url || api.documentFileUrl(citation.document_id)}
                      onLoadSuccess={({ numPages }) => setPageCount(numPages)}
                      loading={<PageLoader label="正在打开 PDF…" />}
                      error={<ErrorState message="PDF 无法打开，请确认原文档仍然存在。" />}
                    >
                      <div className="relative mx-auto w-fit overflow-hidden bg-white shadow-card" style={{ width: containerWidth * zoom }}>
                        <Page pageNumber={pageNumber} width={containerWidth * zoom} renderAnnotationLayer={false} />
                        {pageNumber === citation.page_number ? (
                          <div aria-label="答案出处高亮区域" className="pointer-events-none absolute inset-0">
                            {rectangles.map((style, index) => (
                              <span key={index} className="absolute rounded-sm border-2 border-amber-500 bg-amber-300/35 shadow-[0_0_0_2px_rgba(255,255,255,.35)]" style={style} />
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </Document>
                  </div>
                  {!rectangles.length ? (
                    <div className="border-t border-stone-200 bg-white px-4 py-2 text-center text-xs text-stone-400">当前引用没有坐标框，已跳转到对应页并保留原文摘录。</div>
                  ) : null}
                </>
              ) : (
                <div className="flex-1 overflow-auto p-4 sm:p-6">
                  {content.isLoading ? <PageLoader label="正在定位原文段落…" /> : null}
                  {content.error ? <ErrorState message={toErrorMessage(content.error)} onRetry={() => void content.refetch()} /> : null}
                  {content.data ? (
                    <article className="paper-lines mx-auto max-w-3xl rounded-2xl border border-stone-200 bg-white p-6 shadow-card sm:p-9">
                      <div className="mb-5 flex items-center gap-2"><Badge tone="info">结构化原文</Badge>{citation.block_id ? <span className="text-xs text-stone-400">段落 {citation.block_id}</span> : null}</div>
                      <HighlightedText text={content.data.text} excerpt={citation.excerpt} />
                    </article>
                  ) : null}
                </div>
              )}
            </>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
