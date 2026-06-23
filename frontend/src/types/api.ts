// 文档相关
export type DocumentStatus = 'indexed' | 'uploading' | 'parsing' | 'failed'

export interface DocumentOut {
  id: number
  tenant_id: string
  uploaded_by: string
  filename: string
  status: DocumentStatus
  chunk_count: number
  error_msg: string | null
  created_at: string
}

export type JobStatus = 'pending' | 'processing' | 'succeeded' | 'failed' | 'cancelled'

export interface IngestJobOut {
  id: number
  document_id: number
  job_type: string
  status: JobStatus
  attempt: number
  max_attempts: number
  error_msg: string | null
  created_at: string
  updated_at: string
}

// 问答相关
export interface AskRequest {
  question: string
  session_id: string
}

export interface SourceItem {
  doc_id: number
  chunk_id: string
  source: string
  page: number | null
  sheet_name: string | null
  distance: number
  relevance: number
}

export interface AskResponse {
  answer: string
  sources: SourceItem[]
  refused: boolean
  need_human: boolean
  human_task_id: number | null
}

export interface HistoryMessage {
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
}

export interface HistoryResponse {
  session_id: string
  messages: HistoryMessage[]
}

// 管理相关
export interface AdminStats {
  documents: {
    total: number
    indexed: number
    failed: number
  }
  qa: {
    total: number
    refused_rate: number
    human_rate: number
  }
}

export interface AdminQARecord {
  id: number
  tenant_id: string
  user_id: string
  session_id: string
  question: string
  answer: string
  has_source: boolean
  refused: boolean
  need_human: boolean
  sources: SourceItem[]
  total_tokens: number
  latency_ms: number
  created_at: string
}

export type HumanTaskStatus = 'pending' | 'claimed' | 'completed'

export interface HumanTaskOut {
  id: number
  chat_record_id: number
  tenant_id: string
  user_id: string
  session_id: string
  category: string
  reason: string
  status: HumanTaskStatus
  assigned_to: string | null
  claimed_at: string | null
  completed_at: string | null
  resolution: string | null
  created_at: string
  updated_at: string
}

export interface HumanTaskEventOut {
  id: number
  task_id: number
  actor_user_id: string
  action: string
  from_status: string
  to_status: string
  note: string | null
  created_at: string
}

// 通用错误
export interface ApiError {
  detail: string
  error_code: string
  request_id: string
}
