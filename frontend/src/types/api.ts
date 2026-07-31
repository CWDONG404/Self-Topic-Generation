export type Id = string;

export type DocumentRole = 'outline' | 'source';
export type DocumentStatus = 'queued' | 'parsing' | 'ready' | 'warning' | 'failed' | 'archived';
export type JobStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'partial' | 'failed' | 'cancelled';
export type Difficulty = 'easy' | 'medium' | 'hard';
export type ModelProvider = 'openai_compatible' | 'ollama';
export type ModelRole = 'blueprint' | 'generator' | 'reviewer' | 'vision' | 'embedding';

export interface Library {
  id: Id;
  name: string;
  description?: string | null;
  document_count?: number;
  ready_document_count?: number;
  created_at: string;
  updated_at?: string;
}

export interface DocumentRecord {
  id: Id;
  library_id: Id;
  name: string;
  original_filename?: string;
  extension?: string;
  mime_type?: string;
  size_bytes?: number;
  role: DocumentRole;
  allow_as_evidence: boolean;
  status: DocumentStatus;
  progress: number;
  page_count?: number | null;
  chunk_count?: number | null;
  version?: number;
  warnings?: string[];
  error?: string | null;
  created_at: string;
  updated_at?: string;
}

export interface ModelCapabilities {
  structured_output: boolean;
  vision: boolean;
  embedding: boolean;
}

export interface ModelProfile {
  id: Id;
  name: string;
  provider: ModelProvider;
  base_url: string;
  model_name: string;
  capabilities: ModelCapabilities;
  default_roles: ModelRole[];
  has_api_key: boolean;
  is_available?: boolean | null;
  last_tested_at?: string | null;
  created_at: string;
}

export interface DocumentAllocation {
  document_id: Id;
  percentage: number;
}

export interface GenerationRequest {
  library_id: Id;
  outline_document_ids: Id[];
  source_allocations: DocumentAllocation[];
  question_count: number;
  execution_mode: 'cloud_allowed' | 'local_only';
  model_roles: Partial<Record<ModelRole, Id>>;
  random_seed?: number;
  allow_outline_as_evidence?: boolean;
}

export interface JobCounts {
  generated: number;
  accepted: number;
  rejected: number;
  revised: number;
  target: number;
}

export interface Job {
  id: Id;
  kind?: 'document_parse' | 'paper_generation';
  status: JobStatus;
  stage: string;
  progress: number;
  message?: string | null;
  counts?: Partial<JobCounts>;
  warnings?: string[];
  error?: string | null;
  paper_id?: Id | null;
  request?: GenerationRequest;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface JobEvent {
  id?: string;
  sequence: number;
  job_id: Id;
  stage: string;
  progress: number;
  message?: string;
  current_document?: string | null;
  current_topic?: string | null;
  counts?: Partial<JobCounts>;
  warning?: string | null;
  error?: string | null;
  created_at: string;
}

export interface CitationRect {
  x: number;
  y: number;
  width: number;
  height: number;
  page_width?: number;
  page_height?: number;
  coordinate_system?: 'top-left' | 'bottom-left';
}

export interface CitationAnchor {
  id: Id;
  document_id: Id;
  document_version_id?: Id;
  document_name: string;
  document_type?: string;
  chunk_id: Id;
  excerpt: string;
  excerpt_hash?: string;
  page_number?: number | null;
  rectangles?: CitationRect[];
  block_id?: string | null;
  start_offset?: number | null;
  end_offset?: number | null;
  file_url?: string;
}

export interface QuestionOption {
  key: 'A' | 'B' | 'C' | 'D';
  text: string;
}

export interface ReviewResult {
  id?: Id;
  status: 'pending' | 'passed' | 'failed' | 'needs_revision';
  independent_answer?: string | null;
  comments?: string[];
  reviewed_at?: string | null;
}

export interface Question {
  id: Id;
  stem: string;
  options: QuestionOption[];
  correct_answer: 'A' | 'B' | 'C' | 'D';
  explanation: string;
  knowledge_point: string;
  difficulty: Difficulty;
  citations: CitationAnchor[];
  review: ReviewResult;
  enabled: boolean;
  similarity_relaxed?: boolean;
  revision_count?: number;
  source_document_id?: Id;
  created_at?: string;
}

export interface Paper {
  id: Id;
  title: string;
  status: 'draft' | 'ready' | 'partial' | 'archived';
  question_count: number;
  enabled_question_count?: number;
  questions?: Question[];
  random_seed?: number;
  source_summary?: string;
  created_at: string;
  updated_at?: string;
}

export interface PracticeAnswer {
  question_id: Id;
  selected_answer: string | null;
  is_correct?: boolean | null;
  answered_at?: string;
}

export interface PracticeResult {
  score: number;
  correct_count: number;
  incorrect_count: number;
  unanswered_count: number;
  total_count: number;
  knowledge_points?: Array<{ name: string; correct: number; total: number }>;
}

export interface PracticeSession {
  id: Id;
  paper_id: Id;
  paper?: Paper;
  mode: 'practice' | 'exam' | 'wrong_answers';
  status: 'in_progress' | 'submitted';
  answers: PracticeAnswer[];
  current_question_index?: number;
  result?: PracticeResult | null;
  created_at: string;
  submitted_at?: string | null;
}

export interface WrongAnswerRecord {
  question: Question;
  selected_answer: string | null;
  wrong_count: number;
  last_answered_at: string;
  paper_id?: Id;
}

export interface CitationContent {
  document_id: Id;
  document_name: string;
  block_id?: string | null;
  text: string;
  highlighted_text?: string;
}

export interface ApiList<T> {
  items: T[];
  total?: number;
}
