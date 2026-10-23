import { del, get, post, put } from "./http";

export interface Job {
  id: number;
  source_path: string;
  doc_type: string;
  status: string;
  stage: string;
  message: string;
  document_id: number | null;
  created_at: string;
}

export interface Conflict {
  field: string;
  draft: string;
  published: string;
  published_doc: string;
  published_doc_id: number;
}

export interface ReviewRow {
  id: number;
  title: string;
  doc_type: string;
  dept: string;
  version: number;
  chunks: number;
  embedded: number;
  created_at: string;
  conflicts: Conflict[];
}

export interface DocRow {
  id: number;
  title: string;
  doc_type: string;
  status: string;
  version: number;
  chunks: number;
  embedded: number;
  published_at: string | null;
  created_at: string;
}

export interface MatterRow {
  code: string;
  name: string;
  dept: string;
  category: string;
  audience: string;
  location: string;
  contact: string;
  summary: string;
  status: string;
  steps: number;
}

export interface TermRow {
  id: number;
  term: string;
  canonical: string;
  term_type: string;
  weight: number;
}

export interface ModelRow {
  slot: string;
  base_url: string;
  model: string;
  has_key: boolean;
  overridden: boolean;
  enabled: boolean;
  note: string;
}

export interface Dashboard {
  documents: { total: number; published: number; draft: number; archived: number };
  chunks: { total: number; published: number; embedded: number };
  matters: number;
  flows: number;
  terms: number;
  jobs: Record<string, number>;
  queue_depth: number;
  qa_24h: {
    turns: number;
    refused: number;
    refusal_rate: number;
    p50_ms: number;
    p95_ms: number;
  };
}

export interface UploadResult {
  job_id: number;
  filename: string;
  size: number;
  doc_type: string;
  checksum: string;
}

export const ops = {
  dashboard: () => get<Dashboard>("/ops/dashboard"),

  upload: (file: File, docType: string, dept: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);
    form.append("dept", dept);
    return post<UploadResult>("/ops/uploads", form);
  },
  jobs: (status?: string) => get<Job[]>(`/ops/jobs${status ? `?status=${status}` : ""}`),
  retryJob: (id: number) => post<{ job_id: number; status: string }>(`/ops/jobs/${id}/retry`),

  review: () => get<ReviewRow[]>("/ops/review"),
  publish: (id: number) => post(`/ops/review/${id}/publish`),
  archive: (id: number) => post(`/ops/review/${id}/archive`),

  documents: (query = "") =>
    get<DocRow[]>(`/ops/documents?query=${encodeURIComponent(query)}`),
  versions: (id: number) => get<DocRow[]>(`/ops/documents/${id}/versions`),
  rollback: (id: number) => post(`/ops/documents/${id}/rollback`),
  embed: (id: number) => post<{ filled: number }>(`/ops/documents/${id}/embed`),

  matters: (query = "") => get<MatterRow[]>(`/ops/matters?query=${encodeURIComponent(query)}`),
  saveMatter: (body: Partial<MatterRow>) => post<MatterRow>("/ops/matters", body),

  terms: (query = "") => get<TermRow[]>(`/ops/terms?query=${encodeURIComponent(query)}`),
  saveTerms: (rows: Partial<TermRow>[]) =>
    post<{ created: number; total: number }>("/ops/terms", rows),
  deleteTerm: (id: number) => del<{ deleted: number }>(`/ops/terms/${id}`),

  models: () => get<ModelRow[]>("/ops/models"),
  saveModel: (slot: string, body: Partial<ModelRow>) =>
    put<ModelRow>(`/ops/models/${slot}`, body),
};
