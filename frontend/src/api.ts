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
  SearchLog
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

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && unauthorizedHandler) {
      unauthorizedHandler()
    }
    return Promise.reject(error)
  }
)

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

export const fetchLogs = async (params: { provider?: string; direction?: string; q?: string; limit?: number }) => {
  const response = await client.get<SearchLog[]>('/logs', { params })
  return response.data
}

export const deletePartById = async (id: number) => {
  await client.delete(`/parts/${id}`)
}
