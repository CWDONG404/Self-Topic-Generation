import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  Cloud,
  Copy,
  Cpu,
  Download,
  Eye,
  KeyRound,
  Pencil,
  Server,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wifi,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { PageHeader } from '../components/PageHeader';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card, CardBody, CardHeader } from '../components/ui/Card';
import { ErrorState, PageLoader } from '../components/ui/States';
import { api } from '../lib/api';
import { cn, formatDate, toErrorMessage } from '../lib/utils';
import type { ModelProfile, ModelProvider, ModelRole } from '../types/api';

type SetupKind = 'kimi' | 'ollama' | 'custom';
type OllamaLocation = 'host' | 'compose';

const roles: Array<{ key: ModelRole; label: string; description: string }> = [
  { key: 'blueprint', label: '考点蓝图', description: '理解重点与规划知识点' },
  { key: 'generator', label: '出题', description: '生成题干、选项与解析' },
  { key: 'reviewer', label: '审题', description: '独立复核答案与证据' },
  { key: 'vision', label: '视觉', description: '读取图片、表格和流程图' },
  { key: 'embedding', label: 'Embedding', description: '向量检索与证据召回' },
];

const initialForm = {
  name: 'Kimi K3',
  provider: 'openai_compatible' as ModelProvider,
  base_url: 'https://api.kimi.com/coding/v1',
  model_name: 'k3-256k',
  api_key: '',
  structured_output: true,
  vision: true,
  embedding: false,
  default_roles: ['blueprint', 'generator', 'reviewer', 'vision'] as ModelRole[],
};

const setupOptions: Array<{
  key: SetupKind;
  title: string;
  description: string;
  badge?: string;
  icon: typeof Cloud;
}> = [
  { key: 'kimi', title: 'Kimi', description: '只填 API Key，系统自动分配 Agent。', badge: '最省事', icon: Cloud },
  { key: 'ollama', title: 'Ollama', description: '连接已经下载到本机或 Docker 的模型。', icon: Cpu },
  { key: 'custom', title: '其他接口', description: '填写 OpenAI 兼容接口的完整参数。', icon: Server },
];

const localBundle = [
  {
    name: 'Ollama 文本主模型',
    model_name: 'qwen3:8b',
    purpose: '考点蓝图、出题、审题',
    capabilities: { structured_output: true, vision: false, embedding: false },
    default_roles: ['blueprint', 'generator', 'reviewer'] as ModelRole[],
  },
  {
    name: 'Ollama 视觉模型',
    model_name: 'qwen3-vl:4b',
    purpose: '图片、表格、流程图理解',
    capabilities: { structured_output: true, vision: true, embedding: false },
    default_roles: ['vision'] as ModelRole[],
  },
  {
    name: 'Ollama 向量模型',
    model_name: 'qwen3-embedding:0.6b',
    purpose: '语义检索与证据召回',
    capabilities: { structured_output: false, vision: false, embedding: true },
    default_roles: ['embedding'] as ModelRole[],
  },
];

function formForKind(kind: SetupKind, location: OllamaLocation) {
  if (kind === 'kimi') return { ...initialForm, api_key: '' };
  if (kind === 'ollama') {
    return {
      ...initialForm,
      name: 'Ollama 文本主模型',
      provider: 'ollama' as ModelProvider,
      base_url: location === 'host' ? 'http://host.docker.internal:11434' : 'http://ollama:11434',
      model_name: 'qwen3:8b',
      api_key: '',
      vision: false,
      default_roles: ['blueprint', 'generator', 'reviewer'] as ModelRole[],
    };
  }
  return {
    ...initialForm,
    name: '',
    base_url: '',
    model_name: '',
    api_key: '',
    vision: false,
    default_roles: ['blueprint', 'generator', 'reviewer'] as ModelRole[],
  };
}

function setupKindForProfile(profile: ModelProfile): SetupKind {
  if (profile.provider === 'ollama') return 'ollama';
  return /api\.kimi\.com/i.test(profile.base_url) ? 'kimi' : 'custom';
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [setupKind, setSetupKind] = useState<SetupKind>('kimi');
  const [form, setForm] = useState(initialForm);
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
  const [editingHasApiKey, setEditingHasApiKey] = useState(false);
  const [ollamaLocation, setOllamaLocation] = useState<OllamaLocation>('host');
  const profiles = useQuery({ queryKey: ['model-profiles'], queryFn: api.listModelProfiles });

  const modelPayload = () => ({
    name: form.name.trim(),
    provider: form.provider,
    base_url: form.base_url.trim(),
    model_name: form.model_name.trim(),
    ...(form.api_key ? { api_key: form.api_key } : {}),
    capabilities: {
      structured_output: form.structured_output,
      vision: form.vision,
      embedding: form.embedding,
    },
    default_roles: form.default_roles,
  });

  const saveAndTest = useMutation({
    mutationFn: async () => {
      const profile = editingProfileId
        ? await api.updateModelProfile(editingProfileId, { ...modelPayload(), enabled: true })
        : await api.createModelProfile(modelPayload());
      try {
        return { profile, result: await api.testModelProfile(profile.id), testError: '' };
      } catch (error) {
        return { profile, result: null, testError: toErrorMessage(error) };
      }
    },
    onSuccess: ({ result, testError }) => {
      const edited = Boolean(editingProfileId);
      setEditingProfileId(null);
      setEditingHasApiKey(false);
      setForm(formForKind(setupKind, ollamaLocation));
      void queryClient.invalidateQueries({ queryKey: ['model-profiles'] });
      if (result?.ok) {
        toast.success(`${edited ? '配置已更新' : '配置已保存'}，连接成功${result.latency_ms ? ` · ${result.latency_ms} ms` : ''}`);
      } else {
        toast.warning(`配置已保存，但测试未通过：${result?.message || testError || '请检查地址、模型名和网络'}`);
      }
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const configureLocalBundle = useMutation({
    mutationFn: async () => {
      const baseUrl = ollamaLocation === 'host' ? 'http://host.docker.internal:11434' : 'http://ollama:11434';
      for (const item of localBundle) {
        const payload = {
          name: item.name,
          provider: 'ollama',
          base_url: baseUrl,
          model_name: item.model_name,
          capabilities: item.capabilities,
          default_roles: item.default_roles,
          enabled: true,
        };
        const existing = profiles.data?.find((profile) => profile.name === item.name);
        if (existing) await api.updateModelProfile(existing.id, payload);
        else await api.createModelProfile(payload);
      }
    },
    onSuccess: () => {
      toast.success('三条本地模型配置已写入；下载完成后请逐条测试');
      void queryClient.invalidateQueries({ queryKey: ['model-profiles'] });
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const remove = useMutation({
    mutationFn: api.deleteModelProfile,
    onSuccess: () => {
      toast.success('模型配置已删除');
      void queryClient.invalidateQueries({ queryKey: ['model-profiles'] });
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const test = useMutation({
    mutationFn: api.testModelProfile,
    onSuccess: (result) => {
      if (result.ok) toast.success(`连接成功${result.latency_ms ? ` · ${result.latency_ms} ms` : ''}`);
      else toast.error(result.message || '连接失败');
      void queryClient.invalidateQueries({ queryKey: ['model-profiles'] });
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  if (profiles.isLoading) return <PageLoader label="正在读取模型配置…" />;
  if (profiles.error) return <ErrorState message={toErrorMessage(profiles.error)} onRetry={() => void profiles.refetch()} />;

  const kimiKeyMissing = setupKind === 'kimi' && !form.api_key && !editingHasApiKey;
  const invalidRoleCombination = !form.structured_output
    && form.default_roles.some((role) => ['blueprint', 'generator', 'reviewer'].includes(role));
  const canSave = Boolean(form.name.trim() && form.base_url.trim() && form.model_name.trim())
    && !kimiKeyMissing
    && !invalidRoleCombination;
  const command = ollamaLocation === 'host'
    ? 'ollama pull qwen3:8b\nollama pull qwen3-vl:4b\nollama pull qwen3-embedding:0.6b'
    : 'docker compose --profile ollama up -d ollama\ndocker compose exec ollama ollama pull qwen3:8b\ndocker compose exec ollama ollama pull qwen3-vl:4b\ndocker compose exec ollama ollama pull qwen3-embedding:0.6b';

  const selectKind = (kind: SetupKind) => {
    setSetupKind(kind);
    setEditingProfileId(null);
    setEditingHasApiKey(false);
    setForm(formForKind(kind, ollamaLocation));
  };

  const startEditing = (profile: ModelProfile) => {
    const kind = setupKindForProfile(profile);
    setSetupKind(kind);
    setEditingProfileId(profile.id);
    setEditingHasApiKey(profile.has_api_key);
    setOllamaLocation(profile.base_url.includes('host.docker.internal') ? 'host' : 'compose');
    setForm({
      name: profile.name,
      provider: profile.provider,
      base_url: profile.base_url,
      model_name: profile.model_name,
      api_key: '',
      structured_output: profile.capabilities.structured_output,
      vision: profile.capabilities.vision,
      embedding: profile.capabilities.embedding,
      default_roles: profile.default_roles,
    });
    document.getElementById('model-profile-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="AI 基础设施"
        title="连接一个模型"
        description="先完成一条可用配置即可开始出题；角色分工和本地三模型方案都可以稍后设置。"
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(20rem,.85fr)]">
        <Card>
          <CardHeader className="border-b border-stone-100">
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-xl bg-pine-50 text-pine-700">
                <Sparkles aria-hidden="true" className="h-4 w-4" />
              </span>
              <div>
                <h2 className="font-bold text-ink">快速配置</h2>
                <p className="mt-0.5 text-xs text-stone-500">选择服务，系统自动填好常用参数与 Agent 分工。</p>
              </div>
            </div>
          </CardHeader>
          <CardBody>
            <fieldset>
              <legend className="field-label">你准备使用哪种模型？</legend>
              <div className="grid gap-2 sm:grid-cols-3">
                {setupOptions.map(({ key, title, description, badge, icon: Icon }) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={setupKind === key}
                    onClick={() => selectKind(key)}
                    className={cn(
                      'relative min-h-32 rounded-xl border p-4 text-left transition',
                      setupKind === key ? 'border-pine-500 bg-pine-50 shadow-sm' : 'border-stone-200 bg-white hover:border-pine-200',
                    )}
                  >
                    {badge ? <Badge className="absolute right-3 top-3" tone="success">{badge}</Badge> : null}
                    <Icon aria-hidden="true" className={cn('h-5 w-5', setupKind === key ? 'text-pine-700' : 'text-stone-400')} />
                    <span className="mt-3 block text-sm font-bold text-ink">{title}</span>
                    <span className="mt-1 block text-xs leading-5 text-stone-500">{description}</span>
                  </button>
                ))}
              </div>
            </fieldset>

            <form
              id="model-profile-form"
              className="mt-6 space-y-5 border-t border-stone-100 pt-6"
              onSubmit={(event) => {
                event.preventDefault();
                if (canSave) saveAndTest.mutate();
              }}
            >
              {editingProfileId ? (
                <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs text-amber-800">
                  <span className="font-semibold">正在编辑；API Key 留空会保留原密钥。</span>
                  <button type="button" className="shrink-0 font-bold hover:underline" onClick={() => selectKind(setupKind)}>取消</button>
                </div>
              ) : null}

              {setupKind === 'ollama' ? (
                <div>
                  <span className="field-label">Ollama 运行位置</span>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {([
                      ['host', 'Windows 本机', '使用 ollama list 中的模型'],
                      ['compose', '项目 Docker 内', '使用 Compose 中的 Ollama'],
                    ] as const).map(([value, label, description]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => {
                          setOllamaLocation(value);
                          setForm((current) => ({ ...current, base_url: value === 'host' ? 'http://host.docker.internal:11434' : 'http://ollama:11434' }));
                        }}
                        className={cn('rounded-xl border p-3 text-left transition', ollamaLocation === value ? 'border-pine-500 bg-pine-50' : 'border-stone-200')}
                      >
                        <span className="block text-sm font-bold text-ink">{label}</span>
                        <span className="mt-1 block text-xs text-stone-500">{description}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {setupKind === 'ollama' || setupKind === 'custom' ? (
                <label>
                  <span className="field-label">模型名</span>
                  <input
                    className="field-control font-mono text-xs"
                    placeholder={setupKind === 'ollama' ? '例如：qwen3:8b' : '服务商提供的模型 ID'}
                    value={form.model_name}
                    onChange={(event) => setForm({ ...form, model_name: event.target.value })}
                    autoCapitalize="none"
                    spellCheck={false}
                    required
                  />
                  {setupKind === 'ollama' ? <span className="field-help block">填写 `ollama list` 中完整的 NAME。</span> : null}
                </label>
              ) : (
                <div className="rounded-xl border border-pine-100 bg-pine-50/70 p-4">
                  <p className="text-sm font-bold text-pine-900">已预设 Kimi K3</p>
                  <p className="mt-1 text-xs leading-5 text-pine-700">考点蓝图、出题、审题和视觉共用；Embedding 可稍后单独添加。</p>
                </div>
              )}

              {form.provider === 'openai_compatible' ? (
                <label>
                  <span className="field-label">API Key</span>
                  <div className="relative">
                    <KeyRound aria-hidden="true" className="absolute left-3 top-3.5 h-4 w-4 text-stone-400" />
                    <input
                      type="password"
                      autoComplete="new-password"
                      className="field-control pl-10"
                      placeholder={editingHasApiKey ? '留空保留现有密钥' : '粘贴 API Key'}
                      value={form.api_key}
                      onChange={(event) => setForm({ ...form, api_key: event.target.value })}
                      required={setupKind === 'kimi' && !editingHasApiKey}
                    />
                  </div>
                  <span className="field-help block">保存后不再显示明文，也不会写入任务日志。</span>
                </label>
              ) : null}

              {setupKind === 'custom' ? (
                <label>
                  <span className="field-label">Base URL</span>
                  <input className="field-control font-mono text-xs" placeholder="https://api.example.com/v1" value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} inputMode="url" required />
                  <span className="field-help block">填写服务根地址，不要包含 `/chat/completions`。</span>
                </label>
              ) : null}

              <details className="group overflow-hidden rounded-xl border border-stone-200 bg-stone-50/50">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-stone-600 hover:bg-stone-50">
                  高级设置
                  <span className="flex items-center gap-2 text-xs font-normal text-stone-400">
                    名称、地址、能力与 Agent 分工
                    <ChevronDown aria-hidden="true" className="h-4 w-4 transition group-open:rotate-180" />
                  </span>
                </summary>
                <div className="space-y-5 border-t border-stone-200 bg-white p-4">
                  <label>
                    <span className="field-label">配置名称</span>
                    <input className="field-control" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required />
                  </label>
                  {setupKind !== 'custom' ? (
                    <label>
                      <span className="field-label">Base URL</span>
                      <input className="field-control font-mono text-xs" value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} required />
                    </label>
                  ) : null}
                  {setupKind === 'kimi' ? (
                    <label>
                      <span className="field-label">模型名</span>
                      <input className="field-control font-mono text-xs" value={form.model_name} onChange={(event) => setForm({ ...form, model_name: event.target.value })} required />
                    </label>
                  ) : null}

                  <fieldset>
                    <legend className="field-label">模型能力</legend>
                    <div className="grid gap-2 sm:grid-cols-3">
                      {([
                        ['structured_output', '结构化输出'],
                        ['vision', '视觉理解'],
                        ['embedding', 'Embedding'],
                      ] as const).map(([key, label]) => (
                        <label key={key} className="flex min-h-11 items-center gap-2 rounded-lg border border-stone-200 px-3 text-xs font-semibold text-stone-600">
                          <input type="checkbox" className="h-4 w-4 rounded border-stone-300 text-pine-600" checked={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.checked })} />
                          {label}
                        </label>
                      ))}
                    </div>
                  </fieldset>

                  <fieldset>
                    <legend className="field-label">默认 Agent 角色</legend>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {roles.map((role) => {
                        const active = form.default_roles.includes(role.key);
                        return (
                          <label key={role.key} className="flex cursor-pointer items-start gap-3 rounded-lg border border-stone-200 p-3">
                            <input
                              type="checkbox"
                              className="mt-0.5 h-4 w-4 rounded border-stone-300 text-pine-600"
                              checked={active}
                              onChange={() => setForm({ ...form, default_roles: active ? form.default_roles.filter((item) => item !== role.key) : [...form.default_roles, role.key] })}
                            />
                            <span>
                              <span className="block text-xs font-bold text-ink">{role.label}</span>
                              <span className="mt-0.5 block text-xs leading-5 text-stone-400">{role.description}</span>
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </fieldset>
                </div>
              </details>

              {invalidRoleCombination ? <p className="rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs leading-5 text-amber-700">蓝图、出题和审题需要结构化输出。</p> : null}

              <Button className="w-full" size="lg" type="submit" loading={saveAndTest.isPending} disabled={!canSave}>
                <Wifi aria-hidden="true" className="h-4 w-4" />
                {editingProfileId ? '更新并测试' : '保存并测试连接'}
              </Button>
              <p className="text-center text-xs text-stone-400">测试失败也会保留配置，方便修改后重试。</p>
            </form>
          </CardBody>
        </Card>

        <section aria-labelledby="profiles-title" className="min-w-0">
          <div className="mb-3 flex items-end justify-between gap-3">
            <div>
              <h2 id="profiles-title" className="text-lg font-bold text-ink">已配置模型</h2>
              <p className="mt-1 text-xs text-stone-500">至少一条可用配置即可开始出题。</p>
            </div>
            <Badge tone={profiles.data?.some((profile) => profile.is_available !== false) ? 'success' : 'warning'}>{profiles.data?.length ?? 0} 条</Badge>
          </div>

          {profiles.data?.length ? (
            <div className="space-y-3">
              {profiles.data.map((profile) => (
                <Card key={profile.id}>
                  <CardBody className="p-4">
                    <div className="flex min-w-0 items-start gap-3">
                      <span className={cn('grid h-10 w-10 shrink-0 place-items-center rounded-xl', profile.provider === 'ollama' ? 'bg-pine-50 text-pine-700' : 'bg-sky-50 text-sky-700')}>
                        {profile.provider === 'ollama' ? <Cpu aria-hidden="true" className="h-4 w-4" /> : <Cloud aria-hidden="true" className="h-4 w-4" />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="truncate text-sm font-bold text-ink">{profile.name}</h3>
                          <Badge tone={profile.is_available === false ? 'warning' : 'success'}>{profile.is_available === false ? '不可用' : '已启用'}</Badge>
                        </div>
                        <p className="mt-1 truncate font-mono text-xs text-stone-500" title={`${profile.model_name} · ${profile.base_url}`}>{profile.model_name} · {profile.base_url}</p>
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {profile.default_roles.map((role) => <Badge key={role}>{roles.find((item) => item.key === role)?.label || role}</Badge>)}
                          {profile.capabilities.vision ? <Badge tone="violet"><Eye aria-hidden="true" className="mr-1 h-3 w-3" />视觉</Badge> : null}
                          {profile.capabilities.embedding ? <Badge tone="info">Embedding</Badge> : null}
                        </div>
                        {profile.last_tested_at ? <p className="mt-2 text-xs text-stone-400">最近测试 {formatDate(profile.last_tested_at)}</p> : null}
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2 border-t border-stone-100 pt-3">
                      <Button variant="secondary" size="sm" onClick={() => startEditing(profile)}><Pencil aria-hidden="true" className="h-3.5 w-3.5" />编辑</Button>
                      <Button variant="secondary" size="sm" onClick={() => test.mutate(profile.id)} loading={test.isPending && test.variables === profile.id} disabled={test.isPending && test.variables !== profile.id}><Wifi aria-hidden="true" className="h-3.5 w-3.5" />测试</Button>
                      <Button className="ml-auto" variant="danger" size="sm" onClick={() => { if (window.confirm(`删除模型配置“${profile.name}”？`)) remove.mutate(profile.id); }}><Trash2 aria-hidden="true" className="h-3.5 w-3.5" />删除</Button>
                    </div>
                  </CardBody>
                </Card>
              ))}
            </div>
          ) : (
            <Card><CardBody className="py-10 text-center"><Cpu aria-hidden="true" className="mx-auto h-7 w-7 text-stone-300" /><p className="mt-3 text-sm font-bold text-ink">还没有模型配置</p><p className="mt-1 text-xs text-stone-400">从左侧选择 Kimi 或 Ollama。</p></CardBody></Card>
          )}

          <details className="group mt-4 overflow-hidden rounded-2xl border border-stone-200 bg-white">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4 hover:bg-stone-50">
              <span className="flex items-center gap-3"><ShieldCheck aria-hidden="true" className="h-5 w-5 text-pine-700" /><span><span className="block text-sm font-bold text-ink">本地三模型方案（可选）</span><span className="mt-0.5 block text-xs text-stone-500">完全离线或需要单独视觉、向量模型时再展开</span></span></span>
              <ChevronDown aria-hidden="true" className="h-4 w-4 text-stone-400 transition group-open:rotate-180" />
            </summary>
            <div className="space-y-4 border-t border-stone-100 bg-stone-50/50 p-4">
              <div className="grid gap-2 sm:grid-cols-2">
                {([['host', 'Windows 本机'], ['compose', '项目 Docker 内']] as const).map(([value, label]) => (
                  <button key={value} type="button" onClick={() => setOllamaLocation(value)} className={cn('rounded-lg border px-3 py-2 text-left text-xs font-semibold', ollamaLocation === value ? 'border-pine-500 bg-white text-pine-700' : 'border-stone-200 text-stone-500')}>{label}</button>
                ))}
              </div>
              <div className="space-y-2">
                {localBundle.map((item) => <div key={item.name} className="rounded-lg bg-white p-3 text-xs"><span className="font-mono font-bold text-ink">{item.model_name}</span><span className="ml-2 text-stone-400">{item.purpose}</span></div>)}
              </div>
              <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-ink p-3 text-[11px] leading-5 text-pine-50">{command}</pre>
              <div className="grid gap-2 sm:grid-cols-2">
                <Button type="button" variant="secondary" onClick={() => void navigator.clipboard.writeText(command).then(() => toast.success('下载命令已复制')).catch(() => toast.error('复制失败'))}><Copy aria-hidden="true" className="h-4 w-4" />复制下载命令</Button>
                <Button type="button" onClick={() => configureLocalBundle.mutate()} loading={configureLocalBundle.isPending}><Download aria-hidden="true" className="h-4 w-4" />写入三条配置</Button>
              </div>
              <p className="text-xs leading-5 text-stone-500">写入配置不会自动下载模型；请先执行命令，下载完成后再测试。</p>
            </div>
          </details>
        </section>
      </div>
    </div>
  );
}
