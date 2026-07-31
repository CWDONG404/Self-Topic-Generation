import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Check,
  CircleHelp,
  Cloud,
  Copy,
  Cpu,
  Download,
  ExternalLink,
  Eye,
  KeyRound,
  Lightbulb,
  Pencil,
  Plus,
  Server,
  ShieldCheck,
  TestTube2,
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
import type { ModelProvider, ModelRole } from '../types/api';

const roles: Array<{ key: ModelRole; label: string; description: string; required?: boolean }> = [
  { key: 'blueprint', label: '考点蓝图', description: '分析大纲与资料，规划知识点和题量。', required: true },
  { key: 'generator', label: '出题', description: '根据证据生成题干、选项与解析。', required: true },
  { key: 'reviewer', label: '审题', description: '独立复核答案、证据与题目质量。', required: true },
  { key: 'vision', label: '视觉', description: '仅在资料包含图片且模型能读图时使用。' },
  { key: 'embedding', label: 'Embedding', description: '可选的向量检索模型，不负责生成文本。' },
];

const initialForm = {
  name: '',
  provider: 'ollama' as ModelProvider,
  base_url: 'http://host.docker.internal:11434',
  model_name: '',
  api_key: '',
  structured_output: true,
  vision: false,
  embedding: false,
  default_roles: [] as ModelRole[],
};

const localBundle = [
  {
    id: 'text',
    name: 'Ollama 文本主模型',
    model_name: 'qwen3:8b',
    size: '约 5.2 GB',
    purpose: '考点蓝图、出题、审题',
    capabilities: { structured_output: true, vision: false, embedding: false },
    default_roles: ['blueprint', 'generator', 'reviewer'] as ModelRole[],
  },
  {
    id: 'vision',
    name: 'Ollama 视觉模型',
    model_name: 'qwen3-vl:4b',
    size: '约 3.3 GB',
    purpose: '图片、表格、流程图理解',
    capabilities: { structured_output: true, vision: true, embedding: false },
    default_roles: ['vision'] as ModelRole[],
  },
  {
    id: 'embedding',
    name: 'Ollama 向量模型',
    model_name: 'qwen3-embedding:0.6b',
    size: '约 639 MB',
    purpose: '中文语义检索与证据召回',
    capabilities: { structured_output: false, vision: false, embedding: true },
    default_roles: ['embedding'] as ModelRole[],
  },
];

const examples = [
  {
    id: 'ollama-compose',
    label: '项目内 Ollama',
    description: '使用 Compose 的 Ollama 服务，无需 API Key。',
    values: {
      ...initialForm,
      name: 'Ollama 文本主模型',
      provider: 'ollama' as const,
      base_url: 'http://ollama:11434',
      model_name: 'qwen3:8b',
      default_roles: ['blueprint', 'generator', 'reviewer'] as ModelRole[],
    },
  },
  {
    id: 'kimi-k3',
    label: 'Kimi K3',
    description: '文本与图片均可用；Embedding 请另配向量模型。',
    values: {
      ...initialForm,
      name: 'Kimi K3',
      provider: 'openai_compatible' as const,
      base_url: 'https://api.kimi.com/coding/v1',
      model_name: 'k3-256k',
      vision: true,
      default_roles: ['blueprint', 'generator', 'reviewer', 'vision'] as ModelRole[],
    },
  },
  {
    id: 'openai',
    label: 'OpenAI 兼容',
    description: '适用于官方 OpenAI 或兼容 Chat Completions 的服务。',
    values: {
      ...initialForm,
      name: 'OpenAI 兼容模型',
      provider: 'openai_compatible' as const,
      base_url: 'https://api.openai.com/v1',
      model_name: 'gpt-4o-mini',
      default_roles: ['blueprint', 'generator', 'reviewer'] as ModelRole[],
    },
  },
];

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(initialForm);
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
  const [ollamaLocation, setOllamaLocation] = useState<'compose' | 'host'>('compose');
  const [testAfterSave, setTestAfterSave] = useState(true);
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

  const save = useMutation({
    mutationFn: () => editingProfileId
      ? api.updateModelProfile(editingProfileId, { ...modelPayload(), enabled: true })
      : api.createModelProfile(modelPayload()),
    onSuccess: (profile) => {
      const edited = Boolean(editingProfileId);
      setForm(initialForm);
      setEditingProfileId(null);
      toast.success(edited ? '模型配置已更新' : '模型配置已保存');
      void queryClient.invalidateQueries({ queryKey: ['model-profiles'] });

      if (testAfterSave) {
        const toastId = `model-test-${profile.id}`;
        toast.loading('已保存，正在测试连接…', { id: toastId });
        void api.testModelProfile(profile.id)
          .then((result) => {
            if (result.ok) {
              toast.success(`连接成功${result.latency_ms ? ` · ${result.latency_ms} ms` : ''}`, { id: toastId });
            } else {
              toast.error(result.message || '配置已保存，但连接测试失败', { id: toastId });
            }
            void queryClient.invalidateQueries({ queryKey: ['model-profiles'] });
          })
          .catch((error) => toast.error(`配置已保存；测试失败：${toErrorMessage(error)}`, { id: toastId }));
      }
    },
    onError: (error) => toast.error(toErrorMessage(error)),
  });

  const configureLocalBundle = useMutation({
    mutationFn: async () => {
      const baseUrl = ollamaLocation === 'compose'
        ? 'http://ollama:11434'
        : 'http://host.docker.internal:11434';
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
      toast.success('已写入 3 条 Ollama 默认配置；下载模型后逐条测试即可');
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

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="AI 基础设施"
        title="模型设置"
        description="为不同 Agent 分配云端或本地模型。密钥只允许覆盖，读取接口永不返回明文。"
      />

      <Card className="mb-6 overflow-hidden border-pine-100 bg-gradient-to-br from-white to-pine-50/60">
        <CardBody>
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-pine-100 text-pine-700">
              <Lightbulb aria-hidden="true" className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="font-bold text-ink">第一次配置？按这 3 步</h2>
              <ol className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
                <li className="rounded-xl border border-white bg-white/80 p-3 shadow-sm">
                  <span className="text-xs font-bold text-pine-700">01 · 选接口</span>
                  <p className="mt-1 leading-6 text-stone-600">本机 Ollama 选“Ollama”；云服务及 Kimi Coding 选“OpenAI 兼容”。</p>
                </li>
                <li className="rounded-xl border border-white bg-white/80 p-3 shadow-sm">
                  <span className="text-xs font-bold text-pine-700">02 · 填准确 ID</span>
                  <p className="mt-1 leading-6 text-stone-600">Base URL 是服务根地址，模型名必须与服务端实际模型 ID 完全一致。</p>
                </li>
                <li className="rounded-xl border border-white bg-white/80 p-3 shadow-sm">
                  <span className="text-xs font-bold text-pine-700">03 · 保存并测试</span>
                  <p className="mt-1 leading-6 text-stone-600">保持“保存后测试”开启；成功后再到生成页分配模型角色。</p>
                </li>
              </ol>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card className="mb-6 overflow-hidden border-pine-200">
        <CardHeader className="flex flex-col gap-2 border-b border-pine-100 bg-pine-50/70 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Server aria-hidden="true" className="h-5 w-5 text-pine-700" />
              <h2 className="font-bold text-ink">推荐：Ollama 本地三模型方案</h2>
            </div>
            <p className="mt-1 text-xs leading-5 text-stone-500">职责分开更容易理解，也避免把文本模型误当成 Embedding 模型。</p>
          </div>
          <Badge tone="success">总下载约 9.1 GB</Badge>
        </CardHeader>
        <CardBody>
          <div className="grid gap-3 lg:grid-cols-3">
            {localBundle.map((item, index) => (
              <div key={item.id} className="rounded-xl border border-stone-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-pine-700 text-xs font-bold text-white">{index + 1}</span>
                  <Badge>{item.size}</Badge>
                </div>
                <p className="mt-3 font-mono text-sm font-bold text-ink">{item.model_name}</p>
                <p className="mt-1 text-xs leading-5 text-stone-500">{item.purpose}</p>
                <button
                  type="button"
                  className="mt-3 text-xs font-semibold text-pine-700 hover:underline"
                  onClick={() => {
                    setEditingProfileId(null);
                    setForm({
                      ...initialForm,
                      name: item.name,
                      provider: 'ollama',
                      base_url: ollamaLocation === 'compose' ? 'http://ollama:11434' : 'http://host.docker.internal:11434',
                      model_name: item.model_name,
                      structured_output: item.capabilities.structured_output,
                      vision: item.capabilities.vision,
                      embedding: item.capabilities.embedding,
                      default_roles: item.default_roles,
                    });
                  }}
                >
                  单独填入表单
                </button>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-4 rounded-xl bg-stone-50 p-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div className="min-w-0">
              <p className="text-sm font-bold text-ink">1. 选择 Ollama 在哪里运行</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {([
                  ['compose', '项目 Docker 内（推荐）', 'http://ollama:11434'],
                  ['host', 'Windows 宿主机', 'http://host.docker.internal:11434'],
                ] as const).map(([value, label, address]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setOllamaLocation(value)}
                    className={cn(
                      'rounded-lg border px-3 py-2 text-left text-xs transition',
                      ollamaLocation === value
                        ? 'border-pine-500 bg-white text-pine-800 shadow-sm'
                        : 'border-stone-200 text-stone-500 hover:border-stone-300',
                    )}
                  >
                    <span className="block font-bold">{label}</span>
                    <span className="mt-0.5 block font-mono text-[11px] opacity-70">{address}</span>
                  </button>
                ))}
              </div>
              <p className="mt-4 text-sm font-bold text-ink">2. 启动并下载模型</p>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-ink p-3 text-[11px] leading-5 text-pine-50">
                {ollamaLocation === 'compose'
                  ? 'docker compose --profile ollama up -d ollama\n'
                    + 'docker compose exec ollama ollama pull qwen3:8b\n'
                    + 'docker compose exec ollama ollama pull qwen3-vl:4b\n'
                    + 'docker compose exec ollama ollama pull qwen3-embedding:0.6b'
                  : 'ollama pull qwen3:8b\n'
                    + 'ollama pull qwen3-vl:4b\n'
                    + 'ollama pull qwen3-embedding:0.6b'}
              </pre>
            </div>
            <div className="flex flex-col gap-2">
              <Button
                variant="secondary"
                type="button"
                onClick={() => {
                  const command = ollamaLocation === 'compose'
                    ? 'docker compose --profile ollama up -d ollama\n'
                      + 'docker compose exec ollama ollama pull qwen3:8b\n'
                      + 'docker compose exec ollama ollama pull qwen3-vl:4b\n'
                      + 'docker compose exec ollama ollama pull qwen3-embedding:0.6b'
                    : 'ollama pull qwen3:8b\n'
                      + 'ollama pull qwen3-vl:4b\n'
                      + 'ollama pull qwen3-embedding:0.6b';
                  void navigator.clipboard.writeText(command)
                    .then(() => toast.success('下载命令已复制'))
                    .catch(() => toast.error('复制失败，请手动选择命令'));
                }}
              >
                <Copy aria-hidden="true" className="h-4 w-4" />
                复制下载命令
              </Button>
              <Button
                type="button"
                onClick={() => configureLocalBundle.mutate()}
                loading={configureLocalBundle.isPending}
              >
                <Download aria-hidden="true" className="h-4 w-4" />
                写入三条配置
              </Button>
            </div>
          </div>
          <p className="mt-3 text-xs leading-5 text-stone-500">
            “写入配置”只保存地址、模型名和 Agent 分工，不会偷偷下载约 9 GB 文件。请先执行上方命令，下载完成后再逐条点击“测试”。
          </p>
        </CardBody>
      </Card>

      <div className="mb-6 rounded-2xl border border-sky-100 bg-sky-50 p-4 text-sm text-sky-900">
        <p className="font-bold">关于 Kimi K3</p>
        <p className="mt-1 text-xs leading-5 text-sky-700">
          K3 支持图片输入，因此可以同时承担蓝图、出题、审题和视觉角色；它不是 Embedding 模型。此前的 ReadTimeout
          表示长任务在客户端等待窗口内没有返回，不是 API Key 格式错误。系统现在为正式出题使用更长的请求窗口，并保留自动重试。
        </p>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <section aria-labelledby="profiles-title">
          <h2 id="profiles-title" className="mb-3 text-lg font-bold text-ink">已配置模型</h2>
          {profiles.data?.length ? (
            <div className="space-y-3">
              {profiles.data.map((profile) => (
                <Card key={profile.id}>
                  <CardBody>
                    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
                      <div className="flex min-w-0 items-start gap-3">
                        <span className={cn(
                          'grid h-11 w-11 shrink-0 place-items-center rounded-xl',
                          profile.provider === 'ollama' ? 'bg-pine-50 text-pine-700' : 'bg-sky-50 text-sky-700',
                        )}>
                          {profile.provider === 'ollama' ? <Cpu aria-hidden="true" className="h-5 w-5" /> : <Cloud aria-hidden="true" className="h-5 w-5" />}
                        </span>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-bold text-ink">{profile.name}</h3>
                            <Badge tone={profile.provider === 'ollama' ? 'success' : 'info'}>
                              {profile.provider === 'ollama' ? 'Ollama 本地' : 'OpenAI 兼容'}
                            </Badge>
                            {profile.is_available !== false ? (
                              <Badge tone="success"><Check aria-hidden="true" className="mr-1 h-3 w-3" />已启用</Badge>
                            ) : (
                              <Badge tone="warning">已停用</Badge>
                            )}
                          </div>
                          <p className="mt-1 truncate font-mono text-xs text-stone-500">{profile.model_name} · {profile.base_url}</p>
                          <div className="mt-3 flex flex-wrap gap-1.5">
                            {profile.default_roles.map((role) => (
                              <Badge key={role}>{roles.find((item) => item.key === role)?.label || role}</Badge>
                            ))}
                            {profile.capabilities.structured_output ? <Badge tone="success">结构化输出</Badge> : null}
                            {profile.capabilities.vision ? <Badge tone="violet"><Eye aria-hidden="true" className="mr-1 h-3 w-3" />视觉</Badge> : null}
                            {profile.capabilities.embedding ? <Badge tone="info">Embedding</Badge> : null}
                          </div>
                          {profile.last_tested_at ? <p className="mt-2 text-xs text-stone-400">最近测试 {formatDate(profile.last_tested_at)}</p> : null}
                        </div>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => {
                            setEditingProfileId(profile.id);
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
                          }}
                        >
                          <Pencil aria-hidden="true" className="h-3.5 w-3.5" />
                          编辑
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => test.mutate(profile.id)}
                          loading={test.isPending && test.variables === profile.id}
                          disabled={test.isPending && test.variables !== profile.id}
                        >
                          <Wifi aria-hidden="true" className="h-3.5 w-3.5" />
                          测试
                        </Button>
                        <Button
                          variant="danger"
                          size="icon"
                          onClick={() => {
                            if (window.confirm(`删除模型配置“${profile.name}”？密钥引用也会一并移除。`)) {
                              remove.mutate(profile.id);
                            }
                          }}
                          aria-label={`删除 ${profile.name}`}
                        >
                          <Trash2 aria-hidden="true" className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </CardBody>
                </Card>
              ))}
            </div>
          ) : (
            <Card>
              <CardBody className="py-12 text-center">
                <Cpu aria-hidden="true" className="mx-auto h-8 w-8 text-stone-300" />
                <p className="mt-3 font-bold text-ink">还没有模型配置</p>
                <p className="mt-1 text-sm text-stone-400">从右侧示例开始，保存后会自动测试连接。</p>
              </CardBody>
            </Card>
          )}

          <div className="mt-4 rounded-2xl border border-pine-100 bg-pine-50 p-4">
            <div className="flex items-start gap-3">
              <ShieldCheck aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-pine-700" />
              <div>
                <p className="text-sm font-bold text-pine-900">密钥与本地模式安全边界</p>
                <p className="mt-1 text-xs leading-5 text-pine-700">
                  API Key 使用密码框录入，保存后前端会立即清空，后续接口只返回“已配置”状态而非明文。选择“仅本地”生成时，系统不会自动回退到云端。
                </p>
              </div>
            </div>
          </div>

          <Card className="mt-4">
            <CardHeader className="flex items-center gap-2">
              <CircleHelp aria-hidden="true" className="h-4 w-4 text-pine-600" />
              <h2 className="font-bold text-ink">能力与默认角色怎么选</h2>
            </CardHeader>
            <CardBody className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl bg-stone-50 p-4 text-sm">
                <p className="font-bold text-ink">能力是硬条件</p>
                <p className="mt-1 text-xs leading-5 text-stone-500">
                  蓝图、出题、审题需要结构化输出；视觉与 Embedding 只在对应角色中出现。请按服务端真实能力勾选。
                </p>
              </div>
              <div className="rounded-xl bg-stone-50 p-4 text-sm">
                <p className="font-bold text-ink">默认角色是自动选择</p>
                <p className="mt-1 text-xs leading-5 text-stone-500">
                  打开生成页时会优先选中这些模型，不会改变模型能力，也可在每次任务中手动覆盖。
                </p>
              </div>
              <div className="sm:col-span-2 grid gap-2">
                {roles.map((role) => (
                  <div key={role.key} className="flex items-start justify-between gap-4 rounded-lg border border-stone-100 px-3 py-2.5">
                    <span className="text-xs font-semibold text-ink">
                      {role.label}{role.required ? <span className="ml-1 text-red-500">*</span> : null}
                    </span>
                    <span className="text-right text-xs leading-5 text-stone-500">{role.description}</span>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>
        </section>

        <Card className="xl:sticky xl:top-8">
          <CardHeader className="flex items-center gap-2">
            <Plus aria-hidden="true" className="h-4 w-4 text-pine-600" />
            <h2 className="font-bold text-ink">添加模型</h2>
          </CardHeader>
          <CardBody>
            <div>
              <p className="field-label">从示例开始</p>
              <div className="grid gap-2">
                {examples.map((example) => (
                  <button
                    key={example.id}
                    type="button"
                    className="rounded-xl border border-stone-200 bg-white p-3 text-left transition hover:border-pine-300 hover:bg-pine-50/50"
                    onClick={() => setForm({ ...example.values, api_key: '' })}
                  >
                    <span className="block text-xs font-bold text-ink">{example.label}</span>
                    <span className="mt-1 block text-xs leading-5 text-stone-400">{example.description}</span>
                  </button>
                ))}
              </div>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                <a className="inline-flex items-center gap-1 text-pine-700 hover:underline" href="https://www.kimi.com/code/docs/en/" target="_blank" rel="noreferrer">
                  Kimi 官方配置 <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
                <a className="inline-flex items-center gap-1 text-pine-700 hover:underline" href="https://docs.ollama.com/api/introduction" target="_blank" rel="noreferrer">
                  Ollama API <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
              </div>
            </div>

            <form
              id="model-profile-form"
              className="mt-5 space-y-4 border-t border-stone-100 pt-5"
              onSubmit={(event) => {
                event.preventDefault();
                if (form.name.trim() && form.model_name.trim() && form.base_url.trim()) save.mutate();
              }}
            >
              {editingProfileId ? (
                <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs text-amber-800">
                  <span className="font-semibold">正在编辑现有配置；API Key 留空会保留原密钥。</span>
                  <button
                    type="button"
                    className="shrink-0 font-bold hover:underline"
                    onClick={() => {
                      setEditingProfileId(null);
                      setForm(initialForm);
                    }}
                  >
                    取消编辑
                  </button>
                </div>
              ) : null}
              <fieldset>
                <legend className="field-label">接口类型</legend>
                <div className="grid grid-cols-2 gap-2">
                  {([
                    ['ollama', 'Ollama', '本机 / 局域网', Cpu],
                    ['openai_compatible', 'OpenAI 兼容', '云服务 / 兼容网关', Cloud],
                  ] as const).map(([value, label, description, Icon]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setForm((current) => ({
                        ...current,
                        provider: value,
                        base_url: value === 'ollama' ? 'http://host.docker.internal:11434' : '',
                        api_key: '',
                      }))}
                      className={cn(
                        'flex min-h-16 flex-col items-center justify-center gap-1 rounded-xl border px-2 text-xs font-bold transition',
                        form.provider === value ? 'border-pine-500 bg-pine-50 text-pine-700' : 'border-stone-200 text-stone-500 hover:border-stone-300',
                      )}
                    >
                      <span className="flex items-center gap-2"><Icon aria-hidden="true" className="h-4 w-4" />{label}</span>
                      <span className="font-normal text-stone-400">{description}</span>
                    </button>
                  ))}
                </div>
              </fieldset>

              <label>
                <span className="field-label">配置名称</span>
                <input
                  className="field-control"
                  placeholder="例如：本地审题模型"
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                  required
                />
                <span className="field-help block">只用于本系统内识别，可写用途或部署位置。</span>
              </label>

              <label>
                <span className="field-label">Base URL</span>
                <input
                  className="field-control font-mono text-xs"
                  placeholder={form.provider === 'ollama' ? 'http://host.docker.internal:11434' : 'https://api.example.com/v1'}
                  value={form.base_url}
                  onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                  required
                  inputMode="url"
                />
                <span className="field-help block">
                  {form.provider === 'ollama'
                    ? 'Docker 部署通常使用 host.docker.internal；直接运行前端/后端时可用 localhost。'
                    : '填写服务根地址，通常以 /v1 结尾，不要填完整的 /chat/completions。'}
                </span>
              </label>

              <label>
                <span className="field-label">模型名</span>
                <input
                  className="field-control font-mono text-xs"
                  placeholder={form.provider === 'ollama' ? 'qwen3:8b' : '服务商提供的模型 ID'}
                  value={form.model_name}
                  onChange={(event) => setForm({ ...form, model_name: event.target.value })}
                  required
                  autoCapitalize="none"
                  spellCheck={false}
                />
                <span className="field-help block">模型 ID 区分字符，请从服务商模型列表复制。</span>
              </label>

              {form.provider === 'openai_compatible' ? (
                <label>
                  <span className="field-label">API Key</span>
                  <div className="relative">
                    <KeyRound aria-hidden="true" className="absolute left-3 top-3.5 h-4 w-4 text-stone-400" />
                    <input
                      type="password"
                      autoComplete="new-password"
                      className="field-control pl-10"
                      placeholder="只写入，不回显"
                      value={form.api_key}
                      onChange={(event) => setForm({ ...form, api_key: event.target.value })}
                    />
                  </div>
                  <span className="field-help block">示例不会填入密钥；请只粘贴当前服务签发的 Key。</span>
                </label>
              ) : null}

              <fieldset>
                <legend className="field-label">能力</legend>
                <div className="space-y-2">
                  {([
                    ['structured_output', '结构化输出', '蓝图 / 出题 / 审题必需'],
                    ['vision', '视觉理解', '读图模型才开启'],
                    ['embedding', 'Embedding', '向量模型才开启'],
                  ] as const).map(([key, label, description]) => (
                    <label key={key} className="flex items-start gap-2 rounded-lg border border-stone-100 px-3 py-2 text-sm text-stone-600">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 rounded border-stone-300 text-pine-600 focus:ring-pine-500"
                        checked={form[key]}
                        onChange={(event) => setForm({ ...form, [key]: event.target.checked })}
                      />
                      <span>
                        <span className="block font-semibold text-ink">{label}</span>
                        <span className="mt-0.5 block text-xs text-stone-400">{description}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset>
                <legend className="field-label">默认角色</legend>
                <div className="flex flex-wrap gap-2">
                  {roles.map((role) => {
                    const active = form.default_roles.includes(role.key);
                    return (
                      <button
                        key={role.key}
                        type="button"
                        aria-pressed={active}
                        onClick={() => setForm({
                          ...form,
                          default_roles: active
                            ? form.default_roles.filter((item) => item !== role.key)
                            : [...form.default_roles, role.key],
                        })}
                        className={cn(
                          'rounded-full border px-3 py-1.5 text-xs font-semibold transition',
                          active ? 'border-pine-500 bg-pine-50 text-pine-700' : 'border-stone-200 text-stone-500 hover:border-stone-300',
                        )}
                      >
                        {role.label}
                      </button>
                    );
                  })}
                </div>
                <p className="field-help">同一模型可以承担多个角色；生成页仍可逐次调整。</p>
              </fieldset>

              {!form.structured_output && form.default_roles.some((role) => ['blueprint', 'generator', 'reviewer'].includes(role)) ? (
                <div className="rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs leading-5 text-amber-700">
                  蓝图、出题和审题角色要求“结构化输出”，请开启该能力或取消对应默认角色。
                </div>
              ) : null}

              <label className="flex items-start gap-3 rounded-xl border border-pine-100 bg-pine-50/70 p-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-stone-300 text-pine-600 focus:ring-pine-500"
                  checked={testAfterSave}
                  onChange={(event) => setTestAfterSave(event.target.checked)}
                />
                <span>
                  <span className="flex items-center gap-1.5 font-semibold text-pine-900">
                    <TestTube2 aria-hidden="true" className="h-4 w-4" />
                    保存后立即测试
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-pine-700">推荐开启。测试失败不会撤销已保存配置，可修改后再次测试。</span>
                  <span className="mt-1 block text-xs leading-5 text-pine-700">连接测试主要验证地址与鉴权；OpenAI 兼容服务是否支持严格结构化输出，建议先用少量题目试跑。</span>
                </span>
              </label>

              <Button
                className="w-full"
                type="submit"
                loading={save.isPending}
                disabled={
                  !form.name.trim()
                  || !form.model_name.trim()
                  || !form.base_url.trim()
                  || (!form.structured_output && form.default_roles.some((role) => ['blueprint', 'generator', 'reviewer'].includes(role)))
                }
              >
                {editingProfileId ? '更新模型配置' : '保存模型配置'}
              </Button>
            </form>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
