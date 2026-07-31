import type {
  ApiList,
  CitationAnchor,
  CitationContent,
  DocumentRecord,
  GenerationRequest,
  Job,
  JobEvent,
  Library,
  ModelProfile,
  Paper,
  PracticeAnswer,
  PracticeResult,
  PracticeSession,
  Question,
  QuestionOption,
  WrongAnswerRecord,
} from '../types/api';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, '');

export class ApiError extends Error {
  status: number;
  details?: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  headers.set('Accept', 'application/json');

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let details: unknown;
    try {
      details = await response.json();
    } catch {
      details = await response.text();
    }
    const detailMessage =
      typeof details === 'object' && details !== null && 'detail' in details
        ? String((details as { detail: unknown }).detail)
        : undefined;
    throw new ApiError(detailMessage || `请求失败（${response.status}）`, response.status, details);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function unwrapList<T>(value: T[] | ApiList<T>): T[] {
  return Array.isArray(value) ? value : value.items;
}

interface BackendDocumentVersion {
  id: string;
  version_number: number;
  file_size: number;
  page_count: number | null;
  status: string;
  progress: number;
  error: string | null;
  metadata_json: Record<string, unknown>;
}

interface BackendDocument {
  id: string;
  library_id: string;
  name: string;
  role: 'outline' | 'source';
  allow_as_evidence: boolean;
  extension: string;
  mime_type: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  latest_version: BackendDocumentVersion | null;
}

interface BackendModelProfile {
  id: string;
  name: string;
  provider: 'openai_compatible' | 'ollama';
  base_url: string;
  model_name: string;
  capabilities: Record<string, boolean>;
  default_roles?: string[];
  enabled: boolean;
  is_default: boolean;
  has_api_key: boolean;
  created_at: string;
}

interface BackendJob {
  id: string;
  status: string;
  stage: string;
  progress: number;
  request_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  error: string | null;
  target_count: number;
  accepted_count: number;
  rejected_count: number;
  revision_count: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

interface BackendOption {
  id: string;
  label: string;
  text: string;
  position: number;
}

interface BackendCitation {
  id: string;
  document_id: string;
  document_name: string;
  document_type: string;
  document_version_id: string;
  chunk_id: string;
  block_id: string | null;
  page_number: number | null;
  rects: unknown[];
  rectangles?: CitationAnchor['rectangles'];
  excerpt: string;
  excerpt_hash: string;
  char_start: number | null;
  char_end: number | null;
}

interface BackendReview {
  id: string;
  status: string;
  chosen_option: string | null;
  issues: string[];
  rationale: string | null;
  created_at: string;
}

interface BackendQuestion {
  id: string;
  stem: string;
  correct_option: string;
  explanation: string;
  knowledge_point: string;
  difficulty: string;
  status: string;
  similarity_relaxed: boolean;
  options: BackendOption[];
  citations: BackendCitation[];
  reviews: BackendReview[];
  created_at: string;
}

interface BackendPaper {
  id: string;
  title: string;
  status: string;
  target_count: number;
  actual_count: number;
  random_seed: number;
  metadata_json: Record<string, unknown>;
  questions?: BackendQuestion[];
  created_at: string;
  updated_at: string;
}

interface BackendPracticeQuestion {
  id: string;
  stem: string;
  knowledge_point: string;
  difficulty: string;
  options: BackendOption[];
  correct_option?: string | null;
  explanation?: string | null;
  citations?: BackendCitation[];
}

interface BackendPracticeAnswer {
  question_id: string;
  selected_option: string;
  is_correct: boolean | null;
  answered_at: string;
}

interface BackendPracticeSession {
  id: string;
  paper_id: string;
  mode: string;
  status: string;
  current_index: number;
  score: number | null;
  correct_count: number;
  total_count: number;
  questions: BackendPracticeQuestion[];
  answers: BackendPracticeAnswer[];
  created_at: string;
  submitted_at: string | null;
}

interface BackendPracticeResult extends Omit<BackendPracticeSession, 'questions'> {
  questions: BackendQuestion[];
}

function normalizeDocument(raw: BackendDocument): DocumentRecord {
  const version = raw.latest_version;
  const metadata = version?.metadata_json ?? {};
  const parserWarnings = Array.isArray(metadata.parser_warnings)
    ? metadata.parser_warnings.map(String)
    : [];
  const rawStatus = raw.archived ? 'archived' : (version?.status ?? 'queued');
  const status: DocumentRecord['status'] = rawStatus === 'uploaded'
    ? 'queued'
    : rawStatus === 'ready' && parserWarnings.length
      ? 'warning'
      : ['queued', 'parsing', 'ready', 'warning', 'failed', 'archived'].includes(rawStatus)
        ? rawStatus as DocumentRecord['status']
        : 'queued';
  return {
    id: raw.id,
    library_id: raw.library_id,
    name: raw.name,
    original_filename: typeof metadata.original_filename === 'string' ? metadata.original_filename : raw.name,
    extension: raw.extension,
    mime_type: raw.mime_type,
    size_bytes: version?.file_size,
    role: raw.role,
    allow_as_evidence: raw.allow_as_evidence,
    status,
    progress: version?.progress ?? 0,
    page_count: version?.page_count,
    chunk_count: typeof metadata.chunk_count === 'number' ? metadata.chunk_count : undefined,
    version: version?.version_number,
    warnings: parserWarnings,
    error: version?.error,
    created_at: raw.created_at,
    updated_at: raw.updated_at,
  };
}

function normalizeProfile(raw: BackendModelProfile): ModelProfile {
  const normalizedRoles = (raw.default_roles ?? []).flatMap((role): ModelProfile['default_roles'] => {
    const frontendRole = role === 'author' ? 'generator' : role;
    return ['blueprint', 'generator', 'reviewer', 'vision', 'embedding'].includes(frontendRole)
      ? [frontendRole as ModelProfile['default_roles'][number]]
      : [];
  });
  return {
    id: raw.id,
    name: raw.name,
    provider: raw.provider,
    base_url: raw.base_url,
    model_name: raw.model_name,
    capabilities: {
      structured_output: Boolean(raw.capabilities.structured_output),
      vision: Boolean(raw.capabilities.vision),
      embedding: Boolean(raw.capabilities.embedding),
    },
    default_roles: normalizedRoles,
    has_api_key: raw.has_api_key,
    is_available: raw.enabled,
    created_at: raw.created_at,
  };
}

function modelProfilePayload(payload: Record<string, unknown>) {
  if (!Array.isArray(payload.default_roles)) return payload;
  return {
    ...payload,
    default_roles: payload.default_roles.map((role) => role === 'generator' ? 'author' : role),
  };
}

function frontendRequest(raw: Record<string, unknown>): GenerationRequest | undefined {
  const sources = Array.isArray(raw.source_documents) ? raw.source_documents : [];
  if (typeof raw.library_id !== 'string') return undefined;
  return {
    library_id: raw.library_id,
    outline_document_ids: Array.isArray(raw.outline_document_ids)
      ? raw.outline_document_ids.map(String)
      : [],
    source_allocations: sources.flatMap((item) => {
      if (!item || typeof item !== 'object') return [];
      const value = item as Record<string, unknown>;
      return typeof value.document_id === 'string' && typeof value.percentage === 'number'
        ? [{ document_id: value.document_id, percentage: value.percentage }]
        : [];
    }),
    question_count: typeof raw.target_count === 'number' ? raw.target_count : 50,
    execution_mode: raw.execution_mode === 'local' ? 'local_only' : 'cloud_allowed',
    model_roles: raw.model_assignments && typeof raw.model_assignments === 'object'
      ? raw.model_assignments as GenerationRequest['model_roles']
      : {},
    random_seed: typeof raw.random_seed === 'number' ? raw.random_seed : undefined,
    allow_outline_as_evidence: raw.allow_outline_as_evidence === true,
  };
}

function normalizeJob(raw: BackendJob): Job {
  const result = raw.result_json ?? {};
  const warnings = Array.isArray(result.warnings) ? result.warnings.map(String) : [];
  const status: Job['status'] = raw.status === 'canceled'
    ? 'cancelled'
    : raw.status === 'cancel_requested'
      ? 'cancelling'
    : ['queued', 'running', 'completed', 'partial', 'failed'].includes(raw.status)
      ? raw.status as Job['status']
      : 'running';
  return {
    id: raw.id,
    kind: 'paper_generation',
    status,
    stage: raw.stage,
    progress: raw.progress,
    message: raw.error || undefined,
    counts: {
      accepted: raw.accepted_count,
      rejected: raw.rejected_count,
      revised: raw.revision_count,
      generated: typeof result.statistics === 'object' && result.statistics !== null
        ? Number((result.statistics as Record<string, unknown>).generated ?? 0)
        : 0,
      target: raw.target_count,
    },
    warnings,
    error: raw.error,
    paper_id: typeof result.paper_id === 'string' ? result.paper_id : null,
    request: frontendRequest(raw.request_json),
    created_at: raw.created_at,
    started_at: raw.started_at,
    finished_at: raw.completed_at,
  };
}

function normalizeOption(raw: BackendOption): QuestionOption {
  const key = ['A', 'B', 'C', 'D'].includes(raw.label) ? raw.label : 'A';
  return { key: key as QuestionOption['key'], text: raw.text };
}

function normalizeCitation(raw: BackendCitation): CitationAnchor {
  return {
    id: raw.id,
    document_id: raw.document_id,
    document_version_id: raw.document_version_id,
    document_name: raw.document_name,
    document_type: raw.document_type,
    chunk_id: raw.chunk_id,
    excerpt: raw.excerpt,
    excerpt_hash: raw.excerpt_hash,
    page_number: raw.page_number,
    rectangles: raw.rectangles ?? [],
    block_id: raw.block_id,
    start_offset: raw.char_start,
    end_offset: raw.char_end,
    file_url: `${API_BASE}/documents/${encodeURIComponent(raw.document_id)}/file?version_id=${encodeURIComponent(raw.document_version_id)}`,
  };
}

function normalizeQuestion(raw: BackendQuestion): Question {
  const latestReview = raw.reviews.at(-1);
  const answer = ['A', 'B', 'C', 'D'].includes(raw.correct_option) ? raw.correct_option : 'A';
  const difficulty = ['easy', 'medium', 'hard'].includes(raw.difficulty) ? raw.difficulty : 'medium';
  const reviewStatus = latestReview?.status === 'passed'
    ? 'passed'
    : latestReview?.status === 'failed'
      ? 'failed'
      : raw.status === 'review_pending'
        ? 'pending'
        : 'needs_revision';
  return {
    id: raw.id,
    stem: raw.stem,
    options: raw.options.sort((left, right) => left.position - right.position).map(normalizeOption),
    correct_answer: answer as Question['correct_answer'],
    explanation: raw.explanation,
    knowledge_point: raw.knowledge_point,
    difficulty: difficulty as Question['difficulty'],
    citations: raw.citations.map(normalizeCitation),
    review: {
      id: latestReview?.id,
      status: reviewStatus,
      independent_answer: latestReview?.chosen_option,
      comments: latestReview?.issues ?? (latestReview?.rationale ? [latestReview.rationale] : []),
      reviewed_at: latestReview?.created_at,
    },
    enabled: raw.status !== 'disabled',
    similarity_relaxed: raw.similarity_relaxed,
    created_at: raw.created_at,
  };
}

function normalizePaper(raw: BackendPaper): Paper {
  const questions = raw.questions?.map(normalizeQuestion);
  return {
    id: raw.id,
    title: raw.title,
    status: ['draft', 'ready', 'partial', 'archived'].includes(raw.status)
      ? raw.status as Paper['status']
      : 'draft',
    question_count: raw.actual_count,
    enabled_question_count: questions?.filter((item) => item.enabled).length ?? raw.actual_count,
    questions,
    random_seed: raw.random_seed,
    source_summary: Array.isArray(raw.metadata_json.warnings)
      ? raw.metadata_json.warnings.map(String).join('；')
      : undefined,
    created_at: raw.created_at,
    updated_at: raw.updated_at,
  };
}

function normalizeAnswer(raw: BackendPracticeAnswer): PracticeAnswer {
  return {
    question_id: raw.question_id,
    selected_answer: raw.selected_option,
    is_correct: raw.is_correct,
    answered_at: raw.answered_at,
  };
}

function placeholderQuestion(raw: BackendPracticeQuestion): Question {
  const difficulty = ['easy', 'medium', 'hard'].includes(raw.difficulty) ? raw.difficulty : 'medium';
  const answer = raw.correct_option && ['A', 'B', 'C', 'D'].includes(raw.correct_option)
    ? raw.correct_option
    : 'A';
  return {
    id: raw.id,
    stem: raw.stem,
    options: raw.options.sort((left, right) => left.position - right.position).map(normalizeOption),
    correct_answer: answer as Question['correct_answer'],
    explanation: raw.explanation ?? '',
    knowledge_point: raw.knowledge_point,
    difficulty: difficulty as Question['difficulty'],
    citations: (raw.citations ?? []).map(normalizeCitation),
    review: { status: 'pending' },
    enabled: true,
  };
}

function resultSummary(raw: BackendPracticeResult): PracticeResult {
  const answered = raw.answers.length;
  const incorrect = raw.answers.filter((item) => item.is_correct === false).length;
  const grouped = new Map<string, { name: string; correct: number; total: number }>();
  const answerByQuestion = new Map(raw.answers.map((item) => [item.question_id, item]));
  raw.questions.forEach((question) => {
    const current = grouped.get(question.knowledge_point) ?? {
      name: question.knowledge_point || '未分类', correct: 0, total: 0,
    };
    current.total += 1;
    if (answerByQuestion.get(question.id)?.is_correct) current.correct += 1;
    grouped.set(current.name, current);
  });
  return {
    score: raw.score ?? 0,
    correct_count: raw.correct_count,
    incorrect_count: incorrect,
    unanswered_count: Math.max(0, raw.total_count - answered),
    total_count: raw.total_count,
    knowledge_points: [...grouped.values()],
  };
}

async function normalizePracticeSession(raw: BackendPracticeSession): Promise<PracticeSession> {
  let paper: Paper;
  let result: PracticeResult | null = null;
  if (raw.status === 'submitted') {
    const [paperRaw, resultRaw] = await Promise.all([
      apiRequest<BackendPaper>(`/papers/${encodeURIComponent(raw.paper_id)}`),
      apiRequest<BackendPracticeResult>(`/practice-sessions/${encodeURIComponent(raw.id)}/result`),
    ]);
    paper = normalizePaper({ ...paperRaw, questions: resultRaw.questions });
    result = resultSummary(resultRaw);
    raw = resultRaw;
  } else if (raw.mode !== 'exam') {
    const basePaper = normalizePaper(
      await apiRequest<BackendPaper>(`/papers/${encodeURIComponent(raw.paper_id)}`),
    );
    paper = {
      ...basePaper,
      questions: raw.questions.map(placeholderQuestion),
      question_count: raw.total_count,
      enabled_question_count: raw.total_count,
    };
  } else {
    paper = {
      id: raw.paper_id,
      title: '模拟考试',
      status: 'ready',
      question_count: raw.total_count,
      questions: raw.questions.map(placeholderQuestion),
      created_at: raw.created_at,
    };
  }
  return {
    id: raw.id,
    paper_id: raw.paper_id,
    paper,
    mode: raw.mode === 'exam' ? 'exam' : raw.mode === 'wrong_answers' ? 'wrong_answers' : 'practice',
    status: raw.status === 'submitted' ? 'submitted' : 'in_progress',
    answers: raw.answers.map(normalizeAnswer),
    current_question_index: raw.current_index,
    result,
    created_at: raw.created_at,
    submitted_at: raw.submitted_at,
  };
}

export const api = {
  async listLibraries() {
    return unwrapList(await apiRequest<Library[] | ApiList<Library>>('/libraries'));
  },
  createLibrary(payload: Pick<Library, 'name'> & { description?: string }) {
    return apiRequest<Library>('/libraries', { method: 'POST', body: JSON.stringify(payload) });
  },
  async listDocuments(libraryId?: string, options?: { includeArchived?: boolean }) {
    const params = new URLSearchParams();
    if (libraryId) params.set('library_id', libraryId);
    if (options?.includeArchived) params.set('include_archived', 'true');
    const query = params.size ? `?${params.toString()}` : '';
    const values = unwrapList(await apiRequest<BackendDocument[] | ApiList<BackendDocument>>(`/documents${query}`));
    return values.map(normalizeDocument);
  },
  async getDocument(id: string) {
    return normalizeDocument(await apiRequest<BackendDocument>(`/documents/${encodeURIComponent(id)}`));
  },
  async uploadDocument(file: File, libraryId: string, role: DocumentRecord['role'], allowAsEvidence: boolean) {
    const body = new FormData();
    body.append('file', file);
    body.append('library_id', libraryId);
    body.append('role', role);
    body.append('allow_as_evidence', String(allowAsEvidence));
    return normalizeDocument(await apiRequest<BackendDocument>('/documents', { method: 'POST', body }));
  },
  async updateDocument(
    id: string,
    payload: Partial<Pick<DocumentRecord, 'name' | 'role' | 'allow_as_evidence'>> & { archived?: boolean },
  ) {
    return normalizeDocument(await apiRequest<BackendDocument>(`/documents/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(payload),
    }));
  },
  parseDocument(id: string) {
    return apiRequest<unknown>(`/documents/${encodeURIComponent(id)}/parse`, { method: 'POST' });
  },
  archiveDocument(id: string) {
    return apiRequest<void>(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' });
  },
  documentFileUrl(documentId: string) {
    return `${API_BASE}/documents/${encodeURIComponent(documentId)}/file`;
  },
  async getCitationContent(
    documentId: string,
    blockId?: string | null,
    versionId?: string | null,
  ) {
    const params = new URLSearchParams();
    if (blockId) params.set('block_id', blockId);
    if (versionId) params.set('version_id', versionId);
    const query = params.size ? `?${params.toString()}` : '';
    const raw = await apiRequest<{
      document_id: string;
      document_name: string;
      blocks: Array<{ id: string; text: string }>;
    }>(`/documents/${encodeURIComponent(documentId)}/content${query}`);
    const selected = blockId ? raw.blocks.find((item) => item.id === blockId) : undefined;
    return {
      document_id: raw.document_id,
      document_name: raw.document_name,
      block_id: blockId,
      text: raw.blocks.map((item) => item.text).join('\n\n'),
      highlighted_text: selected?.text,
    } satisfies CitationContent;
  },
  async listJobs() {
    const values = unwrapList(await apiRequest<BackendJob[] | ApiList<BackendJob>>('/jobs'));
    return values.map(normalizeJob);
  },
  async getJob(id: string) {
    return normalizeJob(await apiRequest<BackendJob>(`/jobs/${encodeURIComponent(id)}`));
  },
  async createGenerationJob(payload: GenerationRequest) {
    const backendPayload = {
      library_id: payload.library_id,
      outline_document_ids: payload.outline_document_ids,
      source_documents: payload.source_allocations,
      target_count: payload.question_count,
      execution_mode: payload.execution_mode === 'local_only' ? 'local' : 'mixed',
      model_assignments: payload.model_roles,
      random_seed: payload.random_seed,
      allow_outline_as_evidence: payload.allow_outline_as_evidence ?? false,
    };
    return normalizeJob(await apiRequest<BackendJob>('/jobs', {
      method: 'POST', body: JSON.stringify(backendPayload),
    }));
  },
  async cancelJob(id: string) {
    return normalizeJob(await apiRequest<BackendJob>(`/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }));
  },
  async retryJob(id: string) {
    return normalizeJob(await apiRequest<BackendJob>(`/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' }));
  },
  async listPapers() {
    const values = unwrapList(await apiRequest<BackendPaper[] | ApiList<BackendPaper>>('/papers'));
    return values.map(normalizePaper);
  },
  async getPaper(id: string) {
    return normalizePaper(await apiRequest<BackendPaper>(`/papers/${encodeURIComponent(id)}`));
  },
  async updateQuestion(id: string, payload: Record<string, unknown>) {
    const { correct_answer: correctAnswer, ...rest } = payload;
    const options = Array.isArray(payload.options)
      ? Object.fromEntries(payload.options.flatMap((item) => {
          if (!item || typeof item !== 'object') return [];
          const option = item as Record<string, unknown>;
          return typeof option.key === 'string' && typeof option.text === 'string'
            ? [[option.key, option.text]]
            : [];
        }))
      : payload.options;
    const backendPayload = {
      ...rest,
      options,
      correct_option: correctAnswer,
    };
    return normalizeQuestion(await apiRequest<BackendQuestion>(`/questions/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(backendPayload),
    }));
  },
  async reviewQuestion(id: string) {
    return normalizeQuestion(await apiRequest<BackendQuestion>(`/questions/${encodeURIComponent(id)}/review`, { method: 'POST' }));
  },
  async regenerateQuestion(id: string) {
    return normalizeQuestion(await apiRequest<BackendQuestion>(`/questions/${encodeURIComponent(id)}/regenerate`, { method: 'POST' }));
  },
  async disableQuestion(id: string) {
    return normalizeQuestion(await apiRequest<BackendQuestion>(`/questions/${encodeURIComponent(id)}/disable`, { method: 'POST' }));
  },
  async createPracticeSession(paperId: string, mode: PracticeSession['mode']) {
    const raw = await apiRequest<BackendPracticeSession>('/practice-sessions', {
      method: 'POST', body: JSON.stringify({ paper_id: paperId, mode: mode === 'exam' ? 'exam' : 'practice' }),
    });
    return normalizePracticeSession(raw);
  },
  async getPracticeSession(id: string) {
    return normalizePracticeSession(await apiRequest<BackendPracticeSession>(`/practice-sessions/${encodeURIComponent(id)}`));
  },
  async savePracticeAnswer(sessionId: string, questionId: string, selectedAnswer: string | null) {
    if (!selectedAnswer) return;
    await apiRequest<void>(`/practice-sessions/${encodeURIComponent(sessionId)}/answers`, {
      method: 'POST',
      body: JSON.stringify({ question_id: questionId, selected_option: selectedAnswer }),
    });
  },
  async submitPracticeSession(id: string) {
    await apiRequest(`/practice-sessions/${encodeURIComponent(id)}/submit`, { method: 'POST' });
    return api.getPracticeSession(id);
  },
  async listWrongAnswers() {
    const values = await apiRequest<Array<{
      question: BackendQuestion;
      selected_option: string | null;
      wrong_count: number;
      last_answered_at: string;
      paper_id?: string;
    }>>('/practice-sessions/wrong-answers');
    return values.map((item): WrongAnswerRecord => ({
      question: normalizeQuestion(item.question),
      selected_answer: item.selected_option,
      wrong_count: item.wrong_count,
      last_answered_at: item.last_answered_at,
      paper_id: item.paper_id,
    }));
  },
  async createWrongAnswerSession(questionIds: string[]) {
    const raw = await apiRequest<BackendPracticeSession>('/practice-sessions/wrong-answers/retry', {
      method: 'POST', body: JSON.stringify({ question_ids: questionIds }),
    });
    return normalizePracticeSession(raw);
  },
  async retryPracticeMistakes(sessionId: string) {
    const raw = await apiRequest<BackendPracticeSession>(
      `/practice-sessions/${encodeURIComponent(sessionId)}/retry-mistakes`,
      { method: 'POST' },
    );
    return normalizePracticeSession(raw);
  },
  async listModelProfiles() {
    const values = unwrapList(await apiRequest<BackendModelProfile[] | ApiList<BackendModelProfile>>('/model-profiles'));
    return values.map(normalizeProfile);
  },
  async createModelProfile(payload: Record<string, unknown>) {
    return normalizeProfile(await apiRequest<BackendModelProfile>('/model-profiles', {
      method: 'POST', body: JSON.stringify(modelProfilePayload(payload)),
    }));
  },
  async updateModelProfile(id: string, payload: Record<string, unknown>) {
    return normalizeProfile(await apiRequest<BackendModelProfile>(`/model-profiles/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(modelProfilePayload(payload)),
    }));
  },
  deleteModelProfile(id: string) {
    return apiRequest<void>(`/model-profiles/${encodeURIComponent(id)}`, { method: 'DELETE' });
  },
  testModelProfile(id: string) {
    return apiRequest<{ ok: boolean; latency_ms?: number; message?: string }>(
      `/model-profiles/${encodeURIComponent(id)}/test`, { method: 'POST' },
    );
  },
};

function normalizeEvent(raw: {
  id?: string;
  sequence: number;
  job_id: string;
  stage: string;
  progress: number;
  message?: string;
  payload?: Record<string, unknown>;
  created_at: string;
}): JobEvent {
  const payload = raw.payload ?? {};
  return {
    id: raw.id,
    sequence: raw.sequence,
    job_id: raw.job_id,
    stage: raw.stage,
    progress: raw.progress,
    message: raw.message,
    current_document: typeof payload.current_document === 'string' ? payload.current_document : null,
    current_topic: typeof payload.current_topic === 'string' ? payload.current_topic : null,
    counts: {
      generated: Number(payload.generated ?? 0),
      accepted: Number(payload.accepted ?? 0),
      rejected: Number(payload.rejected ?? 0),
      revised: Number(payload.revised ?? 0),
      target: Number(payload.target ?? payload.target_count ?? 0),
    },
    warning: typeof payload.warning === 'string' ? payload.warning : null,
    error: typeof payload.error === 'string' ? payload.error : null,
    created_at: raw.created_at,
  };
}

export function subscribeToJobEvents(
  jobId: string,
  callbacks: { onEvent: (event: JobEvent) => void; onError?: () => void },
) {
  const source = new EventSource(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/events`);
  const receive = (message: MessageEvent<string>) => {
    try {
      callbacks.onEvent(normalizeEvent(JSON.parse(message.data)));
    } catch {
      // Heartbeats or non-JSON events are intentionally ignored.
    }
  };
  source.onmessage = receive;
  ['progress', 'stage', 'job_event', 'completed', 'failed', 'cancelled'].forEach((name) => {
    source.addEventListener(name, receive as EventListener);
  });
  source.onerror = () => callbacks.onError?.();
  return () => source.close();
}
