/** 与后端 `Answer.as_dict()` / `TurnResult.as_dict()` 对齐的类型。 */

export interface Citation {
  ref: number;
  chunk_id: number;
  document_id: number;
  title: string;
  section: string;
  segments?: number[];
}

export interface EvidenceItem {
  ref: number;
  chunk_id: number;
  title: string;
  section: string;
  page: number;
  doc_type: string;
  score: number;
  sim?: number;
  overlap?: number;
  source: string;
  content: string;
}

export interface ChecklistItem {
  kind: "material" | "step" | "condition" | "notice" | string;
  text: string;
  ref: number | null;
  ordinal: number;
  segment?: number;
}

export interface Segment {
  index: number;
  question: string;
  intent: string;
  answerable: boolean;
  text: string;
  failed: boolean;
  refusal_reason?: string;
  citations: Citation[];
  evidence: EvidenceItem[];
  checklist: ChecklistItem[];
  notices: string[];
}

export interface TurnResult {
  conversation_id: string;
  turn: number;
  question: string;
  text: string;
  mode: string;
  intent: string;
  answerable: boolean;
  refusal_reason?: string;
  degraded: boolean;
  failed_segments: number;
  trace_id: string;
  latency_ms: number;
  notices: string[];
  matter_name: string;
  segments: Segment[];
  citations: Citation[];
  checklist: ChecklistItem[];
}

export interface SessionBrief {
  id: string;
  title: string;
  turn_count: number;
  last_active_at: string;
}

export interface StoredMessage {
  turn: number;
  role: "user" | "assistant";
  content: string;
  intent: string;
  answerable: boolean | null;
  refusal_reason: string;
  latency_ms: number;
  created_at: string;
  payload: Partial<TurnResult>;
}

export interface Me {
  user_key: string;
  audience: string;
  role: "student" | "admin";
  limits: Record<string, number>;
}
