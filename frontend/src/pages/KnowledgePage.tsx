import * as Dialog from '@radix-ui/react-dialog';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Archive,
  ArchiveRestore,
  BookMarked,
  Check,
  File,
  FilePenLine,
  FileText,
  FolderPlus,
  Image,
  Info,
  Plus,
  RefreshCw,
  UploadCloud,
  X,
} from 'lucide-react';
import { useMemo, useRef, useState, type DragEvent } from 'react';
import { toast } from 'sonner';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card, CardBody, CardHeader } from '../components/ui/Card';
import { Progress } from '../components/ui/Progress';
import { Select } from '../components/ui/Select';
import { EmptyState, ErrorState, PageLoader } from '../components/ui/States';
import { api } from '../lib/api';
import { cn, formatBytes, formatDate, toErrorMessage } from '../lib/utils';
import type { DocumentRecord, DocumentRole } from '../types/api';

const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.md', '.markdown', '.txt'];

type DocumentUpdate = Partial<Pick<DocumentRecord, 'name' | 'role' | 'allow_as_evidence'>> & {
  archived?: boolean;
};

type EditDraft = {
  name: string;
  role: DocumentRole;
  allowAsEvidence: boolean;
};

function fileIcon(document: DocumentRecord) {
  if (document.mime_type?.startsWith('image/')) return Image;
  if (['.md', '.markdown', '.txt'].includes(document.extension?.toLowerCase() ?? '')) return FileText;
  return File;
}

function DocumentEditDialog({
  document,
  draft,
  busy,
  onDraftChange,
  onClose,
  onSave,
}: {
  document: DocumentRecord | null;
  draft: EditDraft;
  busy: boolean;
  onDraftChange: (draft: EditDraft) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <Dialog.Root open={Boolean(document)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/35 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(94vw,34rem)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl bg-white p-5 shadow-2xl focus:outline-none sm:p-7">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-lg font-bold text-ink">编辑文档信息</Dialog.Title>
              <Dialog.Description className="mt-1 text-xs leading-5 text-stone-400">
                修改显示名称与资料用途，不会改动原始文件内容。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="关闭文档编辑器">
                <X aria-hidden="true" className="h-5 w-5" />
              </Button>
            </Dialog.Close>
          </div>

          <div className="mt-6 space-y-5">
            <label>
              <span className="field-label">显示名称</span>
              <input
                className="field-control"
                value={draft.name}
                maxLength={255}
                onChange={(event) => onDraftChange({ ...draft, name: event.target.value })}
                placeholder="输入便于识别的文档名称"
                autoFocus
              />
              {document?.original_filename ? (
                <span className="field-help block truncate">原始文件：{document.original_filename}</span>
              ) : null}
            </label>

            <label>
              <span className="field-label">资料角色</span>
              <Select
                value={draft.role}
                onChange={(event) => {
                  const nextRole = event.target.value as DocumentRole;
                  onDraftChange({
                    ...draft,
                    role: nextRole,
                    allowAsEvidence: nextRole === 'source',
                  });
                }}
              >
                <option value="source">权威正文</option>
                <option value="outline">重点 / 大纲</option>
              </Select>
              <span className="field-help block">
                正文用于证明答案；大纲用于规划考点，只有明确开启后才可作为证据。
              </span>
            </label>

            <label className={cn(
              'flex min-h-12 items-start gap-3 rounded-xl border p-3.5 text-sm',
              draft.role === 'source' ? 'border-pine-100 bg-pine-50/70' : 'border-stone-200',
            )}>
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 rounded border-stone-300 text-pine-600 focus:ring-pine-500"
                checked={draft.role === 'source' || draft.allowAsEvidence}
                disabled={draft.role === 'source'}
                onChange={(event) => onDraftChange({ ...draft, allowAsEvidence: event.target.checked })}
              />
              <span>
                <span className="block font-semibold text-ink">允许作为答案依据</span>
                <span className="mt-1 block text-xs leading-5 text-stone-500">
                  {draft.role === 'source'
                    ? '权威正文始终可作为答案依据。'
                    : '仅在大纲本身也包含可靠正文时开启。'}
                </span>
              </span>
            </label>
          </div>

          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="secondary">取消</Button>
            </Dialog.Close>
            <Button
              loading={busy}
              disabled={!draft.name.trim()}
              onClick={onSave}
            >
              保存修改
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ArchiveDocumentDialog({
  document,
  busy,
  onClose,
  onConfirm,
}: {
  document: DocumentRecord | null;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog.Root open={Boolean(document)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/35 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-2xl focus:outline-none">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-amber-50 text-amber-700">
            <Archive aria-hidden="true" className="h-5 w-5" />
          </span>
          <Dialog.Title className="mt-4 text-lg font-bold text-ink">归档这份文档？</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm leading-6 text-stone-500">
            “{document?.name}”归档后不会参与出题，也不会永久删除文件。之后可在“已归档”列表中恢复。
          </Dialog.Description>
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="secondary">取消</Button>
            </Dialog.Close>
            <Button variant="danger" loading={busy} onClick={onConfirm}>
              确认归档
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [selectedLibrary, setSelectedLibrary] = useState('');
  const [libraryName, setLibraryName] = useState('');
  const [role, setRole] = useState<DocumentRole>('source');
  const [allowEvidence, setAllowEvidence] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [uploadingNames, setUploadingNames] = useState<string[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [editingDocument, setEditingDocument] = useState<DocumentRecord | null>(null);
  const [editDraft, setEditDraft] = useState<EditDraft>({
    name: '',
    role: 'source',
    allowAsEvidence: true,
  });
  const [archiveTarget, setArchiveTarget] = useState<DocumentRecord | null>(null);

  const libraries = useQuery({ queryKey: ['libraries'], queryFn: api.listLibraries });
  const activeLibrary = selectedLibrary || libraries.data?.[0]?.id || '';
  const documents = useQuery({
    queryKey: ['documents', activeLibrary, { includeArchived: true }],
    queryFn: () => api.listDocuments(activeLibrary, { includeArchived: true }),
    enabled: Boolean(activeLibrary),
    refetchInterval: (query) =>
      query.state.data?.some((item) => ['queued', 'parsing'].includes(item.status)) ? 3_000 : false,
  });

  const refreshDocuments = () => {
    void queryClient.invalidateQueries({ queryKey: ['documents'] });
    void queryClient.invalidateQueries({ queryKey: ['libraries'] });
  };

  const createLibrary = useMutation({
    mutationFn: () => api.createLibrary({ name: libraryName.trim() }),
    onSuccess: (library) => {
      setLibraryName('');
      setSelectedLibrary(library.id);
      void queryClient.invalidateQueries({ queryKey: ['libraries'] });
      toast.success('资料库已创建');
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const updateDocument = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: DocumentUpdate;
      successMessage: string;
      closeEditor?: boolean;
    }) => api.updateDocument(id, payload),
    onSuccess: (_document, variables) => {
      if (variables.closeEditor) setEditingDocument(null);
      refreshDocuments();
      toast.success(variables.successMessage);
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const parseDocument = useMutation({
    mutationFn: api.parseDocument,
    onSuccess: () => {
      refreshDocuments();
      toast.success('文档已重新进入解析队列');
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const archiveDocument = useMutation({
    mutationFn: api.archiveDocument,
    onSuccess: () => {
      setArchiveTarget(null);
      refreshDocuments();
      toast.success('文档已归档，可随时恢复');
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const uploadFiles = async (files: File[]) => {
    if (!activeLibrary) {
      toast.error('请先创建资料库');
      return;
    }
    const valid = files.filter((file) => ACCEPTED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext)));
    if (valid.length !== files.length) toast.warning('已跳过不支持的文件格式');
    if (!valid.length) return;

    setUploadingNames(valid.map((file) => file.name));
    const results = await Promise.allSettled(
      valid.map((file) => api.uploadDocument(file, activeLibrary, role, role === 'source' || allowEvidence)),
    );
    const failed = results.filter((result) => result.status === 'rejected').length;
    setUploadingNames([]);
    refreshDocuments();
    if (failed) toast.error(`${failed} 份文档上传失败`);
    else toast.success(`${valid.length} 份文档已进入解析队列`);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    void uploadFiles(Array.from(event.dataTransfer.files));
  };

  const activeDocuments = documents.data?.filter((item) => item.status !== 'archived') ?? [];
  const archivedDocuments = documents.data?.filter((item) => item.status === 'archived') ?? [];
  const documentGroups = useMemo(() => ({
    outline: activeDocuments.filter((item) => item.role === 'outline'),
    source: activeDocuments.filter((item) => item.role === 'source'),
  }), [activeDocuments]);

  const startEditing = (document: DocumentRecord) => {
    setEditDraft({
      name: document.name || document.original_filename || '',
      role: document.role,
      allowAsEvidence: document.role === 'source' || document.allow_as_evidence,
    });
    setEditingDocument(document);
  };

  if (libraries.isLoading) return <PageLoader />;
  if (libraries.error) return <ErrorState message={toErrorMessage(libraries.error)} onRetry={() => void libraries.refetch()} />;

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="知识来源"
        title="资料库"
        description="把考试重点与权威正文分开管理。重点决定考什么，正文负责证明答案。"
        actions={
          activeLibrary ? (
            <Button onClick={() => inputRef.current?.click()}>
              <Plus aria-hidden="true" className="h-4 w-4" />
              上传资料
            </Button>
          ) : undefined
        }
      />

      <div className="grid gap-6 xl:grid-cols-[18rem_minmax(0,1fr)]">
        <aside>
          <Card>
            <CardHeader>
              <h2 className="text-sm font-bold text-ink">知识空间</h2>
            </CardHeader>
            <CardBody className="p-3">
              <div className="space-y-1">
                {libraries.data?.map((library) => (
                  <button
                    key={library.id}
                    className={cn(
                      'flex w-full items-center justify-between rounded-xl px-3 py-3 text-left text-sm transition',
                      activeLibrary === library.id ? 'bg-pine-50 font-semibold text-pine-700' : 'text-stone-600 hover:bg-stone-50',
                    )}
                    onClick={() => {
                      setSelectedLibrary(library.id);
                      setShowArchived(false);
                    }}
                  >
                    <span className="flex min-w-0 items-center gap-2.5">
                      <BookMarked aria-hidden="true" className="h-4 w-4 shrink-0" />
                      <span className="truncate">{library.name}</span>
                    </span>
                    <span className="text-xs text-stone-400">{library.document_count ?? 0}</span>
                  </button>
                ))}
              </div>
              <form
                className="mt-3 border-t border-stone-100 pt-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (libraryName.trim()) createLibrary.mutate();
                }}
              >
                <label htmlFor="new-library" className="sr-only">新资料库名称</label>
                <div className="flex gap-2">
                  <input
                    id="new-library"
                    value={libraryName}
                    onChange={(event) => setLibraryName(event.target.value)}
                    placeholder="新资料库名称"
                    className="field-control min-w-0"
                  />
                  <Button type="submit" size="icon" variant="secondary" loading={createLibrary.isPending} aria-label="创建资料库">
                    <FolderPlus aria-hidden="true" className="h-4 w-4" />
                  </Button>
                </div>
              </form>
            </CardBody>
          </Card>

          <div className="mt-4 rounded-2xl border border-amber-100 bg-amber-50 p-4">
            <div className="flex items-start gap-3">
              <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <p className="text-xs leading-5 text-amber-600">
                支持 PDF、DOCX、Markdown 和 TXT。单文件默认不超过 200 MB。
              </p>
            </div>
          </div>
        </aside>

        <div className="min-w-0 space-y-6">
          {!activeLibrary ? (
            <EmptyState title="先创建一个资料库" description="例如“CISP 备考”或“计算机网络”，随后即可上传资料。" />
          ) : (
            <>
              <Card>
                <CardBody className="p-4 sm:p-5">
                  <div className="mb-4 grid gap-3 sm:grid-cols-2">
                    <fieldset>
                      <legend className="field-label">资料角色</legend>
                      <div className="grid grid-cols-2 gap-2">
                        {([
                          ['source', '权威正文'],
                          ['outline', '重点 / 大纲'],
                        ] as const).map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            onClick={() => {
                              setRole(value);
                              setAllowEvidence(value === 'source');
                            }}
                            className={cn(
                              'min-h-11 rounded-xl border px-3 text-sm font-semibold transition',
                              role === value ? 'border-pine-500 bg-pine-50 text-pine-700' : 'border-stone-200 bg-white text-stone-500 hover:border-stone-300',
                            )}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </fieldset>
                    <div>
                      <span className="field-label">答案依据</span>
                      <label className={cn('flex min-h-11 items-center gap-3 rounded-xl border px-3.5 text-sm', role === 'source' ? 'border-pine-100 bg-pine-50/70' : 'border-stone-200 bg-white')}>
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-stone-300 text-pine-600 focus:ring-pine-500"
                          checked={role === 'source' || allowEvidence}
                          disabled={role === 'source'}
                          onChange={(event) => setAllowEvidence(event.target.checked)}
                        />
                        {role === 'source' ? '正文始终作为答案依据' : '允许重点资料作为答案依据'}
                      </label>
                    </div>
                  </div>

                  <input
                    ref={inputRef}
                    type="file"
                    accept=".pdf,.docx,.md,.markdown,.txt"
                    multiple
                    className="sr-only"
                    onChange={(event) => {
                      if (event.target.files) void uploadFiles(Array.from(event.target.files));
                      event.target.value = '';
                    }}
                  />
                  <div
                    role="button"
                    tabIndex={0}
                    aria-label="上传文档，可点击选择文件或拖放文件"
                    onClick={() => inputRef.current?.click()}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click();
                    }}
                    onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
                    onDragOver={(event) => event.preventDefault()}
                    onDragLeave={() => setDragging(false)}
                    onDrop={onDrop}
                    className={cn(
                      'flex min-h-44 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-6 text-center transition',
                      dragging ? 'border-pine-500 bg-pine-50' : 'border-stone-200 bg-stone-50/60 hover:border-pine-300 hover:bg-pine-50/40',
                    )}
                  >
                    <span className="grid h-12 w-12 place-items-center rounded-2xl bg-white text-pine-600 shadow-sm">
                      <UploadCloud aria-hidden="true" className="h-6 w-6" />
                    </span>
                    <p className="mt-3 text-sm font-bold text-ink">拖放文档到这里，或点击选择</p>
                    <p className="mt-1 text-xs text-stone-400">PDF · DOCX · MD · TXT，可一次上传多份</p>
                    {uploadingNames.length ? <p className="mt-3 text-xs font-semibold text-pine-600">正在上传 {uploadingNames.length} 份文档…</p> : null}
                  </div>
                </CardBody>
              </Card>

              <div className="flex flex-col justify-between gap-3 rounded-2xl border border-stone-200/80 bg-white p-4 sm:flex-row sm:items-center">
                <div>
                  <p className="text-sm font-bold text-ink">文档管理</p>
                  <p className="mt-1 text-xs text-stone-400">可重命名、调整用途、重新解析；归档内容不会参与出题。</p>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  aria-pressed={showArchived}
                  onClick={() => setShowArchived((value) => !value)}
                >
                  {showArchived ? <FileText aria-hidden="true" className="h-3.5 w-3.5" /> : <Archive aria-hidden="true" className="h-3.5 w-3.5" />}
                  {showArchived ? '查看使用中' : '查看已归档'}
                  <Badge>{archivedDocuments.length}</Badge>
                </Button>
              </div>

              {documents.isLoading ? <PageLoader label="正在读取文档…" /> : null}
              {documents.error ? <ErrorState message={toErrorMessage(documents.error)} onRetry={() => void documents.refetch()} /> : null}
              {!documents.isLoading && !documents.error && showArchived ? (
                <section aria-labelledby="archived-title">
                  <div className="mb-3">
                    <h2 id="archived-title" className="font-bold text-ink">已归档</h2>
                    <p className="mt-1 text-xs leading-5 text-stone-400">归档文档已从出题资料中移除，恢复后会保留原解析结果。</p>
                  </div>
                  <Card className="overflow-hidden">
                    {archivedDocuments.length ? (
                      <ul className="divide-y divide-stone-100">
                        {archivedDocuments.map((document) => {
                          const Icon = fileIcon(document);
                          const restoring = updateDocument.isPending && updateDocument.variables?.id === document.id;
                          return (
                            <li key={document.id} className="p-4 sm:p-5">
                              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                                <div className="flex min-w-0 items-start gap-3">
                                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-stone-100 text-stone-400">
                                    <Icon aria-hidden="true" className="h-5 w-5" />
                                  </span>
                                  <div className="min-w-0">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <p className="truncate text-sm font-semibold text-ink">{document.name || document.original_filename}</p>
                                      <StatusBadge status="archived" />
                                    </div>
                                    <p className="mt-1 text-xs text-stone-400">
                                      {document.role === 'source' ? '权威正文' : '重点 / 大纲'} · {formatBytes(document.size_bytes)}
                                    </p>
                                  </div>
                                </div>
                                <Button
                                  type="button"
                                  variant="secondary"
                                  size="sm"
                                  loading={restoring}
                                  onClick={() => updateDocument.mutate({
                                    id: document.id,
                                    payload: { archived: false },
                                    successMessage: '文档已恢复',
                                  })}
                                >
                                  <ArchiveRestore aria-hidden="true" className="h-3.5 w-3.5" />
                                  恢复
                                </Button>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    ) : (
                      <div className="px-5 py-12 text-center text-sm text-stone-400">还没有归档文档</div>
                    )}
                  </Card>
                </section>
              ) : null}

              {!documents.isLoading && !documents.error && !showArchived ? (
                <div className="grid gap-6 2xl:grid-cols-2">
                  {([
                    ['source', '权威正文', '题目、答案和解析必须从这里找到可靠证据。'],
                    ['outline', '重点 / 考试大纲', '帮助 AI 理解考点与重要程度，默认不单独作为答案依据。'],
                  ] as const).map(([group, title, description]) => (
                    <section key={group} aria-labelledby={`${group}-title`}>
                      <div className="mb-3 flex items-end justify-between gap-3">
                        <div>
                          <h2 id={`${group}-title`} className="font-bold text-ink">{title}</h2>
                          <p className="mt-1 text-xs leading-5 text-stone-400">{description}</p>
                        </div>
                        <Badge tone={group === 'source' ? 'success' : 'violet'}>{documentGroups[group].length} 份</Badge>
                      </div>
                      <Card className="overflow-hidden">
                        {documentGroups[group].length ? (
                          <ul className="divide-y divide-stone-100">
                            {documentGroups[group].map((document) => {
                              const Icon = fileIcon(document);
                              const updating = updateDocument.isPending && updateDocument.variables?.id === document.id;
                              const reparsing = parseDocument.isPending && parseDocument.variables === document.id;
                              const parsing = ['queued', 'parsing'].includes(document.status);
                              return (
                                <li key={document.id} className="p-4 sm:p-5">
                                  <div className="flex items-start gap-3">
                                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-stone-100 text-stone-500">
                                      <Icon aria-hidden="true" className="h-5 w-5" />
                                    </span>
                                    <div className="min-w-0 flex-1">
                                      <div className="flex flex-wrap items-center gap-2">
                                        <p className="min-w-0 truncate text-sm font-semibold text-ink">{document.name || document.original_filename}</p>
                                        <StatusBadge status={document.status} />
                                      </div>
                                      <p className="mt-1 text-xs text-stone-400">
                                        {formatBytes(document.size_bytes)} · {document.page_count ? `${document.page_count} 页 · ` : ''}{formatDate(document.created_at)}
                                      </p>
                                      {parsing ? <Progress className="mt-3" value={document.progress} label="解析文档" /> : null}
                                      {document.error ? (
                                        <p className="mt-2 flex items-start gap-1.5 text-xs leading-5 text-red-600">
                                          <AlertTriangle aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                          {document.error}
                                        </p>
                                      ) : null}
                                      {document.warnings?.length ? (
                                        <p className="mt-2 text-xs leading-5 text-amber-600">{document.warnings.join('；')}</p>
                                      ) : null}

                                      <div className="mt-3 grid gap-2 sm:flex sm:flex-wrap sm:items-center">
                                        <Select
                                          selectSize="sm"
                                          containerClassName="w-full sm:w-36"
                                          value={document.role}
                                          disabled={updating}
                                          aria-label={`修改 ${document.name} 的资料角色`}
                                          onChange={(event) => {
                                            const nextRole = event.target.value as DocumentRole;
                                            updateDocument.mutate({
                                              id: document.id,
                                              payload: nextRole === 'source'
                                                ? { role: nextRole, allow_as_evidence: true }
                                                : { role: nextRole, allow_as_evidence: false },
                                              successMessage: '资料角色已更新',
                                            });
                                          }}
                                        >
                                          <option value="source">权威正文</option>
                                          <option value="outline">重点 / 大纲</option>
                                        </Select>
                                        <label className="flex min-h-10 items-center gap-2 rounded-lg border border-stone-200 px-3 text-xs text-stone-500 sm:border-0 sm:px-1">
                                          <input
                                            type="checkbox"
                                            className="h-4 w-4 rounded border-stone-300 text-pine-600 focus:ring-pine-500"
                                            checked={document.role === 'source' || document.allow_as_evidence}
                                            disabled={document.role === 'source' || updating}
                                            onChange={(event) => updateDocument.mutate({
                                              id: document.id,
                                              payload: { allow_as_evidence: event.target.checked },
                                              successMessage: '答案依据设置已更新',
                                            })}
                                          />
                                          可作答案依据
                                        </label>
                                        {document.status === 'ready' ? (
                                          <span className="text-xs font-semibold text-pine-600 sm:ml-auto">
                                            <Check aria-hidden="true" className="mr-1 inline h-3.5 w-3.5" />
                                            {document.chunk_count ?? 0} 个证据块
                                          </span>
                                        ) : null}
                                      </div>

                                      <div className="mt-3 flex flex-wrap gap-1 border-t border-stone-100 pt-3">
                                        <Button type="button" variant="ghost" size="sm" onClick={() => startEditing(document)}>
                                          <FilePenLine aria-hidden="true" className="h-3.5 w-3.5" />
                                          编辑
                                        </Button>
                                        <Button
                                          type="button"
                                          variant="ghost"
                                          size="sm"
                                          loading={reparsing}
                                          disabled={parsing}
                                          onClick={() => parseDocument.mutate(document.id)}
                                        >
                                          <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" />
                                          重新解析
                                        </Button>
                                        <Button type="button" variant="danger" size="sm" onClick={() => setArchiveTarget(document)}>
                                          <Archive aria-hidden="true" className="h-3.5 w-3.5" />
                                          归档
                                        </Button>
                                      </div>
                                    </div>
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        ) : (
                          <div className="px-5 py-12 text-center text-sm text-stone-400">尚未添加{title}</div>
                        )}
                      </Card>
                    </section>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>

      <DocumentEditDialog
        document={editingDocument}
        draft={editDraft}
        busy={updateDocument.isPending}
        onDraftChange={setEditDraft}
        onClose={() => setEditingDocument(null)}
        onSave={() => {
          if (!editingDocument || !editDraft.name.trim()) return;
          updateDocument.mutate({
            id: editingDocument.id,
            payload: {
              name: editDraft.name.trim(),
              role: editDraft.role,
              allow_as_evidence: editDraft.role === 'source' || editDraft.allowAsEvidence,
            },
            successMessage: '文档信息已保存',
            closeEditor: true,
          });
        }}
      />

      <ArchiveDocumentDialog
        document={archiveTarget}
        busy={archiveDocument.isPending}
        onClose={() => setArchiveTarget(null)}
        onConfirm={() => {
          if (archiveTarget) archiveDocument.mutate(archiveTarget.id);
        }}
      />
    </div>
  );
}
