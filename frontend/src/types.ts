export interface PartRequestItem {
  part_number: string
  manufacturer_hint?: string | null
}

export type MatchStatus = 'matched' | 'mismatch' | 'pending' | null

export interface StageStatus {
  name: string
  status: 'success' | 'low-confidence' | 'no-results' | 'skipped'
  provider?: string | null
  confidence?: number | null
  urls_considered?: number
  message?: string | null
}

export interface SearchResult {
  part_number: string
  manufacturer_name?: string | null
  alias_used?: string | null
  submitted_manufacturer?: string | null
  match_status?: MatchStatus
  match_confidence?: number | null
  confidence?: number | null
  source_url?: string | null
  debug_log?: string | null
  search_stage?: string | null
  stage_history?: StageStatus[]
}

export interface SearchResponse {
  results: SearchResult[]
  debug: boolean
}

export interface UploadResponse {
  imported: number
  skipped: number
  errors: string[]
  status_message?: string | null
}

export interface PartRead extends SearchResult {
  id: number
  created_at: string
}

export interface ExportResponse {
  url: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  username: string
  role: 'admin' | 'user'
}

export interface CredentialsUpdatePayload {
  username: string
  password: string
}

export interface AuthenticatedUser {
  username: string
  role: 'admin' | 'user'
}
