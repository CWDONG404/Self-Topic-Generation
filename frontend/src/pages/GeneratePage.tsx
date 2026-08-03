import { useMutation, useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  BookOpenCheck,
  BrainCircuit,
  Check,
  Cloud,
  Cpu,
  FileText,
  Info,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  WandSparkles,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { PageHeader } from '../components/PageHeader';
import { Badge } from '../components/ui/Badge';
import { Button, buttonVariants } from '../components/ui/Button';
import { Card, CardBody, CardHeader } from '../components/ui/Card';
import { Select } from '../components/ui/Select';
import { ErrorState, PageLoader } from '../components/ui/States';
import { api } from '../lib/api';
import { allocateByLargestRemainder } from '../lib/quota';
import { cn, toErrorMessage } from '../lib/utils';
import type { GenerationRequest, ModelProfile, ModelRole } from '../types/api';

export function isLocalModelUrl(baseUrl: string) {
  try {
    const host = new URL(baseUrl).hostname.toLowerCase();
    if (['localhost', '127.0.0.1', '::1', 'host.docker.internal', 'ollama'].includes(host)) return true;
    if (host.endsWith('.local') || host.startsWith('10.') || host.startsWith('192.168.')) return true;
    const match = /^172\.(\d{1,3})\./.exec(host);
    return Boolean(match && Number(match[1]) >= 16 && Number(match[1]) <= 31);
  } catch {
    return false;
  }
}

export function modelSupportsRole(profile: ModelProfile, role: ModelRole) {
  if (role === 'vision') return profile.capabilities.vision;
  if (role === 'embedding') return profile.capabilities.embedding;
  return profile.capabilities.structured_output;
}

export function isModelEligible(
  profile: ModelProfile,
  role: ModelRole,
  executionMode: GenerationRequest['execution_mode'],
) {
  return profile.is_available !== false
    && modelSupportsRole(profile, role)
    && (executionMode !== 'local_only' || isLocalModelUrl(profile.base_url));
}

const modelRoleMeta: Array<{ key: ModelRole; label: string; icon: typeof BrainCircuit; required?: boolean }> = [
  { key: 'blueprint', label: '考点蓝图', icon: BrainCircuit, required: true },
  { key: 'generator', label: '出题', icon: WandSparkles, required: true },
  { key: 'reviewer', label: '独立审题', icon: ShieldCheck, required: true },
  { key: 'vision', label: '图像理解', icon: FileText },
  { key: 'embedding', label: '向量检索', icon: BookOpenCheck },
];

const CISE_V42_DISTRIBUTION = [
  ['信息安全保障', 10],
  ['网络安全监管', 8],
  ['信息安全管理', 10],
  ['业务连续性', 8],
  ['安全工程与运营', 10],
  ['安全评估', 8],
  ['信息安全支撑技术', 10],
  ['物理与网络通信安全', 12],
  ['计算环境安全', 12],
  ['软件安全开发', 12],
] as const;

const ciseTopicDistribution = Object.fromEntries(CISE_V42_DISTRIBUTION) as Record<string, number>;

function redistribute(ids: string[]) {
  if (!ids.length) return {};
  const base = Math.floor(100 / ids.length);
  const remainder = 100 - base * ids.length;
  return Object.fromEntries(ids.map((id, index) => [id, base + (index < remainder ? 1 : 0)]));
}

export function GeneratePage() {
  const navigate = useNavigate();
  const libraries = useQuery({ queryKey: ['libraries'], queryFn: api.listLibraries });
  const models = useQuery({ queryKey: ['model-profiles'], queryFn: api.listModelProfiles });
  const [libraryId, setLibraryId] = useState('');
  const activeLibraryId = libraryId || libraries.data?.[0]?.id || '';
  const documents = useQuery({
    queryKey: ['documents', activeLibraryId],
    queryFn: () => api.listDocuments(activeLibraryId),
    enabled: Boolean(activeLibraryId),
    refetchInterval: (query) =>
      query.state.data?.some((item) => ['queued', 'parsing'].includes(item.status)) ? 3_000 : false,
  });
  const [outlineIds, setOutlineIds] = useState<string[]>([]);
  const [allocations, setAllocations] = useState<Record<string, number>>({});
  const [questionCount, setQuestionCount] = useState(50);
  const [executionMode, setExecutionMode] = useState<GenerationRequest['execution_mode']>('cloud_allowed');
  const [modelRoles, setModelRoles] = useState<Partial<Record<ModelRole, string>>>({});
  const [randomSeed, setRandomSeed] = useState('');
  const [examPreset, setExamPreset] = useState<'cise_v4_2' | ''>('');

  useEffect(() => {
    setOutlineIds([]);
    setAllocations({});
  }, [activeLibraryId]);

  const readyDocuments = documents.data?.filter((item) => ['ready', 'warning'].includes(item.status)) ?? [];
  const parsingDocuments = documents.data?.filter((item) => ['queued', 'parsing'].includes(item.status)) ?? [];
  const outlines = readyDocuments.filter((item) => item.role === 'outline');
  const sources = readyDocuments.filter((item) => item.role === 'source' || item.allow_as_evidence);
  const availableModels = useMemo(
    () => models.data?.filter((profile) => profile.is_available !== false) ?? [],
    [models.data],
  );
  const eligibleModelsByRole = useMemo(
    () => Object.fromEntries(
      modelRoleMeta.map(({ key }) => [
        key,
        availableModels.filter((profile) => isModelEligible(profile, key, executionMode)),
      ]),
    ) as Record<ModelRole, ModelProfile[]>,
    [availableModels, executionMode],
  );
  const unavailableModelCount = (models.data?.length ?? 0) - availableModels.length;
  const selectedSourceIds = Object.keys(allocations);
  const totalPercentage = Object.values(allocations).reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0);
  const quotaPreview = useMemo(() => {
    if (totalPercentage !== 100 || !selectedSourceIds.length) return [];
    try {
      return allocateByLargestRemainder(
        questionCount,
        selectedSourceIds.map((id) => ({ id, percentage: allocations[id] })),
      );
    } catch {
      return [];
    }
  }, [allocations, questionCount, selectedSourceIds, totalPercentage]);

  useEffect(() => {
    setModelRoles((current) => {
      const next = { ...current };
      let changed = false;
      for (const role of modelRoleMeta) {
        const choices = eligibleModelsByRole[role.key];
        const currentId = next[role.key];
        if (currentId && choices.some((profile) => profile.id === currentId)) continue;
        const defaultProfile = choices.find((profile) => profile.default_roles?.includes(role.key));
        if (defaultProfile) next[role.key] = defaultProfile.id;
        else delete next[role.key];
        if (currentId !== next[role.key]) changed = true;
      }
      return changed ? next : current;
    });
  }, [eligibleModelsByRole]);

  const requiredRolesReady = modelRoleMeta
    .filter((item) => item.required)
    .every((item) => {
      const selectedId = modelRoles[item.key];
      return Boolean(selectedId && eligibleModelsByRole[item.key].some((profile) => profile.id === selectedId));
    });
  const localModelsValid =
    executionMode !== 'local_only' ||
    Object.entries(modelRoles)
      .filter(([, profileId]) => Boolean(profileId))
      .every(([, profileId]) => {
        const profile = models.data?.find((item) => item.id === profileId);
        return Boolean(profile && isLocalModelUrl(profile.base_url));
      });
  const canSubmit =
    Boolean(activeLibraryId) &&
    selectedSourceIds.length > 0 &&
    totalPercentage === 100 &&
    questionCount >= 10 &&
    questionCount <= 500 &&
    requiredRolesReady &&
    localModelsValid;

  const createJob = useMutation({
    mutationFn: () => {
      const payload: GenerationRequest = {
        library_id: activeLibraryId,
        outline_document_ids: outlineIds,
        source_allocations: selectedSourceIds.map((documentId) => ({
          document_id: documentId,
          percentage: allocations[documentId],
        })),
        question_count: questionCount,
        execution_mode: executionMode,
        model_roles: modelRoles,
        allow_outline_as_evidence: selectedSourceIds.some(
          (documentId) => readyDocuments.find((item) => item.id === documentId)?.role === 'outline',
        ),
        ...(examPreset ? {
          exam_preset: examPreset,
          topic_distribution: ciseTopicDistribution,
        } : {}),
        ...(randomSeed ? { random_seed: Number(randomSeed) } : {}),
      };
      return api.createGenerationJob(payload);
    },
    onSuccess: (job) => {
      toast.success('出题任务已进入队列');
      navigate(`/jobs/${job.id}`);
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const toggleSource = (id: string) => {
    const nextIds = selectedSourceIds.includes(id)
      ? selectedSourceIds.filter((item) => item !== id)
      : [...selectedSourceIds, id];
    setAllocations(redistribute(nextIds));
  };

  if (libraries.isLoading || models.isLoading) return <PageLoader label="正在准备出题向导…" />;
  const pageError = libraries.error || models.error;
  if (pageError) return <ErrorState message={toErrorMessage(pageError)} onRetry={() => { void libraries.refetch(); void models.refetch(); }} />;

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="生成向导"
        title="创建一套新模拟卷"
        description="先决定考什么，再分配各资料的题量。系统会在后台完成证据检索、出题、审查与去重。"
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <form
          id="generation-form"
          className="min-w-0 space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (canSubmit) createJob.mutate();
          }}
        >
          <Card>
            <CardHeader className="flex items-center gap-3">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-pine-700 text-sm font-bold text-white">1</span>
              <div>
                <h2 className="font-bold text-ink">选择资料空间</h2>
                <p className="mt-0.5 text-xs text-stone-400">只会使用已完成解析的文档</p>
              </div>
            </CardHeader>
            <CardBody>
              {libraries.data?.length ? (
                <Select value={activeLibraryId} onChange={(event) => setLibraryId(event.target.value)} aria-label="选择资料库">
                  {libraries.data.map((library) => <option key={library.id} value={library.id}>{library.name}</option>)}
                </Select>
              ) : (
                <div className="rounded-xl bg-amber-50 p-4 text-sm text-amber-600">
                  还没有资料库。<Link className="font-bold underline" to="/knowledge">先去创建并上传资料</Link>
                </div>
              )}
              {documents.isLoading ? <div className="mt-4 text-sm text-stone-400">读取资料中…</div> : null}
              {documents.error ? <p className="mt-3 text-sm text-red-600">{toErrorMessage(documents.error)}</p> : null}
              {parsingDocuments.length ? (
                <div className="mt-3 flex flex-col gap-2 rounded-xl border border-sky-100 bg-sky-50 p-3 text-xs leading-5 text-sky-700 sm:flex-row sm:items-center sm:justify-between">
                  <span>
                    {parsingDocuments.length} 份文档仍在解析，页面每 3 秒自动刷新；完成后会自动出现在下方。
                  </span>
                  <Button type="button" variant="secondary" size="sm" onClick={() => void documents.refetch()} disabled={documents.isFetching}>
                    <RefreshCw aria-hidden="true" className={cn('h-3.5 w-3.5', documents.isFetching && 'animate-spin')} />
                    立即刷新
                  </Button>
                </div>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader className="flex items-center gap-3">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-pine-700 text-sm font-bold text-white">2</span>
              <div>
                <h2 className="font-bold text-ink">告诉 AI 重点在哪里</h2>
                <p className="mt-0.5 text-xs text-stone-400">可多选，也可以不选；重点资料不会改变正文证据规则</p>
              </div>
            </CardHeader>
            <CardBody>
              {outlines.length ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  {outlines.map((document) => {
                    const selected = outlineIds.includes(document.id);
                    return (
                      <button
                        key={document.id}
                        type="button"
                        aria-pressed={selected}
                        onClick={() => setOutlineIds((ids) => selected ? ids.filter((id) => id !== document.id) : [...ids, document.id])}
                        className={cn(
                          'flex min-h-14 items-center gap-3 rounded-xl border p-3 text-left transition',
                          selected ? 'border-violet-300 bg-violet-50' : 'border-stone-200 hover:border-stone-300',
                        )}
                      >
                        <span className={cn('grid h-6 w-6 shrink-0 place-items-center rounded-full border', selected ? 'border-violet-500 bg-violet-500 text-white' : 'border-stone-300 text-transparent')}>
                          <Check aria-hidden="true" className="h-3.5 w-3.5" />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-ink">{document.name}</span>
                          <span className="text-xs text-stone-400">重点 / 大纲</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <p className="rounded-xl border border-dashed border-stone-200 p-5 text-center text-sm text-stone-400">当前资料库没有已就绪的重点资料，将直接根据正文规划考点。</p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader className="flex items-center gap-3">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-pine-700 text-sm font-bold text-white">3</span>
              <div>
                <h2 className="font-bold text-ink">分配正文题量</h2>
                <p className="mt-0.5 text-xs text-stone-400">选中文档后设置整数比例，总和必须为 100%</p>
              </div>
            </CardHeader>
            <CardBody>
              {sources.length ? (
                <div className="space-y-2">
                  {sources.map((document) => {
                    const selected = selectedSourceIds.includes(document.id);
                    const count = quotaPreview.find((item) => item.id === document.id)?.count;
                    return (
                      <div key={document.id} className={cn('rounded-xl border p-3 transition sm:flex sm:items-center sm:gap-4', selected ? 'border-pine-200 bg-pine-50/60' : 'border-stone-200')}>
                        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => toggleSource(document.id)}
                            className="h-4 w-4 rounded border-stone-300 text-pine-600 focus:ring-pine-500"
                          />
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-semibold text-ink">{document.name}</span>
                            <span className="text-xs text-stone-400">{document.page_count ? `${document.page_count} 页` : '正文材料'}</span>
                          </span>
                        </label>
                        {selected ? (
                          <div className="mt-3 flex items-center gap-2 pl-7 sm:mt-0 sm:pl-0">
                            <label htmlFor={`allocation-${document.id}`} className="text-xs font-semibold text-stone-500">占比</label>
                            <div className="relative">
                              <input
                                id={`allocation-${document.id}`}
                                type="number"
                                min={0}
                                max={100}
                                step={1}
                                value={allocations[document.id]}
                                onChange={(event) => setAllocations((current) => ({ ...current, [document.id]: Number(event.target.value) }))}
                                className="h-9 w-20 rounded-lg border border-stone-200 bg-white pl-3 pr-7 text-right text-sm font-bold"
                              />
                              <span className="pointer-events-none absolute right-2 top-2 text-xs text-stone-400">%</span>
                            </div>
                            {count != null ? <Badge tone="success">{count} 题</Badge> : null}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                  <div className={cn('mt-3 flex items-center justify-between rounded-xl px-4 py-3 text-sm font-semibold', totalPercentage === 100 ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-600')}>
                    <span>{totalPercentage === 100 ? '比例校验通过' : '比例之和需要等于 100%'}</span>
                    <span className="text-lg">{totalPercentage}%</span>
                  </div>
                </div>
              ) : (
                <p className="rounded-xl border border-dashed border-amber-200 bg-amber-50 p-5 text-center text-sm text-amber-600">没有可作为答案依据的就绪正文，请先到资料库上传或完成解析。</p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader className="flex items-center gap-3">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-pine-700 text-sm font-bold text-white">4</span>
              <div>
                <h2 className="font-bold text-ink">选择考试蓝图</h2>
                <p className="mt-0.5 text-xs text-stone-400">预设控制同一份资料内部的知识域题量</p>
              </div>
            </CardHeader>
            <CardBody className="space-y-3">
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setExamPreset('')}
                  className={cn('rounded-xl border p-4 text-left transition', !examPreset ? 'border-pine-500 bg-pine-50' : 'border-stone-200')}
                >
                  <span className="block text-sm font-bold text-ink">根据资料自动规划</span>
                  <span className="mt-1 block text-xs leading-5 text-stone-400">由蓝图 Agent 根据重点材料分配知识点</span>
                </button>
                <button
                  type="button"
                  onClick={() => { setExamPreset('cise_v4_2'); setQuestionCount(100); }}
                  className={cn('rounded-xl border p-4 text-left transition', examPreset === 'cise_v4_2' ? 'border-pine-500 bg-pine-50' : 'border-stone-200')}
                >
                  <span className="flex items-center gap-2 text-sm font-bold text-ink">CISE V4.2 标准卷 <Badge tone="success">推荐</Badge></span>
                  <span className="mt-1 block text-xs leading-5 text-stone-400">100 道单选题，每题 1 分，严格按官方十个知识域比例</span>
                </button>
              </div>
              {examPreset === 'cise_v4_2' ? (
                <div className="grid gap-2 rounded-xl border border-pine-100 bg-pine-50/60 p-3 sm:grid-cols-2">
                  {CISE_V42_DISTRIBUTION.map(([name, percentage]) => (
                    <div key={name} className="flex items-center justify-between gap-3 text-xs">
                      <span className="truncate text-stone-600">{name}</span>
                      <span className="shrink-0 font-bold text-pine-700">{percentage}% · {Math.round(questionCount * percentage / 100)} 题</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader className="flex items-center gap-3">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-pine-700 text-sm font-bold text-white">5</span>
              <div>
                <h2 className="font-bold text-ink">题量与模型</h2>
                <p className="mt-0.5 text-xs text-stone-400">按角色指定模型；本地模式不会回退到云端</p>
              </div>
            </CardHeader>
            <CardBody className="space-y-6">
              <div>
                <label className="field-label" htmlFor="question-count">试卷题量</label>
                <div className="flex flex-wrap gap-2">
                  {[50, 100].map((count) => (
                    <button
                      key={count}
                      type="button"
                      onClick={() => setQuestionCount(count)}
                      className={cn('h-11 min-w-20 rounded-xl border px-4 text-sm font-bold', questionCount === count ? 'border-pine-500 bg-pine-50 text-pine-700' : 'border-stone-200 bg-white text-stone-500')}
                    >
                      {count} 题
                    </button>
                  ))}
                  <input
                    id="question-count"
                    type="number"
                    min={10}
                    max={500}
                    value={questionCount}
                    onChange={(event) => setQuestionCount(Number(event.target.value))}
                    className="field-control w-28"
                    aria-label="自定义题量"
                  />
                </div>
              </div>

              <fieldset>
                <legend className="field-label">执行模式</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {([
                    ['cloud_allowed', '云端可用', '允许使用 OpenAI 兼容接口或 Ollama', Cloud],
                    ['local_only', '仅本地', '只连接本机、局域网或 Docker 内模型', Cpu],
                  ] as const).map(([value, label, description, Icon]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setExecutionMode(value)}
                      className={cn('flex items-start gap-3 rounded-xl border p-4 text-left transition', executionMode === value ? 'border-pine-500 bg-pine-50' : 'border-stone-200')}
                    >
                      <Icon aria-hidden="true" className={cn('mt-0.5 h-5 w-5', executionMode === value ? 'text-pine-700' : 'text-stone-400')} />
                      <span>
                        <span className="block text-sm font-bold text-ink">{label}</span>
                        <span className="mt-1 block text-xs leading-5 text-stone-400">{description}</span>
                      </span>
                    </button>
                  ))}
                </div>
                {!localModelsValid ? <p className="mt-2 text-xs font-semibold text-red-600">仅本地模式不能选择云端模型。</p> : null}
              </fieldset>

              {availableModels.length ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {modelRoleMeta.map(({ key, label, icon: Icon, required }) => {
                    const choices = eligibleModelsByRole[key];
                    return (
                      <label key={key}>
                        <span className="mb-2 flex items-center gap-2 text-xs font-bold text-stone-600">
                          <Icon aria-hidden="true" className="h-3.5 w-3.5" />
                          {label}{required ? <span className="text-red-500">*</span> : null}
                        </span>
                        <Select
                          value={modelRoles[key] ?? ''}
                          disabled={!choices.length}
                          aria-invalid={required && !modelRoles[key] ? true : undefined}
                          onChange={(event) => setModelRoles((current) => ({ ...current, [key]: event.target.value || undefined }))}
                        >
                          <option value="">
                            {choices.length ? (required ? '请选择模型' : '不启用') : '没有符合能力要求的模型'}
                          </option>
                          {choices.map((profile) => (
                            <option key={profile.id} value={profile.id}>
                              {profile.name} · {profile.model_name} ({isLocalModelUrl(profile.base_url) ? '本地' : '云端'})
                            </option>
                          ))}
                        </Select>
                        {!choices.length ? (
                          <span className="mt-1.5 block text-xs leading-5 text-amber-600">
                            {key === 'vision' ? '需要开启“视觉理解”能力。' : key === 'embedding' ? '需要开启“Embedding”能力。' : '需要可用且支持结构化输出的模型。'}
                          </span>
                        ) : null}
                      </label>
                    );
                  })}
                  {unavailableModelCount > 0 ? (
                    <p className="sm:col-span-2 text-xs leading-5 text-stone-400">
                      已隐藏 {unavailableModelCount} 个停用模型；当前角色列表也会自动排除能力不匹配及不符合“仅本地”要求的模型。
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-xl bg-amber-50 p-4 text-sm text-amber-600">
                  {models.data?.length ? '所有模型均已停用。' : '尚未配置模型。'}
                  <Link to="/settings" className="ml-1 font-bold underline">前往模型设置</Link>
                </div>
              )}

              <div>
                <label htmlFor="random-seed" className="field-label">随机种子 <span className="font-normal text-stone-400">（可选）</span></label>
                <div className="flex gap-2">
                  <input id="random-seed" type="number" min={0} value={randomSeed} onChange={(event) => setRandomSeed(event.target.value)} placeholder="留空则自动生成" className="field-control" />
                  <Button type="button" variant="secondary" size="icon" aria-label="生成随机种子" onClick={() => setRandomSeed(String(Math.floor(Math.random() * 2_147_483_647)))}>
                    <RefreshCw aria-hidden="true" className="h-4 w-4" />
                  </Button>
                </div>
                <p className="field-help">保存种子便于复现检索与随机采样；历史题干仍会参与永久去重。</p>
              </div>
            </CardBody>
          </Card>
        </form>

        <aside className="space-y-4 xl:sticky xl:top-8">
          <Card className="overflow-hidden">
            <div className="bg-pine-900 px-5 py-4 text-white">
              <div className="flex items-center gap-2 text-sm font-bold"><Sparkles className="h-4 w-4" />出题摘要</div>
            </div>
            <CardBody className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-stone-50 p-3"><p className="text-xs text-stone-400">目标题量</p><p className="mt-1 text-2xl font-bold text-ink">{questionCount}</p></div>
                <div className="rounded-xl bg-stone-50 p-3"><p className="text-xs text-stone-400">正文资料</p><p className="mt-1 text-2xl font-bold text-ink">{selectedSourceIds.length}</p></div>
              </div>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-3"><dt className="text-stone-400">重点资料</dt><dd className="font-semibold text-ink">{outlineIds.length} 份</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-stone-400">比例总和</dt><dd className={cn('font-semibold', totalPercentage === 100 ? 'text-pine-600' : 'text-amber-600')}>{totalPercentage}%</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-stone-400">考试蓝图</dt><dd className="font-semibold text-ink">{examPreset === 'cise_v4_2' ? 'CISE V4.2' : '自动规划'}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-stone-400">运行位置</dt><dd className="font-semibold text-ink">{executionMode === 'local_only' ? '仅本地' : '云端可用'}</dd></div>
              </dl>
              <div className="rounded-xl border border-pine-100 bg-pine-50 p-3 text-xs leading-5 text-pine-700">
                <Info aria-hidden="true" className="mr-1 inline h-3.5 w-3.5" />
                正常证据充足时会严格达到题量；不足时交付部分试卷并标明缺口，不会编造答案。
              </div>
              <Button type="submit" form="generation-form" size="lg" className="w-full" disabled={!canSubmit} loading={createJob.isPending}>
                启动 Multi-Agent 出题
                <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </Button>
              {!canSubmit ? <p className="text-center text-xs leading-5 text-stone-400">完成正文比例与必选模型后即可开始</p> : null}
            </CardBody>
          </Card>
          <Link to="/settings" className={cn(buttonVariants({ variant: 'ghost' }), 'w-full')}>
            管理模型配置
          </Link>
        </aside>
      </div>
    </div>
  );
}
