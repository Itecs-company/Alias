import axios from 'axios'
import {
  ExportResponse,
  PartRead,
  SearchResponse,
  UploadResponse,
  PartRequestItem,
  LoginResponse,
  CredentialsUpdatePayload,
  AuthenticatedUser,
  SearchLog,
  SystemSettings,
  SystemSettingsUpdate,
  TelegramTestResponse
} from './types'

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
const isLocalhost = (url: string) => /https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/i.test(url)
const shouldUseWindowOrigin =
  !rawBaseUrl ||
  (typeof window !== 'undefined' && rawBaseUrl.startsWith('http') && isLocalhost(rawBaseUrl) &&
    window.location.hostname !== 'localhost' &&
    window.location.hostname !== '127.0.0.1')

const resolvedBase = (() => {
  if (shouldUseWindowOrigin && typeof window !== 'undefined') {
    return `${window.location.origin}/api`
  }
  if (!rawBaseUrl) {
    return '/api'
  }
  if (rawBaseUrl.startsWith('http')) {
    return rawBaseUrl
  }
  return rawBaseUrl.startsWith('/') ? rawBaseUrl : `/${rawBaseUrl}`
})()

const client = axios.create({
  baseURL: resolvedBase
})

let unauthorizedHandler: (() => void) | null = null

const isLoginRequest = (url: unknown) =>
  typeof url === 'string' && url.split('?')[0].endsWith('/auth/login')

client.interceptors.response.use(
  (response) => response,
  (error) => {
    // Неверный пароль при входе — это не истекшая сессия
    if (error?.response?.status === 401 && unauthorizedHandler && !isLoginRequest(error?.config?.url)) {
      unauthorizedHandler()
    }
    return Promise.reject(error)
  }
)

export const getErrorStatus = (error: unknown): number | null =>
  axios.isAxiosError(error) ? error.response?.status ?? null : null

export const getErrorDetail = (error: unknown): string | null => {
  if (!axios.isAxiosError(error)) return null
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (item && typeof item === 'object' && 'msg' in item ? String(item.msg) : String(item)))
      .join('; ')
  }
  return null
}

export const setAuthToken = (token: string | null) => {
  if (token) {
    client.defaults.headers.common.Authorization = `Bearer ${token}`
  } else {
    delete client.defaults.headers.common.Authorization
  }
}

export const setUnauthorizedHandler = (handler: (() => void) | null) => {
  unauthorizedHandler = handler
}

export const login = async (username: string, password: string) => {
  const response = await client.post<LoginResponse>('/auth/login', { username, password })
  return response.data
}

export const fetchProfile = async () => {
  const response = await client.get<AuthenticatedUser>('/auth/me')
  return response.data
}

export const updateCredentials = async (payload: CredentialsUpdatePayload) => {
  const response = await client.post<{ username: string; message: string }>('/auth/credentials', payload)
  return response.data
}

export const searchParts = async (items: PartRequestItem[], debug: boolean, stages?: string[] | null) => {
  const response = await client.post<SearchResponse>('/search', { items, debug, stages })
  return response.data
}

export const listParts = async () => {
  const response = await client.get<PartRead[]>('/parts')
  return response.data
}

export const createPart = async (item: PartRequestItem) => {
  const response = await client.post<PartRead>('/parts', item)
  return response.data
}

export const uploadExcel = async (file: File, debug: boolean) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('debug', String(debug))
  const response = await client.post<UploadResponse>('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
  return response.data
}

export const exportExcel = async () => {
  const response = await client.get<ExportResponse>('/export/excel')
  return response.data
}

export const exportPdf = async () => {
  const response = await client.get<ExportResponse>('/export/pdf')
  return response.data
}

export const downloadExport = async (url: string) => {
  const path = url.split(/[?#]/)[0]
  const rawName = path.split('/').filter(Boolean).pop()
  if (!rawName) {
    throw new Error('Некорректная ссылка на файл')
  }
  let filename = rawName
  try {
    filename = decodeURIComponent(rawName)
  } catch {
    filename = rawName
  }
  const response = await client.get<Blob>(`/download/${encodeURIComponent(filename)}`, { responseType: 'blob' })
  const objectUrl = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  try {
    link.click()
  } finally {
    document.body.removeChild(link)
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  }
}

export const fetchLogs = async (params: { provider?: string; direction?: string; q?: string; limit?: number }) => {
  const response = await client.get<SearchLog[]>('/logs', { params })
  return response.data
}

export const deletePartById = async (id: number) => {
  await client.delete(`/parts/${id}`)
}

export const getSettings = async () => {
  const response = await client.get<SystemSettings>('/settings')
  return response.data
}

export const updateSettings = async (payload: SystemSettingsUpdate) => {
  const response = await client.put<SystemSettings>('/settings', payload)
  return response.data
}

export const testTelegram = async (message?: string) => {
  const response = await client.post<TelegramTestResponse>('/settings/test-telegram', message ? { message } : {})
  return response.data
}
