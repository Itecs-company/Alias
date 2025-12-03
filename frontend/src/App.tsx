import { Fragment, SyntheticEvent, useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { keyframes } from '@emotion/react'
import {
  AppBar,
  Avatar,
  Box,
  Button,
  Checkbox,
  Chip,
  Container,
  CssBaseline,
  Divider,
  FormControlLabel,
  Grid,
  IconButton,
  LinearProgress,
  Paper,
  Snackbar,
  Stack,
  Step,
  StepLabel,
  Stepper,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Toolbar,
  Tooltip,
  Typography
} from '@mui/material'
import { ThemeProvider, alpha } from '@mui/material/styles'
import {
  DarkMode,
  LightMode,
  BugReport,
  FileDownload,
  Upload,
  AddCircleOutline,
  Search,
  Bolt,
  Lock,
  Logout,
  AcUnit,
  DeleteForever,
  VisibilityOff,
  Visibility,
  ListAlt,
  FilterAlt,
  Psychology,
  Settings
} from '@mui/icons-material'
import { ToggleButton, ToggleButtonGroup } from '@mui/material'

import { ThemeMode, buildTheme } from './theme'
import {
  createPart,
  exportExcel,
  exportPdf,
  listParts,
  searchParts,
  uploadExcel,
  login as loginRequest,
  updateCredentials as updateCredentialsRequest,
  setAuthToken,
  setUnauthorizedHandler,
  fetchProfile,
  fetchLogs,
  deletePartById
} from './api'
import { MatchStatus, PartRead, PartRequestItem, SearchLog, SearchResult, StageStatus } from './types'

const emptyItem: PartRequestItem = { part_number: '', manufacturer_hint: '' }

const THEME_OPTIONS: { value: ThemeMode; label: string; icon: JSX.Element }[] = [
  { value: 'light', label: 'Светлая', icon: <LightMode fontSize="small" /> },
  { value: 'dark', label: 'Тёмная', icon: <DarkMode fontSize="small" /> },
  { value: 'holiday', label: 'Зимняя 3D', icon: <AcUnit fontSize="small" /> }
]

const STAGE_SEQUENCE = ['Internet', 'googlesearch', 'OpenAI'] as const
type StageName = (typeof STAGE_SEQUENCE)[number]
type StageState = 'idle' | 'pending' | 'active' | 'done' | 'warning' | 'error' | 'skipped'

const stageLabels: Record<StageName, string> = {
  Internet: 'Internet · общий поиск',
  googlesearch: 'GoogleSearch · Google CSE',
  OpenAI: 'OpenAI · ChatGPT'
}

const stageStatusDescription: Record<StageStatus['status'], string> = {
  success: 'успешно',
  'low-confidence': 'низкая уверенность',
  'no-results': 'нет результатов',
  skipped: 'пропущено'
}

const stageStatusChipColor: Record<StageStatus['status'], 'default' | 'success' | 'warning' | 'error'> = {
  success: 'success',
  'low-confidence': 'warning',
  'no-results': 'error',
  skipped: 'default'
}

const progressStateLabel: Record<StageState, string> = {
  idle: 'ожидание',
  pending: 'ожидание',
  active: 'выполняется',
  done: 'готово',
  warning: 'низкая уверенность',
  error: 'нет результата',
  skipped: 'пропущено'
}

const progressStateColor: Record<StageState, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  idle: 'default',
  pending: 'default',
  active: 'info',
  done: 'success',
  warning: 'warning',
  error: 'error',
  skipped: 'default'
}

type StageProgressEntry = { name: StageName; state: StageState; message?: string | null }

const matchStatusLabels: Record<Exclude<MatchStatus, null>, string> = {
  matched: 'совпадает',
  mismatch: 'расхождение',
  pending: 'ожидает проверки'
}

const matchStatusColor: Record<Exclude<MatchStatus, null>, 'success' | 'error' | 'warning'> = {
  matched: 'success',
  mismatch: 'error',
  pending: 'warning'
}

type AuthState = { token: string; username: string; role: 'admin' | 'user' }
const AUTH_STORAGE_KEY = 'aliasfinder:auth'
const THEME_STORAGE_KEY = 'aliasfinder:theme'

const twinkle = keyframes`
  0% { opacity: 0.25; transform: translateY(0px) scale(0.9); }
  50% { opacity: 0.95; transform: translateY(4px) scale(1.05); }
  100% { opacity: 0.4; transform: translateY(0px) scale(0.9); }
`

const drift = keyframes`
  0% { transform: translateY(-5%) translateX(0); }
  50% { transform: translateY(5%) translateX(6%); }
  100% { transform: translateY(-5%) translateX(0); }
`

const glowwave = keyframes`
  0% { opacity: 0.25; }
  50% { opacity: 0.55; }
  100% { opacity: 0.25; }
`

const garlandSwing = keyframes`
  0% { transform: translateY(0) }
  50% { transform: translateY(4px) }
  100% { transform: translateY(0) }
`

const ResizableCell = ({
  column,
  width,
  onResize,
  children
}: {
  column: string
  width: number
  onResize: (column: string, width: number) => void
  children: React.ReactNode
}) => {
  const [isResizing, setIsResizing] = useState(false)
  const [startX, setStartX] = useState(0)
  const [startWidth, setStartWidth] = useState(width)

  const handleMouseDown = (e: React.MouseEvent) => {
    setIsResizing(true)
    setStartX(e.clientX)
    setStartWidth(width)
    e.preventDefault()
  }

  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      const diff = e.clientX - startX
      const newWidth = startWidth + diff
      onResize(column, newWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing, startX, startWidth, column, onResize])

  return (
    <TableCell
      sx={{
        fontWeight: 600,
        width: width,
        minWidth: width,
        maxWidth: width,
        position: 'relative',
        userSelect: isResizing ? 'none' : 'auto',
        cursor: isResizing ? 'col-resize' : 'default'
      }}
    >
      {children}
      <Box
        onMouseDown={handleMouseDown}
        sx={{
          position: 'absolute',
          right: 0,
          top: 0,
          bottom: 0,
          width: 5,
          cursor: 'col-resize',
          backgroundColor: isResizing ? 'primary.main' : 'transparent',
          '&:hover': {
            backgroundColor: 'primary.light'
          },
          zIndex: 1
        }}
      />
    </TableCell>
  )
}

const HolidayLights = () => {
  const palette = ['#ff6b6b', '#ffd166', '#6dd3c2', '#74c0fc', '#c8b6ff']
  return (
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        overflow: 'hidden',
        pointerEvents: 'none',
        zIndex: -1,
        background:
          'radial-gradient(circle at 10% 10%, rgba(15,163,177,0.12), transparent 40%), radial-gradient(circle at 80% 20%, rgba(255,107,154,0.12), transparent 45%), radial-gradient(circle at 30% 80%, rgba(139,92,246,0.12), transparent 40%), linear-gradient(180deg, #e8f6ff 0%, #e7f0ff 45%, #f8f3ff 100%)'
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          top: 12,
          left: 0,
          right: 0,
          display: 'flex',
          justifyContent: 'space-evenly',
          px: 4,
          zIndex: 1,
          animation: `${garlandSwing} 6s ease-in-out infinite`
        }}
      >
        {Array.from({ length: 28 }).map((_, index) => (
          <Box
            key={index}
            sx={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: palette[index % palette.length],
              boxShadow: `0 0 12px ${palette[index % palette.length]}`,
              animation: `${twinkle} 2.6s ease-in-out infinite`,
              animationDelay: `${index * 70}ms`
            }}
          />
        ))}
      </Box>
      <Box
        sx={{
          position: 'absolute',
          inset: '-20% -30% 0 -30%',
          background:
            'radial-gradient(circle at 20% 20%, rgba(15,163,177,0.16), transparent 35%), radial-gradient(circle at 80% 30%, rgba(255,107,154,0.18), transparent 32%), radial-gradient(circle at 45% 70%, rgba(139,92,246,0.18), transparent 40%)',
          filter: 'blur(2px)',
          animation: `${drift} 18s ease-in-out infinite`
        }}
      />
      <Box
        sx={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(ellipse at top, rgba(255,255,255,0.25), transparent 45%), radial-gradient(ellipse at bottom, rgba(135,206,250,0.15), transparent 50%)',
          mixBlendMode: 'screen',
          animation: `${glowwave} 8s ease-in-out infinite`
        }}
      />
    </Box>
  )
}

export function App() {
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    if (typeof window === 'undefined') return 'light'
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'dark' || stored === 'holiday' ? (stored as ThemeMode) : 'light'
  })
  const [auth, setAuth] = useState<AuthState | null>(() => {
    if (typeof window === 'undefined') return null
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AuthState) : null
  })
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)
  const [credentialsForm, setCredentialsForm] = useState({ username: '', password: '' })
  const [credentialsLoading, setCredentialsLoading] = useState(false)
  const [debugMode, setDebugMode] = useState(false)
  const [items, setItems] = useState<PartRequestItem[]>([{ ...emptyItem }])
  const [results, setResults] = useState<SearchResult[]>([])
  const [history, setHistory] = useState<PartRead[]>([])
  const [historyFilter, setHistoryFilter] = useState('')
  const [historyHidden, setHistoryHidden] = useState(false)
  const [manufacturerFilter, setManufacturerFilter] = useState<'all' | 'found' | 'missing'>('all')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [activePage, setActivePage] = useState<'dashboard' | 'logs' | 'settings'>('dashboard')
  const [logs, setLogs] = useState<SearchLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [logFilters, setLogFilters] = useState<{ provider: string; direction: string; q: string }>({
    provider: '',
    direction: '',
    q: ''
  })
  const tableData = useMemo(() => {
    const sorted = [...history].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    )
    return sorted.map((record) => ({
      id: record.id,
      key: `${record.id}-${record.part_number}`,
      article: record.part_number,
      manufacturer: record.manufacturer_name ?? '—',
      alias: record.alias_used ?? '—',
      submitted: record.submitted_manufacturer ?? '—',
      matchStatus: (record.match_status ?? null) as MatchStatus,
      matchConfidence: record.match_confidence ?? null,
      sourceUrl: record.source_url ?? null,
      confidence: record.confidence ?? null
    }))
  }, [history])
  const filteredTableData = useMemo(() => {
    return tableData.filter((row) => {
      const isFound = row.manufacturer !== '—' && row.matchStatus !== 'mismatch'
      const isMissing = row.manufacturer === '—' || row.matchStatus === 'mismatch'
      if (manufacturerFilter === 'found') return isFound
      if (manufacturerFilter === 'missing') return isMissing
      return true
    })
  }, [manufacturerFilter, tableData])
  const filteredHistory = useMemo(() => {
    if (historyHidden) return []
    const term = historyFilter.trim().toLowerCase()
    if (!term) return history
    return history.filter((record) => {
      return (
        record.part_number.toLowerCase().includes(term) ||
        (record.manufacturer_name ?? '').toLowerCase().includes(term) ||
        (record.submitted_manufacturer ?? '').toLowerCase().includes(term)
      )
    })
  }, [history, historyFilter, historyHidden])
  const [snackbar, setSnackbar] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [stageProgress, setStageProgress] = useState<StageProgressEntry[]>(() =>
    STAGE_SEQUENCE.map((name) => ({ name, state: 'idle' }))
  )
  const [uploadState, setUploadState] = useState<{ status: 'idle' | 'uploading' | 'done' | 'error'; message?: string }>(
    { status: 'idle' }
  )
  const [uploadedItems, setUploadedItems] = useState<PartRequestItem[]>([])
  const [tableSize, setTableSize] = useState<'small' | 'medium'>('small')
  const [fontSize, setFontSize] = useState<'small' | 'medium' | 'large'>('medium')
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({
    article: 120,
    manufacturer: 150,
    alias: 120,
    submitted: 120,
    match: 120,
    confidence: 100,
    source: 200,
    actions: 300
  })

  // Вычисляем размер шрифта в зависимости от выбранного значения
  const tableFontSize = useMemo(() => {
    switch (fontSize) {
      case 'small':
        return '0.75rem'  // 12px
      case 'medium':
        return '0.875rem' // 14px
      case 'large':
        return '1rem'     // 16px
      default:
        return '0.875rem'
    }
  }, [fontSize])
  const [currentService, setCurrentService] = useState('—')
  const progressTimerRef = useRef<number | null>(null)
  const progressIndexRef = useRef(0)
  const handleThemeChange = (_: SyntheticEvent, value: ThemeMode | null) => {
    if (value) setThemeMode(value)
  }
  const refreshHistory = async () => {
    try {
      const data = await listParts()
      setHistory(data)
    } catch (error) {
      setSnackbar('Не удалось получить историю поиска')
    }
  }

  const loadLogs = async () => {
    try {
      setLogsLoading(true)
      const data = await fetchLogs({ ...logFilters, limit: 200 })
      setLogs(data)
    } catch (error) {
      setSnackbar('Не удалось загрузить логи')
    } finally {
      setLogsLoading(false)
    }
  }

  const handleDeletePartRow = async (id: number) => {
    try {
      await deletePartById(id)
      await refreshHistory()
      setSnackbar('Строка удалена')
    } catch (error) {
      setSnackbar('Не удалось удалить строку')
    }
  }

  const theme = useMemo(() => buildTheme(themeMode), [themeMode])
  const isAdmin = auth?.role === 'admin'
  const gradientBackground = useMemo(() => {
    if (themeMode === 'holiday') {
      return 'radial-gradient(circle at 10% 10%, rgba(15,163,177,0.25), transparent 40%), radial-gradient(circle at 80% 20%, rgba(255,107,154,0.18), transparent 45%), radial-gradient(circle at 30% 80%, rgba(139,92,246,0.2), transparent 40%), linear-gradient(180deg, #e8f6ff 0%, #e7f0ff 45%, #f8f3ff 100%)'
    }
    if (themeMode === 'light') {
      return 'radial-gradient(circle at 20% 20%, rgba(13,114,133,0.08), transparent 40%), radial-gradient(circle at 80% 0%, rgba(132,94,247,0.12), transparent 45%), linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%)'
    }
    return 'radial-gradient(circle at 25% 25%, rgba(77,171,247,0.15), transparent 45%), radial-gradient(circle at 80% 0%, rgba(27,131,172,0.15), transparent 45%), linear-gradient(180deg, #05090f 0%, #0f1827 100%)'
  }, [themeMode])
  const activeStepperIndex = useMemo(() => {
    const activeIdx = stageProgress.findIndex((entry) => entry.state === 'active')
    if (activeIdx >= 0) return activeIdx
    const doneCount = stageProgress.filter((entry) => entry.state === 'done').length
    return doneCount ? doneCount - 1 : 0
  }, [stageProgress])

  const resetProgress = () => {
    setStageProgress(STAGE_SEQUENCE.map((name) => ({ name, state: 'idle' })))
    setCurrentService('—')
  }

  const renderMatchChip = (status: MatchStatus | undefined, confidence?: number | null) => {
    if (!status) {
      return '—'
    }
    const normalized = status as Exclude<MatchStatus, null>
    const suffix = normalized !== 'pending' && confidence ? ` (${(confidence * 100).toFixed(1)}%)` : ''
    return (
      <Chip
        size="small"
        label={`${matchStatusLabels[normalized]}${suffix}`}
        color={matchStatusColor[normalized]}
        variant="outlined"
      />
    )
  }

  const startProgress = () => {
    if (progressTimerRef.current) {
      window.clearInterval(progressTimerRef.current)
    }
    progressIndexRef.current = 0
    setStageProgress(
      STAGE_SEQUENCE.map((name, index) => ({ name, state: index === 0 ? 'active' : 'pending' }))
    )
    setCurrentService(stageLabels[STAGE_SEQUENCE[0]])
    progressTimerRef.current = window.setInterval(() => {
      progressIndexRef.current = Math.min(progressIndexRef.current + 1, STAGE_SEQUENCE.length - 1)
      setStageProgress((prev) =>
        prev.map((entry, idx) => {
          if (idx < progressIndexRef.current) return { ...entry, state: 'done' as StageState }
          if (idx === progressIndexRef.current) return { ...entry, state: 'active' as StageState }
          return { ...entry, state: 'pending' as StageState }
        })
      )
      setCurrentService(stageLabels[STAGE_SEQUENCE[progressIndexRef.current]])
      if (progressIndexRef.current === STAGE_SEQUENCE.length - 1 && progressTimerRef.current) {
        window.clearInterval(progressTimerRef.current)
        progressTimerRef.current = null
      }
    }, 2200)
  }

  const finishProgress = (history?: StageStatus[]) => {
    if (progressTimerRef.current) {
      window.clearInterval(progressTimerRef.current)
      progressTimerRef.current = null
    }
    if (!history || history.length === 0) {
      resetProgress()
      return
    }
    setStageProgress(
      STAGE_SEQUENCE.map((name) => {
        const stage = history.find((item) => item.name === name)
        if (!stage) {
          return { name, state: 'pending' as StageState }
        }
        const mappedState: StageState =
          stage.status === 'success'
            ? 'done'
            : stage.status === 'low-confidence'
            ? 'warning'
            : stage.status === 'no-results'
            ? 'error'
            : 'skipped'
        return { name, state: mappedState, message: stage.message ?? null }
      })
    )
    const finalStage =
      [...history].reverse().find((stage) => stage.status === 'success') ||
      history.find((stage) => stage.status === 'low-confidence')
    if (finalStage) {
      const mappedName = finalStage.name as StageName
      setCurrentService(stageLabels[mappedName] ?? finalStage.name)
    } else {
      setCurrentService('—')
    }
  }

  const handleLogout = (message?: string) => {
    setAuth(null)
    setResults([])
    setHistory([])
    setItems([{ ...emptyItem }])
    resetProgress()
    setLoading(false)
    setCredentialsForm({ username: '', password: '' })
    if (message) {
      setSnackbar(message)
    }
  }

  useEffect(() => {
    return () => {
      if (progressTimerRef.current) {
        window.clearInterval(progressTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => handleLogout('Сессия истекла. Авторизуйтесь снова.'))
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (auth) {
      window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth))
    } else {
      window.localStorage.removeItem(AUTH_STORAGE_KEY)
    }
  }, [auth])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(THEME_STORAGE_KEY, themeMode)
  }, [themeMode])

  useEffect(() => {
    if (!auth) {
      setAuthToken(null)
      return
    }
    setAuthToken(auth.token)
    const verify = async () => {
      try {
        await fetchProfile()
        await refreshHistory()
      } catch (error) {
        handleLogout('Сессия истекла. Авторизуйтесь снова.')
      }
    }
    verify()
  }, [auth])

  useEffect(() => {
    if (activePage !== 'logs' || !auth) return
    loadLogs()
  }, [activePage, auth, logFilters])

  const handleLoginSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setLoginLoading(true)
    setLoginError(null)
    try {
      const response = await loginRequest(loginForm.username.trim(), loginForm.password)
      setAuth({ token: response.access_token, username: response.username, role: response.role })
      setSnackbar(`Добро пожаловать, ${response.username}`)
    } catch (error) {
      setLoginError('Неверный логин или пароль')
    } finally {
      setLoginLoading(false)
    }
  }

  const handleCredentialsUpdate = async () => {
    if (!credentialsForm.username.trim() || !credentialsForm.password.trim()) {
      setSnackbar('Укажите новый логин и пароль')
      return
    }
    setCredentialsLoading(true)
    try {
      const response = await updateCredentialsRequest({
        username: credentialsForm.username.trim(),
        password: credentialsForm.password.trim()
      })
      setSnackbar(`Учетные данные обновлены для ${response.username}`)
      setCredentialsForm({ username: '', password: '' })
    } catch (error) {
      setSnackbar('Не удалось обновить учетные данные')
    } finally {
      setCredentialsLoading(false)
    }
  }

  const handleItemChange = (index: number, key: keyof PartRequestItem, value: string) => {
    setItems((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], [key]: value }
      return next
    })
  }

  const addRow = () => setItems((prev) => [...prev, { ...emptyItem }])

  const removeRow = (index: number) =>
    setItems((prev) => (prev.length === 1 ? prev : prev.filter((_, idx) => idx !== index)))

  const performSearch = async (targets: PartRequestItem[], stages?: string[] | null) => {
    const filled = targets.filter((item) => item.part_number.trim().length)
    if (!filled.length) {
      setSnackbar('Добавьте хотя бы один артикул для поиска')
      finishProgress()
      return
    }
    setLoading(true)
    startProgress()
    let latestStageHistory: StageStatus[] | undefined
    try {
      const response = await searchParts(filled, debugMode, stages)
      latestStageHistory = response.results[0]?.stage_history
      setResults(response.results)
      await refreshHistory()
      if (!response.results.length) {
        setSnackbar('Производители не найдены')
      }
    } catch (error) {
      setSnackbar('Ошибка при выполнении поиска')
    } finally {
      setLoading(false)
      finishProgress(latestStageHistory)
    }
  }

  const submitSearch = async () => {
    await performSearch(items)
  }

  const submitManual = async () => {
    const [first] = items
    if (!first.part_number.trim()) {
      setSnackbar('Укажите артикул для ручного добавления')
      return
    }
    try {
      const created = await createPart(first)
      setSnackbar(`Товар добавлен: ${created.part_number}`)
      await refreshHistory()
      // Очищаем форму после успешного добавления
      setItems([{ ...emptyItem }])
    } catch (error) {
      setSnackbar('Не удалось добавить товар')
    }
  }

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const input = event.target
    const file = input.files?.[0]
    if (!file) {
      input.value = ''
      return
    }
    try {
      setUploadState({ status: 'uploading', message: `Загружаем ${file.name}…` })
      const response = await uploadExcel(file, debugMode)
      const baseMessage = `Импортировано: ${response.imported}, пропущено: ${response.skipped}`
      const errorMessage = response.errors.length ? ` Ошибки: ${response.errors.join(', ')}` : ''
      const statusMessage = response.status_message ?? `Файл ${file.name} обработан`
      setUploadedItems(response.items ?? [])
      setItems((response.items ?? []).length ? response.items : [{ ...emptyItem }])
      setUploadState({ status: 'done', message: `${statusMessage}. Данные добавлены в таблицу` })
      setSnackbar(`${statusMessage}. ${baseMessage}${errorMessage}`)
      await refreshHistory()
    } catch (error) {
      setUploadState({ status: 'error', message: 'Не удалось загрузить файл' })
      setUploadedItems([])
      setSnackbar('Не удалось загрузить файл')
    } finally {
      input.value = ''
    }
  }

  const runUploadedSearch = async () => {
    await performSearch(uploadedItems)
  }

  const handleSelectAll = useCallback((checked: boolean) => {
    if (checked) {
      setSelectedIds(new Set(filteredTableData.map(row => row.id)))
    } else {
      setSelectedIds(new Set())
    }
  }, [filteredTableData])

  const handleSelectRow = useCallback((id: number, checked: boolean) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (checked) {
        next.add(id)
      } else {
        next.delete(id)
      }
      return next
    })
  }, [])

  const handleSearchSelected = useCallback(async (stage: string) => {
    if (selectedIds.size === 0) {
      setSnackbar('Выберите хотя бы одну строку для поиска')
      return
    }
    const selectedParts = history.filter(part => selectedIds.has(part.id)).map(part => ({
      part_number: part.part_number,
      manufacturer_hint: part.submitted_manufacturer ?? null
    }))
    await performSearch(selectedParts, [stage])
    setSelectedIds(new Set())
  }, [selectedIds, history])

  const handleSearchSingleRow = useCallback(async (partId: number, stages?: string[] | null) => {
    const part = history.find(p => p.id === partId)
    if (!part) return

    const partToSearch: PartRequestItem = {
      part_number: part.part_number,
      manufacturer_hint: part.submitted_manufacturer ?? null
    }
    await performSearch([partToSearch], stages)
  }, [history])

  const handleColumnResize = useCallback((column: string, width: number) => {
    setColumnWidths(prev => ({
      ...prev,
      [column]: Math.max(80, width)
    }))
  }, [])

  const handleExport = async (type: 'pdf' | 'excel') => {
    try {
      const response = type === 'pdf' ? await exportPdf() : await exportExcel()
      if (typeof window !== 'undefined') {
        const absoluteUrl =
          response.url.startsWith('http://') ||
          response.url.startsWith('https://') ||
          response.url.startsWith('//')
            ? response.url
            : `${window.location.origin}${response.url.startsWith('/') ? '' : '/'}${response.url}`
        const tokenizedUrl = auth?.token
          ? `${absoluteUrl}${absoluteUrl.includes('?') ? '&' : '?'}token=${encodeURIComponent(auth.token)}`
          : absoluteUrl
        window.open(tokenizedUrl, '_blank', 'noopener')
      }
      setSnackbar(type === 'pdf' ? 'PDF сформирован' : 'Excel сформирован')
    } catch (error) {
      setSnackbar('Не удалось выгрузить данные')
    }
  }
  if (!auth) {
    return (
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <Box
            sx={{
              minHeight: '100vh',
              background: gradientBackground,
              backgroundColor: (theme) => theme.palette.background.default,
              display: 'flex',
              alignItems: 'center',
              py: 8,
              position: 'relative',
              overflow: 'hidden'
            }}
          >
            {themeMode === 'holiday' && <HolidayLights />}
            <Container maxWidth="sm" sx={{ position: 'relative', zIndex: 1 }}>
              <Paper
                elevation={12}
              sx={{
                p: { xs: 3, md: 5 },
                borderRadius: 4,
                border: '1px solid',
                borderColor: 'divider',
                backdropFilter: 'blur(14px)',
                background: (theme) =>
                  theme.palette.mode === 'light'
                    ? 'linear-gradient(135deg, rgba(255,255,255,0.95), rgba(240,248,255,0.92))'
                    : 'linear-gradient(135deg, rgba(10,15,25,0.9), rgba(22,30,45,0.9))'
              }}
            >
              <Stack component="form" spacing={3} onSubmit={handleLoginSubmit}>
                <Stack spacing={1} alignItems="center">
                  <Avatar sx={{ bgcolor: 'secondary.main', width: 64, height: 64 }}>
                    <Lock />
                  </Avatar>
                  <Typography variant="h4" sx={{ fontWeight: 600 }} textAlign="center">
                    Авторизация AliasFinder
                  </Typography>
                  <Typography color="text.secondary" textAlign="center">
                    Введите действующие учётные данные. Расширенные операции и смена логина/пароля доступны только администратору.
                  </Typography>
                </Stack>
                <TextField
                  label="Логин"
                  value={loginForm.username}
                  onChange={(event) => setLoginForm((prev) => ({ ...prev, username: event.target.value }))}
                  fullWidth
                  required
                />
                <TextField
                  label="Пароль"
                  type="password"
                  value={loginForm.password}
                  onChange={(event) => setLoginForm((prev) => ({ ...prev, password: event.target.value }))}
                  fullWidth
                  required
                />
                {loginError && (
                  <Typography color="error" variant="body2">
                    {loginError}
                  </Typography>
                )}
                <Button type="submit" variant="contained" size="large" disabled={loginLoading}>
                  {loginLoading ? 'Вход…' : 'Войти'}
                </Button>
              </Stack>
            </Paper>
              <Box mt={3} textAlign="center">
                <ToggleButtonGroup
                  exclusive
                  value={themeMode}
                  size="small"
                  onChange={handleThemeChange}
                  aria-label="Переключение тем"
                >
                  {THEME_OPTIONS.map((option) => (
                    <ToggleButton key={option.value} value={option.value} aria-label={option.label}>
                      <Stack direction="row" spacing={0.5} alignItems="center">
                        {option.icon}
                        <Typography variant="body2">{option.label}</Typography>
                      </Stack>
                    </ToggleButton>
                  ))}
                </ToggleButtonGroup>
              </Box>
          </Container>
        </Box>
        <Snackbar
          open={Boolean(snackbar)}
          message={snackbar}
          autoHideDuration={4000}
          onClose={() => setSnackbar(null)}
        />
      </ThemeProvider>
    )
  }

    return (
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Box
          sx={{
            minHeight: '100vh',
            background: gradientBackground,
            backgroundColor: (theme) => theme.palette.background.default,
            color: 'text.primary',
            position: 'relative',
            overflow: 'hidden'
          }}
        >
          {themeMode === 'holiday' && <HolidayLights />}
          <Box sx={{ position: 'relative', zIndex: 1 }}>
            <AppBar
              position="sticky"
              color="transparent"
              elevation={0}
              sx={{
                backdropFilter: 'blur(14px)',
                backgroundColor: (theme) => alpha(theme.palette.background.paper, 0.8),
                borderBottom: '1px solid',
                borderColor: 'divider'
              }}
            >
              <Toolbar>
                <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 600 }}>
                  AliasFinder · интеллектуальный подбор производителя
                </Typography>
                <ToggleButtonGroup
                  value={activePage}
                  exclusive
                  size="small"
                  onChange={(_, value) => value && setActivePage(value)}
                  sx={{ mr: 2 }}
                >
                  <ToggleButton value="dashboard" aria-label="Рабочая область">
                    <Bolt fontSize="small" />
                  </ToggleButton>
                  <ToggleButton value="logs" aria-label="Логи">
                    <ListAlt fontSize="small" />
                  </ToggleButton>
                  {isAdmin && (
                    <ToggleButton value="settings" aria-label="Настройки">
                      <Settings fontSize="small" />
                    </ToggleButton>
                  )}
                </ToggleButtonGroup>
                <ToggleButtonGroup
                  value={themeMode}
                  exclusive
                  size="small"
                  onChange={handleThemeChange}
                  aria-label="Переключение тем"
                  sx={{ mr: 1 }}
                >
                  {THEME_OPTIONS.map((option) => (
                    <ToggleButton key={option.value} value={option.value} aria-label={option.label}>
                      {option.icon}
                    </ToggleButton>
                  ))}
                </ToggleButtonGroup>
                <Tooltip title="Режим отладки">
                  <IconButton color={debugMode ? 'secondary' : 'default'} onClick={() => setDebugMode((prev) => !prev)}>
                    <BugReport />
                  </IconButton>
                </Tooltip>
                <Divider orientation="vertical" flexItem sx={{ mx: 2, display: { xs: 'none', sm: 'block' }, opacity: 0.35 }} />
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip
                    label={isAdmin ? 'Администратор' : 'Оператор'}
                    color={isAdmin ? 'secondary' : 'default'}
                    variant={isAdmin ? 'filled' : 'outlined'}
                  />
                  <Typography variant="body2" sx={{ fontWeight: 500 }}>
                    {auth.username}
                  </Typography>
                  <Button color="inherit" size="small" startIcon={<Logout />} onClick={() => handleLogout()}>
                    Выйти
                  </Button>
                </Stack>
              </Toolbar>
            </AppBar>

            <Container maxWidth="xl" sx={{ pt: { xs: 10, md: 14 }, pb: 8 }}>
        {activePage === 'settings' ? (
          <Stack spacing={4}>
            <Paper
              elevation={0}
              sx={{
                p: { xs: 3, md: 4 },
                borderRadius: 4,
                border: '1px solid',
                borderColor: 'divider'
              }}
            >
              <Stack spacing={3}>
                <Box>
                  <Typography variant="h4" sx={{ fontWeight: 700 }}>
                    Настройки
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    Управление учетными данными оператора
                  </Typography>
                </Box>
                <Divider />
                <Box>
                  <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
                    Обновить учетные данные оператора
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                    Измените логин и пароль для учетной записи оператора. После сохранения оператор должен будет войти с новыми данными.
                  </Typography>
                  <Stack spacing={2} maxWidth={500}>
                    <TextField
                      label="Новый логин"
                      value={credentialsForm.username}
                      onChange={(e) => setCredentialsForm((prev) => ({ ...prev, username: e.target.value }))}
                      fullWidth
                      required
                    />
                    <TextField
                      label="Новый пароль"
                      type="password"
                      value={credentialsForm.password}
                      onChange={(e) => setCredentialsForm((prev) => ({ ...prev, password: e.target.value }))}
                      fullWidth
                      required
                    />
                    <Button
                      variant="contained"
                      startIcon={<Lock />}
                      onClick={handleCredentialsUpdate}
                      disabled={credentialsLoading}
                    >
                      {credentialsLoading ? 'Сохранение...' : 'Сохранить учетные данные'}
                    </Button>
                  </Stack>
                </Box>
              </Stack>
            </Paper>
          </Stack>
        ) : activePage === 'dashboard' ? (
          <Stack spacing={4}>
          <Paper
            elevation={0}
            sx={{
              p: { xs: 3, md: 5 },
              borderRadius: 4,
              border: '1px solid',
              borderColor: 'divider',
              background: (theme) =>
                theme.palette.mode === 'light'
                  ? 'linear-gradient(135deg, rgba(255,255,255,0.92), rgba(233,248,255,0.9))'
                  : 'linear-gradient(135deg, rgba(19,26,37,0.95), rgba(5,9,17,0.9))',
              boxShadow: (theme) =>
                theme.palette.mode === 'light'
                  ? '0 25px 60px rgba(15,23,42,0.15)'
                  : '0 25px 60px rgba(0,0,0,0.6)'
            }}
          >
            <Stack spacing={3}>
              <Box>
                <Typography variant="h3" sx={{ fontWeight: 600 }}>
                  Управление товарами
                </Typography>
                <Typography variant="body1" color="text.secondary" sx={{ mt: 1.5 }}>
                  Единая таблица с товарами. Добавьте товары вручную или загрузите из Excel. Выберите строки и запустите нужный тип поиска.
                </Typography>
              </Box>

              <Paper
                variant="outlined"
                sx={{
                  p: 3,
                  borderRadius: 3,
                  borderColor: 'divider',
                  bgcolor: (theme) => alpha(theme.palette.background.default, 0.4)
                }}
              >
                <Stack spacing={2}>
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>
                    Добавить товар
                  </Typography>
                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="flex-start">
                    <TextField
                      label="Article (артикул)"
                      value={items[0].part_number}
                      onChange={(event) => handleItemChange(0, 'part_number', event.target.value)}
                      fullWidth
                      required
                      placeholder="Введите артикул товара"
                    />
                    <TextField
                      label="Manufacturer/Alias (производитель)"
                      value={items[0].manufacturer_hint ?? ''}
                      onChange={(event) => handleItemChange(0, 'manufacturer_hint', event.target.value)}
                      fullWidth
                      placeholder="Введите производителя (необязательно)"
                    />
                    <Button
                      startIcon={<AddCircleOutline />}
                      variant="contained"
                      onClick={submitManual}
                      sx={{ minWidth: 150, height: 56 }}
                    >
                      Добавить
                    </Button>
                  </Stack>
                  <Typography variant="caption" color="text.secondary">
                    Добавьте товар в таблицу. Поле "Article" обязательно, "Manufacturer/Alias" - необязательно.
                  </Typography>
                </Stack>
              </Paper>

              <Stack direction="row" spacing={2} flexWrap="wrap">
                <Button component="label" startIcon={<Upload />} variant="contained">
                  Загрузить Excel
                  <input hidden type="file" accept=".xls,.xlsx" onChange={handleUpload} />
                </Button>
                <Button startIcon={<FileDownload />} variant="outlined" onClick={() => handleExport('excel')}>
                  Экспорт Excel
                </Button>
                <Button startIcon={<FileDownload />} variant="outlined" onClick={() => handleExport('pdf')}>
                  Экспорт PDF
                </Button>
              </Stack>
              {uploadState.status !== 'idle' && (
                <Stack spacing={1}>
                  {uploadState.status === 'uploading' && <LinearProgress color="secondary" />}
                  <Chip
                    label={uploadState.message ?? 'Обработка файла'}
                    color={
                      uploadState.status === 'done'
                        ? 'success'
                        : uploadState.status === 'uploading'
                        ? 'info'
                        : 'error'
                    }
                    variant="outlined"
                  />
                </Stack>
              )}
            </Stack>
          </Paper>

          {loading && (
            <Paper
              elevation={6}
              sx={{
                p: { xs: 2, md: 3 },
                borderRadius: 3,
                border: '1px solid',
                borderColor: 'divider'
              }}
            >
              <Stack spacing={2}>
                <Box display="flex" alignItems="center" justifyContent="space-between">
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>
                    Прогресс поиска
                  </Typography>
                  <Chip label={`Текущий сервис: ${currentService}`} color="primary" variant="outlined" />
                </Box>
                <LinearProgress color="secondary" />
                <Stack direction="row" spacing={1} flexWrap="wrap">
                  {stageProgress.map((stage) => (
                    <Chip
                      key={stage.name}
                      label={`${stageLabels[stage.name]} · ${progressStateLabel[stage.state]}`}
                      color={progressStateColor[stage.state]}
                      variant={stage.state === 'active' ? 'filled' : 'outlined'}
                      size="small"
                      title={stage.message ?? undefined}
                    />
                  ))}
                </Stack>
              </Stack>
            </Paper>
          )}

          <Paper
            elevation={10}
            sx={{
              p: { xs: 3, md: 4 },
              borderRadius: 4,
              border: '1px solid',
              borderColor: 'divider'
            }}
          >
            <Stack spacing={3}>
              <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={2}>
                <Box>
                  <Typography variant="h4" sx={{ fontWeight: 600 }}>
                    Товары
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Все товары в едином списке. Используйте кнопки справа для запуска поиска по каждой строке.
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                  <ToggleButtonGroup
                    size="small"
                    exclusive
                    value={tableSize}
                    onChange={(_, value) => value && setTableSize(value)}
                    aria-label="Размер таблицы"
                  >
                    <ToggleButton value="small">Компактная</ToggleButton>
                    <ToggleButton value="medium">Нормальная</ToggleButton>
                  </ToggleButtonGroup>
                  <ToggleButtonGroup
                    size="small"
                    exclusive
                    value={fontSize}
                    onChange={(_, value) => value && setFontSize(value)}
                    aria-label="Размер шрифта"
                  >
                    <ToggleButton value="small">Мелкий</ToggleButton>
                    <ToggleButton value="medium">Средний</ToggleButton>
                    <ToggleButton value="large">Крупный</ToggleButton>
                  </ToggleButtonGroup>
                  <ToggleButtonGroup
                    size="small"
                    exclusive
                    value={manufacturerFilter}
                    onChange={(_, value) => value && setManufacturerFilter(value)}
                    aria-label="Фильтр производителей"
                  >
                    <ToggleButton value="all">Все</ToggleButton>
                    <ToggleButton value="found">Найденные</ToggleButton>
                    <ToggleButton value="missing">Не найденные</ToggleButton>
                  </ToggleButtonGroup>
                </Stack>
              </Box>
              {filteredTableData.length === 0 ? (
                <Typography color="text.secondary">Нет данных. Загрузите Excel файл или добавьте товары вручную.</Typography>
              ) : (
                <TableContainer
                  component={Paper}
                  variant="outlined"
                  sx={{
                    maxHeight: 600,
                    borderRadius: 3,
                    overflowX: 'auto',
                    '& .MuiTable-root': {
                      minWidth: { xs: 800, md: 'auto' }
                    },
                    fontSize: tableFontSize
                  }}
                >
                  <Table
                    stickyHeader
                    size={tableSize}
                    sx={{
                      tableLayout: 'fixed',
                      '& .MuiTableCell-root': {
                        fontSize: tableFontSize
                      }
                    }}
                  >
                    <TableHead>
                      <TableRow>
                        <ResizableCell column="article" width={columnWidths.article} onResize={handleColumnResize}>
                          Article
                        </ResizableCell>
                        <ResizableCell column="manufacturer" width={columnWidths.manufacturer} onResize={handleColumnResize}>
                          Manufacturer
                        </ResizableCell>
                        <ResizableCell column="alias" width={columnWidths.alias} onResize={handleColumnResize}>
                          Alias
                        </ResizableCell>
                        <ResizableCell column="submitted" width={columnWidths.submitted} onResize={handleColumnResize}>
                          Submitted
                        </ResizableCell>
                        <ResizableCell column="match" width={columnWidths.match} onResize={handleColumnResize}>
                          Match
                        </ResizableCell>
                        <ResizableCell column="confidence" width={columnWidths.confidence} onResize={handleColumnResize}>
                          Confidence
                        </ResizableCell>
                        <ResizableCell column="source" width={columnWidths.source} onResize={handleColumnResize}>
                          Source
                        </ResizableCell>
                        <ResizableCell column="actions" width={columnWidths.actions} onResize={handleColumnResize}>
                          <Box textAlign="center">Действия</Box>
                        </ResizableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {filteredTableData.map((row) => (
                        <TableRow key={row.key} hover>
                          <TableCell sx={{ width: columnWidths.article, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {row.article}
                          </TableCell>
                          <TableCell sx={{ width: columnWidths.manufacturer, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {row.manufacturer}
                          </TableCell>
                          <TableCell sx={{ width: columnWidths.alias, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {row.alias}
                          </TableCell>
                          <TableCell sx={{ width: columnWidths.submitted, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {row.submitted}
                          </TableCell>
                          <TableCell sx={{ width: columnWidths.match }}>
                            {renderMatchChip(row.matchStatus, row.matchConfidence)}
                          </TableCell>
                          <TableCell sx={{ width: columnWidths.confidence }}>
                            {row.confidence ? `${(row.confidence * 100).toFixed(1)}%` : '—'}
                          </TableCell>
                          <TableCell sx={{ width: columnWidths.source }}>
                            {row.sourceUrl ? (
                              <Tooltip title={row.sourceUrl}>
                                <Box
                                  component="a"
                                  href={row.sourceUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  sx={{
                                    color: 'secondary.main',
                                    textDecoration: 'none',
                                    '&:hover': { textDecoration: 'underline' },
                                    display: 'block',
                                    maxWidth: 200,
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap'
                                  }}
                                >
                                  {row.sourceUrl}
                                </Box>
                              </Tooltip>
                            ) : (
                              '—'
                            )}
                          </TableCell>
                          <TableCell align="center" sx={{ width: columnWidths.actions }}>
                            <Stack direction="row" spacing={0.5} justifyContent="center" flexWrap="wrap" useFlexGap>
                              <Tooltip title="Поиск через Google Search">
                                <IconButton
                                  size="small"
                                  color="secondary"
                                  onClick={() => handleSearchSingleRow(row.id, ['googlesearch'])}
                                  disabled={loading}
                                >
                                  <Search fontSize="small" />
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Поиск через OpenAI">
                                <IconButton
                                  size="small"
                                  color="success"
                                  onClick={() => handleSearchSingleRow(row.id, ['OpenAI'])}
                                  disabled={loading}
                                >
                                  <Psychology fontSize="small" />
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Общий поиск (Internet → Google → OpenAI)">
                                <IconButton
                                  size="small"
                                  color="primary"
                                  onClick={() => handleSearchSingleRow(row.id, null)}
                                  disabled={loading}
                                >
                                  <Search fontSize="small" />
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Удалить строку">
                                <IconButton
                                  size="small"
                                  color="error"
                                  onClick={() => handleDeletePartRow(row.id)}
                                >
                                  <DeleteForever fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            </Stack>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </Stack>
          </Paper>
          </Stack>
        ) : (
          <Stack spacing={4}>
            <Paper
              elevation={0}
              sx={{
                p: { xs: 3, md: 4 },
                borderRadius: 4,
                border: '1px solid',
                borderColor: 'divider'
              }}
            >
              <Stack spacing={3}>
                <Box display="flex" flexWrap="wrap" gap={2} alignItems="center" justifyContent="space-between">
                  <Typography variant="h4" sx={{ fontWeight: 700 }}>
                    Логи поисковых запросов
                  </Typography>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                    <TextField
                      size="small"
                      label="Фильтр по запросу"
                      value={logFilters.q}
                      onChange={(e) => setLogFilters((prev) => ({ ...prev, q: e.target.value }))}
                    />
                    <TextField
                      size="small"
                      label="Провайдер"
                      select
                      SelectProps={{ native: true }}
                      value={logFilters.provider}
                      onChange={(e) => setLogFilters((prev) => ({ ...prev, provider: e.target.value }))}
                    >
                      <option value="">Все</option>
                      <option value="googlesearch">GoogleSearch</option>
                      <option value="google-custom-search">Google CSE</option>
                      <option value="openai">OpenAI</option>
                      <option value="serpapi:google">SerpAPI</option>
                    </TextField>
                    <TextField
                      size="small"
                      label="Тип"
                      select
                      SelectProps={{ native: true }}
                      value={logFilters.direction}
                      onChange={(e) => setLogFilters((prev) => ({ ...prev, direction: e.target.value }))}
                    >
                      <option value="">Все</option>
                      <option value="request">Запрос</option>
                      <option value="response">Ответ</option>
                    </TextField>
                    <Button variant="contained" startIcon={<FilterAlt />} onClick={() => loadLogs()} disabled={logsLoading}>
                      Обновить
                    </Button>
                  </Stack>
                </Box>
                {logsLoading && <LinearProgress />}
                <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 540, borderRadius: 3 }}>
                  <Table stickyHeader size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ fontWeight: 600 }}>Время</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Провайдер</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Тип</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Запрос</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Статус</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Payload</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {logs.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={6}>
                            <Typography color="text.secondary">Логи отсутствуют или не соответствуют фильтрам.</Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        logs.map((entry) => (
                          <TableRow key={entry.id} hover>
                            <TableCell>{new Date(entry.created_at).toLocaleString()}</TableCell>
                            <TableCell>{entry.provider}</TableCell>
                            <TableCell>
                              <Chip
                                size="small"
                                label={entry.direction === 'request' ? 'Запрос' : 'Ответ'}
                                color={entry.direction === 'request' ? 'default' : 'primary'}
                                variant="outlined"
                              />
                            </TableCell>
                            <TableCell sx={{ maxWidth: 320 }}>
                              <Typography variant="body2" noWrap title={entry.query}>
                                {entry.query}
                              </Typography>
                            </TableCell>
                            <TableCell>{entry.status_code ?? '—'}</TableCell>
                            <TableCell sx={{ maxWidth: 320 }}>
                              <Typography variant="body2" noWrap title={entry.payload ?? undefined}>
                                {entry.payload ?? '—'}
                              </Typography>
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Stack>
            </Paper>
          </Stack>
        )}
          </Container>
        </Box>
      </Box>
      <Snackbar
        open={Boolean(snackbar)}
        message={snackbar}
        autoHideDuration={4000}
        onClose={() => setSnackbar(null)}
      />
    </ThemeProvider>
  )
}
