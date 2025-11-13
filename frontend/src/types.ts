export interface PartRequestItem {
  part_number: string
  manufacturer_hint?: string | null
}

export interface SearchResult {
  part_number: string
  manufacturer_name?: string | null
  alias_used?: string | null
  confidence?: number | null
  source_url?: string | null
  debug_log?: string | null
}

export interface SearchResponse {
  results: SearchResult[]
  debug: boolean
}

export interface UploadResponse {
  imported: number
  skipped: number
  errors: string[]
}

export interface PartRead extends SearchResult {
  id: number
  created_at: string
}

export interface ExportResponse {
  url: string
}
