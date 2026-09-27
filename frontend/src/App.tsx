import { Fragment, SyntheticEvent, memo, useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { keyframes } from '@emotion/react'
import {
  AppBar,
  Avatar,
  Box,
  Button,
  Checkbox,
  Chip,
  Collapse,
  Container,
  CssBaseline,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
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
  Settings,
  Fullscreen,
  FullscreenExit,
  KeyboardArrowDown,
  KeyboardArrowUp,
  ContentCopy,
  Api,
  PushPin,
  PushPinOutlined,
  Close,
  Send,
  Telegram
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
  deletePartById,
  downloadExport,
  getSettings,
  updateSettings,
  testTelegram,
  getErrorDetail,
  getErrorStatus
} from './api'
import {
  MatchStatus,
  PartRead,
  PartRequestItem,
  SearchLog,
  SearchResult,
  StageStatus,
  SystemSettings,
  SystemSettingsUpdate
} from './types'
import Draggable from 'react-draggable'

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
const TABLE_SETTINGS_STORAGE_KEY = 'aliasfinder:table-settings'
const SEARCH_CHUNK_SIZE = 5
const LOG_QUERY_DEBOUNCE_MS = 300

// localStorage может быть недоступен (приватный режим, запрет cookies) — не роняем приложение
const safeStorageGet = (key: string): string | null => {
  try {
    if (typeof window === 'undefined') return null
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

const safeStorageSet = (key: string, value: string | null) => {
  try {
    if (typeof window === 'undefined') return
    if (value === null) {
      window.localStorage.removeItem(key)
    } else {
      window.localStorage.setItem(key, value)
    }
  } catch {
    // игнорируем ошибки хранилища (квота, приватный режим)
  }
}

function safeJsonParse<T>(raw: string | null): T | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

// navigator.clipboard недоступен на http-origin, поэтому есть запасной вариант через execCommand
const copyToClipboard = async (text: string): Promise<boolean> => {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // пробуем запасной вариант ниже
  }
  if (typeof document === 'undefined') return false
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  try {
    textarea.focus()
    textarea.select()
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    document.body.removeChild(textarea)
  }
}

type TableSettings = {
  tableSize?: 'small' | 'medium'
  fontSize?: 'small' | 'medium' | 'large'
  rowHeight?: number
  fullscreenMode?: boolean
  fitToScreen?: boolean
  tableContainerSize?: { width: number; height: number }
  columnWidths?: Record<string, number>
}

const loadTableSettings = (): TableSettings => {
  const parsed = safeJsonParse<TableSettings>(safeStorageGet(TABLE_SETTINGS_STORAGE_KEY))
  return parsed && typeof parsed === 'object' ? parsed : {}
}

const loadStoredAuth = (): AuthState | null => {
  const parsed = safeJsonParse<AuthState>(safeStorageGet(AUTH_STORAGE_KEY))
  return parsed && typeof parsed === 'object' && typeof parsed.token === 'string' && parsed.token ? parsed : null
}

const searchItemKey = (item: PartRequestItem) =>
  `${item.part_number.trim()}|${(item.manufacturer_hint ?? '').trim()}`

const keepOnlyIds = (prev: Set<number>, allowed: Set<number>) => {
  const next = new Set(Array.from(prev).filter((id) => allowed.has(id)))
  return next.size === prev.size ? prev : next
}

const withoutIds = (prev: Set<number>, ids: number[]) => {
  if (!ids.some((id) => prev.has(id))) return prev
  const next = new Set(prev)
  ids.forEach((id) => next.delete(id))
  return next
}

type SearchProgress = {
  running: boolean
  total: number
  processed: number
  found: number
  failed: number
  stages: string[] | null
  stageHistory: StageStatus[]
}

const computeStageProgress = (progress: SearchProgress | null): StageProgressEntry[] =>
  STAGE_SEQUENCE.map((name) => {
    if (!progress) return { name, state: 'idle' as StageState }
    const entries = progress.stageHistory.filter((stage) => stage.name === name)
    const counts = entries.reduce<Record<string, number>>((acc, stage) => {
      acc[stage.status] = (acc[stage.status] ?? 0) + 1
      return acc
    }, {})
    const message = entries.length
      ? (Object.keys(counts) as StageStatus['status'][])
          .map((status) => `${stageStatusDescription[status] ?? status}: ${counts[status]}`)
          .join(', ')
      : null
    const requested = !progress.stages || progress.stages.includes(name)
    let state: StageState
    if (counts.success) state = 'done'
    else if (counts['low-confidence']) state = 'warning'
    else if (counts['no-results']) state = 'error'
    else if (entries.length || !requested) state = 'skipped'
    else state = progress.running ? 'pending' : 'skipped'
    return { name, state, message }
  })

type SettingsFormState = {
  telegram_bot_token: string
  telegram_chat_id: string
  telegram_enabled: boolean
  notify_on_errors: boolean
  notify_on_low_balance: boolean
  openai_balance_threshold: string
  google_balance_threshold: string
}

const emptySettingsForm: SettingsFormState = {
  telegram_bot_token: '',
  telegram_chat_id: '',
  telegram_enabled: false,
  notify_on_errors: true,
  notify_on_low_balance: true,
  openai_balance_threshold: '',
  google_balance_threshold: ''
}

const settingsToForm = (settings: SystemSettings): SettingsFormState => ({
  telegram_bot_token: settings.telegram_bot_token ?? '',
  telegram_chat_id: settings.telegram_chat_id ?? '',
  telegram_enabled: Boolean(settings.telegram_enabled),
  notify_on_errors: Boolean(settings.notify_on_errors),
  notify_on_low_balance: Boolean(settings.notify_on_low_balance),
  openai_balance_threshold:
    settings.openai_balance_threshold === null || settings.openai_balance_threshold === undefined
      ? ''
      : String(settings.openai_balance_threshold),
  google_balance_threshold:
    settings.google_balance_threshold === null || settings.google_balance_threshold === undefined
      ? ''
      : String(settings.google_balance_threshold)
})

// Возвращает null для пустого значения и undefined для некорректного
const parseThreshold = (value: string): number | null | undefined => {
  const trimmed = value.trim().replace(',', '.')
  if (!trimmed) return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined
}

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

const snowfall = keyframes`
  0% { transform: translateY(-10vh) translateX(0) rotate(0deg); opacity: 0; }
  10% { opacity: 1; }
  90% { opacity: 1; }
  100% { transform: translateY(110vh) translateX(100px) rotate(360deg); opacity: 0; }
`

const treeGlow = keyframes`
  0%, 100% { filter: drop-shadow(0 0 8px rgba(255,215,0,0.6)); }
  50% { filter: drop-shadow(0 0 20px rgba(255,215,0,0.9)); }
`

const bounce = keyframes`
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
`

const float = keyframes`
  0%, 100% { transform: translateY(0px); }
  50% { transform: translateY(-15px); }
`

const ResizableCell = ({
  column,
  width,
  onResize,
  onResizeEnd,
  children
}: {
  column: string
  width: number
  onResize: (column: string, width: number) => void
  onResizeEnd?: () => void
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
      onResizeEnd?.()
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing, startX, startWidth, column, onResize, onResizeEnd])

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

const useRowHeightResizer = ({
  onResize,
  onResizeEnd
}: {
  onResize: (height: number) => void
  onResizeEnd?: () => void
}) => {
  const [isResizing, setIsResizing] = useState(false)
  const [startY, setStartY] = useState(0)
  const [startHeight, setStartHeight] = useState(0)

  const handleMouseDown = (e: React.MouseEvent, currentHeight: number) => {
    setIsResizing(true)
    setStartY(e.clientY)
    setStartHeight(currentHeight)
    e.preventDefault()
    e.stopPropagation()
  }

  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      const diff = e.clientY - startY
      const newHeight = Math.max(30, startHeight + diff)
      onResize(newHeight)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      onResizeEnd?.()
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing, startY, startHeight, onResize, onResizeEnd])

  return {
    isResizing,
    handleMouseDown
  }
}

const Santa = () => {
  return (
    <>
      {/* Большой Санта справа внизу */}
      <Box
        sx={{
          position: 'absolute',
          bottom: 40,
          right: 40,
          fontSize: '140px',
          zIndex: 5,
          animation: `${drift} 5s ease-in-out infinite`,
          filter: 'drop-shadow(0 10px 20px rgba(0,0,0,0.4))',
          transform: 'rotate(-8deg)'
        }}
      >
        🎅
      </Box>
      {/* Маленькие Санты по экрану */}
      <Box
        sx={{
          position: 'absolute',
          top: '15%',
          left: '10%',
          fontSize: '60px',
          zIndex: 5,
          animation: `${twinkle} 3s ease-in-out infinite`,
        }}
      >
        🎅
      </Box>
      <Box
        sx={{
          position: 'absolute',
          top: '25%',
          right: '15%',
          fontSize: '50px',
          zIndex: 5,
          animation: `${drift} 4s ease-in-out infinite`,
          animationDelay: '1s'
        }}
      >
        🤶
      </Box>
      {/* Эльфы */}
      <Box
        sx={{
          position: 'absolute',
          bottom: '20%',
          left: '20%',
          fontSize: '45px',
          zIndex: 5,
          animation: `${bounce} 2s ease-in-out infinite`,
        }}
      >
        🧝
      </Box>
      <Box
        sx={{
          position: 'absolute',
          bottom: '15%',
          left: '30%',
          fontSize: '40px',
          zIndex: 5,
          animation: `${bounce} 2.5s ease-in-out infinite`,
          animationDelay: '0.5s'
        }}
      >
        🧝‍♀️
      </Box>
    </>
  )
}

const HOLIDAY_PALETTE = ['#ff0000', '#00ff00', '#ffeb3b', '#ff6b6b', '#ffd166', '#6dd3c2', '#74c0fc', '#c8b6ff', '#ff6b9a', '#00d4aa']

// memo + случайные значения генерируются один раз, чтобы снег и звёзды не "прыгали" при каждом рендере
const HolidayLights = memo(function HolidayLights() {
  const palette = HOLIDAY_PALETTE
  const [stars] = useState(() =>
    Array.from({ length: 30 }).map(() => ({
      top: Math.random() * 40,
      left: Math.random() * 100,
      duration: 2 + Math.random() * 3,
      delay: Math.random() * 3
    }))
  )
  const [snowflakes] = useState(() =>
    Array.from({ length: 80 }).map(() => ({
      left: Math.random() * 100,
      size: Math.random() * 12 + 12,
      duration: Math.random() * 10 + 12,
      delay: Math.random() * 10
    }))
  )
  const [treeLightDurations] = useState(() => Array.from({ length: 12 }).map(() => 1.5 + Math.random()))
  return (
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        overflow: 'visible',
        pointerEvents: 'none',
        zIndex: 0,
        background: `
          radial-gradient(ellipse at 20% 0%, rgba(100, 200, 255, 0.4), transparent 40%),
          radial-gradient(ellipse at 80% 0%, rgba(200, 150, 255, 0.35), transparent 35%),
          radial-gradient(ellipse at 50% 0%, rgba(150, 220, 255, 0.3), transparent 50%),
          linear-gradient(180deg,
            #0f1f3f 0%,
            #1a2a4a 10%,
            #2d4a7c 20%,
            #4a7ba7 35%,
            #87b3d4 55%,
            #b8d8f0 75%,
            #e5f2fa 88%,
            #ffffff 100%
          )
        `
      }}
    >
      {/* Снежные холмы на заднем плане */}
      <Box
        sx={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          height: '40%',
          background: `
            radial-gradient(ellipse 800px 300px at 20% 100%, rgba(255, 255, 255, 0.9), transparent),
            radial-gradient(ellipse 600px 250px at 60% 100%, rgba(240, 248, 255, 0.85), transparent),
            radial-gradient(ellipse 700px 280px at 90% 100%, rgba(255, 255, 255, 0.9), transparent),
            linear-gradient(to top, rgba(255, 255, 255, 0.95) 0%, transparent 100%)
          `,
          zIndex: 0
        }}
      />

      {/* Звезды на небе */}
      {stars.map((star, i) => (
        <Box
          key={`star-${i}`}
          sx={{
            position: 'absolute',
            top: `${star.top}%`,
            left: `${star.left}%`,
            width: '2px',
            height: '2px',
            borderRadius: '50%',
            background: 'white',
            boxShadow: '0 0 4px 1px rgba(255,255,255,0.8)',
            animation: `${twinkle} ${star.duration}s ease-in-out infinite`,
            animationDelay: `${star.delay}s`,
            zIndex: 1
          }}
        />
      ))}
      {/* Падающий снег */}
      {snowflakes.map((flake, i) => (
        <Box
          key={`snow-${i}`}
          sx={{
            position: 'absolute',
            top: '-10vh',
            left: `${flake.left}%`,
            fontSize: `${flake.size}px`,
            animation: `${snowfall} ${flake.duration}s linear infinite`,
            animationDelay: `${flake.delay}s`,
            opacity: 0.9,
            filter: 'drop-shadow(0 0 3px rgba(255,255,255,0.8))'
          }}
        >
          ❄
        </Box>
      ))}

      {/* Верхняя гирлянда */}
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
        {Array.from({ length: 50 }).map((_, index) => (
          <Box
            key={`top-${index}`}
            sx={{
              width: 16,
              height: 16,
              borderRadius: '50%',
              background: palette[index % palette.length],
              boxShadow: `0 0 20px 3px ${palette[index % palette.length]}`,
              animation: `${twinkle} 2.2s ease-in-out infinite`,
              animationDelay: `${index * 50}ms`
            }}
          />
        ))}
      </Box>

      {/* Нижняя гирлянда */}
      <Box
        sx={{
          position: 'absolute',
          bottom: 12,
          left: 0,
          right: 0,
          display: 'flex',
          justifyContent: 'space-evenly',
          px: 4,
          zIndex: 1,
          animation: `${garlandSwing} 7s ease-in-out infinite`
        }}
      >
        {Array.from({ length: 50 }).map((_, index) => (
          <Box
            key={`bottom-${index}`}
            sx={{
              width: 16,
              height: 16,
              borderRadius: '50%',
              background: palette[(index + 3) % palette.length],
              boxShadow: `0 0 20px 3px ${palette[(index + 3) % palette.length]}`,
              animation: `${twinkle} 2.4s ease-in-out infinite`,
              animationDelay: `${index * 60}ms`
            }}
          />
        ))}
      </Box>

      {/* Ёлка в левом углу */}
      <Box
        sx={{
          position: 'absolute',
          left: 40,
          bottom: 20,
          fontSize: '180px',
          animation: `${treeGlow} 3s ease-in-out infinite`,
          zIndex: 2
        }}
      >
        🎄
        {/* Гирлянды на ёлке */}
        {treeLightDurations.map((duration, i) => (
          <Box
            key={`tree-light-${i}`}
            sx={{
              position: 'absolute',
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: palette[i % palette.length],
              boxShadow: `0 0 12px ${palette[i % palette.length]}`,
              top: `${20 + i * 12}%`,
              left: `${30 + (i % 2 ? 15 : -15)}%`,
              animation: `${twinkle} ${duration}s ease-in-out infinite`,
              animationDelay: `${i * 100}ms`
            }}
          />
        ))}
      </Box>

      {/* Подарки под ёлкой */}
      <Box sx={{ position: 'absolute', left: 50, bottom: 10, fontSize: '32px', zIndex: 1 }}>
        🎁
      </Box>
      <Box sx={{ position: 'absolute', left: 120, bottom: 15, fontSize: '28px', zIndex: 1 }}>
        🎁
      </Box>
      <Box sx={{ position: 'absolute', left: 90, bottom: 5, fontSize: '24px', zIndex: 1 }}>
        🎁
      </Box>

      {/* Олени */}
      <Box
        sx={{
          position: 'absolute',
          right: 100,
          top: '30%',
          fontSize: '64px',
          animation: `${float} 4s ease-in-out infinite`,
          zIndex: 2
        }}
      >
        🦌
      </Box>
      <Box
        sx={{
          position: 'absolute',
          right: 180,
          top: '35%',
          fontSize: '56px',
          animation: `${float} 5s ease-in-out infinite`,
          animationDelay: '1s',
          zIndex: 2
        }}
      >
        🦌
      </Box>

      {/* Гномы */}
      <Box
        sx={{
          position: 'absolute',
          left: '40%',
          bottom: 30,
          fontSize: '48px',
          animation: `${bounce} 3s ease-in-out infinite`,
          zIndex: 2
        }}
      >
        🧙‍♂️
      </Box>
      <Box
        sx={{
          position: 'absolute',
          right: '35%',
          bottom: 25,
          fontSize: '52px',
          animation: `${bounce} 3.5s ease-in-out infinite`,
          animationDelay: '0.5s',
          zIndex: 2
        }}
      >
        🎅
      </Box>

      {/* Дополнительные украшения */}
      <Box sx={{ position: 'absolute', left: '20%', top: '20%', fontSize: '42px', animation: `${float} 6s ease-in-out infinite` }}>
        ⭐
      </Box>
      <Box sx={{ position: 'absolute', right: '15%', top: '15%', fontSize: '38px', animation: `${float} 5.5s ease-in-out infinite`, animationDelay: '1s' }}>
        ⭐
      </Box>

      {/* Фоновые эффекты */}
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

      {/* Санта Клаус и его команда */}
      <Santa />

      {/* Больше праздничных элементов */}
      <Box sx={{ position: 'absolute', top: '10%', left: '5%', fontSize: '50px', animation: `${twinkle} 3s ease-in-out infinite` }}>🎁</Box>
      <Box sx={{ position: 'absolute', top: '40%', right: '8%', fontSize: '45px', animation: `${float} 4.5s ease-in-out infinite` }}>🎁</Box>
      <Box sx={{ position: 'absolute', bottom: '30%', left: '50%', fontSize: '38px', animation: `${bounce} 3s ease-in-out infinite` }}>🔔</Box>
      <Box sx={{ position: 'absolute', top: '30%', left: '70%', fontSize: '42px', animation: `${drift} 5s ease-in-out infinite` }}>🕯️</Box>
      <Box sx={{ position: 'absolute', top: '50%', left: '15%', fontSize: '40px', animation: `${twinkle} 4s ease-in-out infinite`, animationDelay: '1s' }}>🎄</Box>
      <Box sx={{ position: 'absolute', bottom: '40%', right: '25%', fontSize: '48px', animation: `${float} 6s ease-in-out infinite`, animationDelay: '0.5s' }}>☃️</Box>
    </Box>
  )
})

export function App() {
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    const stored = safeStorageGet(THEME_STORAGE_KEY)
    return stored === 'dark' || stored === 'holiday' ? (stored as ThemeMode) : 'light'
  })
  const [auth, setAuth] = useState<AuthState | null>(loadStoredAuth)
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
  const [debouncedLogQuery, setDebouncedLogQuery] = useState('')
  const logsRequestIdRef = useRef(0)
  const [expandedLogIds, setExpandedLogIds] = useState<Set<number>>(new Set())
  const [expandedTableRows, setExpandedTableRows] = useState<Set<number>>(new Set())
  const [autoRefreshLogs, setAutoRefreshLogs] = useState(false)
  const [refreshInterval, setRefreshInterval] = useState(5000) // 5 seconds default
  const [apiConfigOpen, setApiConfigOpen] = useState(false)
  const [apiConfig, setApiConfig] = useState(() => ({
    apiUrl: safeStorageGet('api_url') || '',
    apiKey: safeStorageGet('api_key') || '',
    apiToken: safeStorageGet('api_token') || '',
    swaggerUrl: safeStorageGet('swagger_url') || '',
    customHeaders: safeStorageGet('custom_headers') || ''
  }))
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
      confidence: record.confidence ?? null,
      whatProduces: record.what_produces ?? '—',
      website: record.website ?? '—',
      manufacturerAliases: record.manufacturer_aliases ?? '—',
      country: record.country ?? '—',
      debugLog: record.debug_log ?? null,
      stageHistory: record.stage_history ?? null,
      searchStage: record.search_stage ?? null
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
  const visibleIds = useMemo(() => new Set(filteredTableData.map((row) => row.id)), [filteredTableData])
  // Массовые действия работают только со строками, видимыми при текущем фильтре
  const selectedVisibleIds = useMemo(
    () => Array.from(selectedIds).filter((id) => visibleIds.has(id)),
    [selectedIds, visibleIds]
  )
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
  const [searchProgress, setSearchProgress] = useState<SearchProgress | null>(null)
  const searchRunIdRef = useRef(0)
  const stageProgress = useMemo(() => computeStageProgress(searchProgress), [searchProgress])
  const [uploadState, setUploadState] = useState<{ status: 'idle' | 'uploading' | 'done' | 'error'; message?: string }>(
    { status: 'idle' }
  )
  const [systemSettings, setSystemSettings] = useState<SystemSettings | null>(null)
  const [settingsForm, setSettingsForm] = useState<SettingsFormState>(emptySettingsForm)
  const [settingsLoading, setSettingsLoading] = useState(false)
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [telegramTesting, setTelegramTesting] = useState(false)

  // Load table settings from localStorage (один раз)
  const [savedSettings] = useState(loadTableSettings)

  const [tableSize, setTableSize] = useState<'small' | 'medium'>(() => savedSettings.tableSize || 'small')
  const [fontSize, setFontSize] = useState<'small' | 'medium' | 'large'>(() => savedSettings.fontSize || 'medium')
  const [rowHeight, setRowHeight] = useState<number>(() => savedSettings.rowHeight || 53)
  // Полноэкранный режим нельзя восстановить без действия пользователя, поэтому стартуем без него
  const [fullscreenMode, setFullscreenMode] = useState<boolean>(false)
  const productsSectionRef = useRef<HTMLDivElement | null>(null)
  const [fitToScreen, setFitToScreen] = useState<boolean>(() => savedSettings.fitToScreen ?? true)

  useEffect(() => {
    const handleFullscreenChange = () =>
      setFullscreenMode(Boolean(document.fullscreenElement && document.fullscreenElement === productsSectionRef.current))
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen()
      } else if (productsSectionRef.current?.requestFullscreen) {
        await productsSectionRef.current.requestFullscreen()
      } else {
        setSnackbar('Полноэкранный режим не поддерживается браузером')
      }
    } catch {
      setSnackbar('Не удалось переключить полноэкранный режим')
    }
  }
  const [tableContainerSize] = useState<{ width: number; height: number }>(
    () =>
      savedSettings.tableContainerSize || {
        width: typeof window === 'undefined' ? 1400 : Math.min(window.innerWidth - 80, 1400),
        height: typeof window === 'undefined' ? 700 : Math.min(window.innerHeight - 200, 700)
      }
  )
  // Увеличивается по отпусканию мыши после изменения размеров — тогда и сохраняем в localStorage
  const [resizeCommitVersion, setResizeCommitVersion] = useState(0)
  const [tableDraggable, setTableDraggable] = useState(false)
  const [tablePosition, setTablePosition] = useState({ x: 0, y: 0 })
  const [tablePinned, setTablePinned] = useState(false)
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(() => savedSettings.columnWidths || {
    checkbox: 50,
    article: 120,
    manufacturer: 150,
    alias: 120,
    submitted: 120,
    match: 120,
    confidence: 100,
    source: 200,
    whatProduces: 180,
    website: 180,
    manufacturerAliases: 180,
    country: 120,
    actions: 180
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
  const handleThemeChange = (_: SyntheticEvent, value: ThemeMode | null) => {
    if (value) setThemeMode(value)
  }
  const refreshHistory = async () => {
    try {
      const data = await listParts()
      setHistory(data)
      // Убираем из выделения и раскрытых строк записи, которых больше нет
      const existingIds = new Set(data.map((part) => part.id))
      setSelectedIds((prev) => keepOnlyIds(prev, existingIds))
      setExpandedTableRows((prev) => keepOnlyIds(prev, existingIds))
    } catch (error) {
      setSnackbar('Не удалось получить историю поиска')
    }
  }

  const loadLogs = async (filters: typeof logFilters) => {
    // Ответы на устаревшие запросы игнорируются
    const requestId = ++logsRequestIdRef.current
    setLogsLoading(true)
    try {
      const data = await fetchLogs({ ...filters, limit: 200 })
      if (requestId === logsRequestIdRef.current) {
        setLogs(data)
      }
    } catch (error) {
      if (requestId === logsRequestIdRef.current) {
        setSnackbar('Не удалось загрузить логи')
      }
    } finally {
      if (requestId === logsRequestIdRef.current) {
        setLogsLoading(false)
      }
    }
  }

  const toggleLogExpansion = (logId: number) => {
    setExpandedLogIds((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(logId)) {
        newSet.delete(logId)
      } else {
        newSet.add(logId)
      }
      return newSet
    })
  }

  const handleCopy = async (text: string, successMessage = 'Скопировано в буфер обмена') => {
    const copied = await copyToClipboard(text)
    setSnackbar(copied ? successMessage : 'Не удалось скопировать')
  }

  const formatJSON = (jsonString: string | null | undefined): string => {
    if (!jsonString) return ''
    try {
      const parsed = JSON.parse(jsonString)
      return JSON.stringify(parsed, null, 2)
    } catch {
      return jsonString
    }
  }

  const handleSaveApiConfig = () => {
    localStorage.setItem('api_url', apiConfig.apiUrl)
    localStorage.setItem('api_key', apiConfig.apiKey)
    localStorage.setItem('api_token', apiConfig.apiToken)
    localStorage.setItem('swagger_url', apiConfig.swaggerUrl)
    localStorage.setItem('custom_headers', apiConfig.customHeaders)
    setApiConfigOpen(false)
    setSnackbar('API настройки сохранены')
  }

  const handleApiConfigChange = (field: keyof typeof apiConfig, value: string) => {
    setApiConfig((prev) => ({ ...prev, [field]: value }))
  }

  const handleDeletePartRow = async (id: number) => {
    try {
      await deletePartById(id)
      setSelectedIds((prev) => withoutIds(prev, [id]))
      setExpandedTableRows((prev) => withoutIds(prev, [id]))
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

  const handleLogout = (message?: string) => {
    // Прерываем идущий пакетный поиск
    searchRunIdRef.current += 1
    setAuth(null)
    setResults([])
    setHistory([])
    setItems([{ ...emptyItem }])
    setSelectedIds(new Set())
    setExpandedTableRows(new Set())
    setUploadState({ status: 'idle' })
    setSearchProgress(null)
    setLoading(false)
    logsRequestIdRef.current += 1
    setLogs([])
    setLogsLoading(false)
    setExpandedLogIds(new Set())
    setSystemSettings(null)
    setSettingsForm(emptySettingsForm)
    setActivePage('dashboard')
    setCredentialsForm({ username: '', password: '' })
    if (message) {
      setSnackbar(message)
    }
  }

  useEffect(() => {
    setUnauthorizedHandler(() => handleLogout('Сессия истекла. Авторизуйтесь снова.'))
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    safeStorageSet(AUTH_STORAGE_KEY, auth ? JSON.stringify(auth) : null)
  }, [auth])

  useEffect(() => {
    safeStorageSet(THEME_STORAGE_KEY, themeMode)
  }, [themeMode])

  useEffect(() => {
    const settings: TableSettings = {
      tableSize,
      fontSize,
      rowHeight,
      fullscreenMode,
      fitToScreen,
      tableContainerSize,
      columnWidths
    }
    safeStorageSet(TABLE_SETTINGS_STORAGE_KEY, JSON.stringify(settings))
    // rowHeight и columnWidths меняются на каждом mousemove — сохраняем их только по mouseup (resizeCommitVersion)
  }, [tableSize, fontSize, fullscreenMode, fitToScreen, tableContainerSize, resizeCommitVersion])

  useEffect(() => {
    if (!auth) {
      setAuthToken(null)
      return
    }
    setAuthToken(auth.token)
    let cancelled = false
    const verify = async () => {
      try {
        await fetchProfile()
      } catch (error) {
        // При 401 выход уже выполнен перехватчиком axios — не дублируем
        if (!cancelled && getErrorStatus(error) !== 401) {
          handleLogout('Сессия истекла. Авторизуйтесь снова.')
        }
        return
      }
      if (!cancelled) {
        await refreshHistory()
      }
    }
    verify()
    return () => {
      cancelled = true
    }
  }, [auth])

  // Debounce текстового фильтра логов, чтобы не слать запрос на каждое нажатие клавиши
  useEffect(() => {
    const timeoutId = window.setTimeout(() => setDebouncedLogQuery(logFilters.q), LOG_QUERY_DEBOUNCE_MS)
    return () => window.clearTimeout(timeoutId)
  }, [logFilters.q])

  const effectiveLogFilters = useMemo(
    () => ({ provider: logFilters.provider, direction: logFilters.direction, q: debouncedLogQuery }),
    [logFilters.provider, logFilters.direction, debouncedLogQuery]
  )

  useEffect(() => {
    if (activePage !== 'logs' || !auth) return
    loadLogs(effectiveLogFilters)
  }, [activePage, auth, effectiveLogFilters])

  // Auto-refresh logs (с актуальными фильтрами)
  useEffect(() => {
    if (!autoRefreshLogs || activePage !== 'logs' || !auth) return

    const intervalId = window.setInterval(() => {
      loadLogs(effectiveLogFilters)
    }, refreshInterval)

    return () => window.clearInterval(intervalId)
  }, [autoRefreshLogs, activePage, auth, refreshInterval, effectiveLogFilters])

  // Загружаем настройки уведомлений, когда администратор открывает страницу настроек
  useEffect(() => {
    if (activePage !== 'settings' || !isAdmin) return
    let cancelled = false
    const load = async () => {
      setSettingsLoading(true)
      try {
        const data = await getSettings()
        if (cancelled) return
        setSystemSettings(data)
        setSettingsForm(settingsToForm(data))
      } catch (error) {
        if (!cancelled) {
          setSnackbar(getErrorDetail(error) ?? 'Не удалось загрузить настройки уведомлений')
        }
      } finally {
        if (!cancelled) {
          setSettingsLoading(false)
        }
      }
    }
    load()
    return () => {
      cancelled = true
      setSettingsLoading(false)
    }
  }, [activePage, isAdmin])

  const settingsDirty = useMemo(() => {
    if (!systemSettings) return false
    const original = settingsToForm(systemSettings)
    return (Object.keys(original) as (keyof SettingsFormState)[]).some((key) => original[key] !== settingsForm[key])
  }, [systemSettings, settingsForm])

  const handleSettingsFieldChange = <K extends keyof SettingsFormState>(field: K, value: SettingsFormState[K]) => {
    setSettingsForm((prev) => ({ ...prev, [field]: value }))
  }

  const handleSaveSystemSettings = async () => {
    const openaiThreshold = parseThreshold(settingsForm.openai_balance_threshold)
    const googleThreshold = parseThreshold(settingsForm.google_balance_threshold)
    if (openaiThreshold === undefined || googleThreshold === undefined) {
      setSnackbar('Пороги баланса должны быть неотрицательными числами')
      return
    }
    const next: SystemSettingsUpdate = {
      telegram_bot_token: settingsForm.telegram_bot_token.trim() || null,
      telegram_chat_id: settingsForm.telegram_chat_id.trim() || null,
      telegram_enabled: settingsForm.telegram_enabled,
      notify_on_errors: settingsForm.notify_on_errors,
      notify_on_low_balance: settingsForm.notify_on_low_balance,
      openai_balance_threshold: openaiThreshold,
      google_balance_threshold: googleThreshold
    }
    // PUT /settings — частичное обновление, отправляем только изменённые поля
    const payload = Object.fromEntries(
      Object.entries(next).filter(([key, value]) => {
        if (!systemSettings) return true
        return (systemSettings[key as keyof SystemSettingsUpdate] ?? null) !== value
      })
    ) as SystemSettingsUpdate
    if (!Object.keys(payload).length) {
      setSnackbar('Нет изменений для сохранения')
      return
    }
    setSettingsSaving(true)
    try {
      const updated = await updateSettings(payload)
      setSystemSettings(updated)
      setSettingsForm(settingsToForm(updated))
      setSnackbar('Настройки уведомлений сохранены')
    } catch (error) {
      setSnackbar(getErrorDetail(error) ?? 'Не удалось сохранить настройки')
    } finally {
      setSettingsSaving(false)
    }
  }

  const handleTestTelegram = async () => {
    setTelegramTesting(true)
    try {
      const response = await testTelegram()
      setSnackbar(response.message || 'Тестовое сообщение отправлено')
    } catch (error) {
      const detail = getErrorDetail(error)
      setSnackbar(detail ? `Ошибка Telegram: ${detail}` : 'Не удалось отправить тестовое сообщение')
    } finally {
      setTelegramTesting(false)
    }
  }

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

  const performSearch = async (
    targets: PartRequestItem[],
    stages?: string[] | null
  ): Promise<{ failedKeys: Set<string> } | null> => {
    // Убираем пустые строки и дубликаты (артикул + производитель)
    const seen = new Set<string>()
    const filled = targets.filter((item) => {
      if (!item.part_number.trim()) return false
      const key = searchItemKey(item)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    if (!filled.length) {
      setSnackbar('Добавьте хотя бы один артикул для поиска')
      return null
    }
    // Новый поиск или выход из системы прерывают текущий цикл
    const runId = ++searchRunIdRef.current
    const isCurrentRun = () => searchRunIdRef.current === runId
    const total = filled.length
    const failedKeys = new Set<string>()
    const collected: SearchResult[] = []
    let found = 0
    setLoading(true)
    setResults([])
    setSearchProgress({
      running: true,
      total,
      processed: 0,
      found: 0,
      failed: 0,
      stages: stages ?? null,
      stageHistory: []
    })
    // Отправляем пачками: таблица заполняется постепенно, а ошибка одной пачки не прерывает весь поиск
    for (let offset = 0; offset < total; offset += SEARCH_CHUNK_SIZE) {
      const chunk = filled.slice(offset, offset + SEARCH_CHUNK_SIZE)
      let chunkResults: SearchResult[] = []
      let chunkFailed = false
      try {
        const response = await searchParts(chunk, debugMode, stages)
        chunkResults = response.results ?? []
      } catch (error) {
        chunkFailed = true
        chunk.forEach((item) => failedKeys.add(searchItemKey(item)))
      }
      if (!isCurrentRun()) return null
      const chunkFound = chunkResults.filter((result) => Boolean(result.manufacturer_name)).length
      const failedCount = failedKeys.size
      found += chunkFound
      collected.push(...chunkResults)
      setResults([...collected])
      setSearchProgress((prev) =>
        prev && {
          ...prev,
          processed: Math.min(prev.total, prev.processed + chunk.length),
          found: prev.found + chunkFound,
          failed: failedCount,
          stageHistory: [...prev.stageHistory, ...chunkResults.flatMap((result) => result.stage_history ?? [])]
        }
      )
      if (!chunkFailed) {
        await refreshHistory()
        if (!isCurrentRun()) return null
      }
    }
    setLoading(false)
    setSearchProgress((prev) => prev && { ...prev, running: false })
    setSnackbar(`Поиск завершён. Найдено ${found} из ${total}, ошибок: ${failedKeys.size}`)
    return { failedKeys }
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
      setUploadState({ status: 'done', message: `${statusMessage}. Данные добавлены в таблицу` })
      setSnackbar(`${statusMessage}. ${baseMessage}${errorMessage}`)
      await refreshHistory()
    } catch (error) {
      setUploadState({ status: 'error', message: 'Не удалось загрузить файл' })
      setSnackbar('Не удалось загрузить файл')
    } finally {
      input.value = ''
    }
  }

  // Выбор/снятие всех строк, видимых при текущем фильтре
  const handleSelectAll = (checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      visibleIds.forEach((id) => {
        if (checked) {
          next.add(id)
        } else {
          next.delete(id)
        }
      })
      return next
    })
  }

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

  const handleBatchSearch = async (stages?: string[] | null) => {
    if (!selectedVisibleIds.length) {
      setSnackbar('Выберите хотя бы одну строку для поиска')
      return
    }
    const targetIds = new Set(selectedVisibleIds)
    const targetParts = history.filter((part) => targetIds.has(part.id))
    const toItem = (part: PartRead): PartRequestItem => ({
      part_number: part.part_number,
      manufacturer_hint: part.submitted_manufacturer ?? null
    })
    const outcome = await performSearch(targetParts.map(toItem), stages)
    if (!outcome) return
    // Строки с ошибкой остаются выбранными, успешно обработанные — снимаем
    const processedIds = targetParts
      .filter((part) => !outcome.failedKeys.has(searchItemKey(toItem(part))))
      .map((part) => part.id)
    setSelectedIds((prev) => withoutIds(prev, processedIds))
  }

  const handleBatchDelete = async () => {
    const targetIds = selectedVisibleIds
    if (!targetIds.length) {
      setSnackbar('Выберите хотя бы одну строку для удаления')
      return
    }
    if (!window.confirm(`Удалить ${targetIds.length} строк(и)?`)) {
      return
    }
    const outcomes = await Promise.allSettled(targetIds.map((id) => deletePartById(id)))
    const deletedIds = targetIds.filter((_, index) => outcomes[index].status === 'fulfilled')
    const failedCount = targetIds.length - deletedIds.length
    // Неудалённые строки остаются выбранными
    setSelectedIds((prev) => withoutIds(prev, deletedIds))
    setExpandedTableRows((prev) => withoutIds(prev, deletedIds))
    await refreshHistory()
    setSnackbar(
      failedCount
        ? `Удалено строк: ${deletedIds.length}, не удалось удалить: ${failedCount}`
        : `Удалено строк: ${deletedIds.length}`
    )
  }

  const handleColumnResize = useCallback((column: string, width: number) => {
    setColumnWidths(prev => ({
      ...prev,
      [column]: Math.max(80, width)
    }))
  }, [])

  const handleRowHeightResize = useCallback((height: number) => {
    setRowHeight(height)
  }, [])

  const handleResizeEnd = useCallback(() => setResizeCommitVersion((version) => version + 1), [])

  const rowResizer = useRowHeightResizer({ onResize: handleRowHeightResize, onResizeEnd: handleResizeEnd })

  const handleExport = async (type: 'pdf' | 'excel') => {
    try {
      const response = type === 'pdf' ? await exportPdf() : await exportExcel()
      await downloadExport(response.url)
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
                <Tooltip title="API настройки">
                  <IconButton color="default" onClick={() => setApiConfigOpen(true)}>
                    <Api />
                  </IconButton>
                </Tooltip>
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

            <Container
              maxWidth="xl"
              sx={{
                pt: { xs: 10, md: 14 },
                pb: 8
              }}
            >
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
                <Divider />
                <Box>
                  <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
                    API Интеграция
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                    Настройте подключение к внешним API (Swagger и другим проектам)
                  </Typography>
                  <Button
                    variant="outlined"
                    startIcon={<Api />}
                    onClick={() => setApiConfigOpen(true)}
                    size="large"
                  >
                    Настроить API подключение
                  </Button>
                </Box>
              </Stack>
            </Paper>
            {isAdmin && (
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
                  <Box display="flex" alignItems="center" gap={1.5}>
                    <Telegram color="primary" />
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 600 }}>
                        Уведомления Telegram
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Оповещения об ошибках поиска и низком балансе OpenAI / Google
                      </Typography>
                    </Box>
                  </Box>
                  {settingsLoading && <LinearProgress />}
                  <Stack spacing={2} maxWidth={500}>
                    <TextField
                      label="Токен бота"
                      type="password"
                      autoComplete="new-password"
                      value={settingsForm.telegram_bot_token}
                      onChange={(e) => handleSettingsFieldChange('telegram_bot_token', e.target.value)}
                      disabled={settingsLoading}
                      fullWidth
                    />
                    <TextField
                      label="Chat ID"
                      value={settingsForm.telegram_chat_id}
                      onChange={(e) => handleSettingsFieldChange('telegram_chat_id', e.target.value)}
                      disabled={settingsLoading}
                      helperText="ID чата или канала, куда бот будет отправлять сообщения"
                      fullWidth
                    />
                    <FormControlLabel
                      control={
                        <Switch
                          checked={settingsForm.telegram_enabled}
                          onChange={(e) => handleSettingsFieldChange('telegram_enabled', e.target.checked)}
                          disabled={settingsLoading}
                        />
                      }
                      label="Отправлять уведомления в Telegram"
                    />
                    <FormControlLabel
                      control={
                        <Switch
                          checked={settingsForm.notify_on_errors}
                          onChange={(e) => handleSettingsFieldChange('notify_on_errors', e.target.checked)}
                          disabled={settingsLoading}
                        />
                      }
                      label="Уведомлять об ошибках"
                    />
                    <FormControlLabel
                      control={
                        <Switch
                          checked={settingsForm.notify_on_low_balance}
                          onChange={(e) => handleSettingsFieldChange('notify_on_low_balance', e.target.checked)}
                          disabled={settingsLoading}
                        />
                      }
                      label="Уведомлять о низком балансе"
                    />
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                      <TextField
                        label="Порог баланса OpenAI, $"
                        type="number"
                        value={settingsForm.openai_balance_threshold}
                        onChange={(e) => handleSettingsFieldChange('openai_balance_threshold', e.target.value)}
                        disabled={settingsLoading}
                        inputProps={{ min: 0, step: 0.5 }}
                        fullWidth
                      />
                      <TextField
                        label="Порог баланса Google, $"
                        type="number"
                        value={settingsForm.google_balance_threshold}
                        onChange={(e) => handleSettingsFieldChange('google_balance_threshold', e.target.value)}
                        disabled={settingsLoading}
                        inputProps={{ min: 0, step: 0.5 }}
                        fullWidth
                      />
                    </Stack>
                    {settingsDirty && (
                      <Typography variant="caption" color="warning.main">
                        Есть несохранённые изменения. Тестовое сообщение отправляется с сохранёнными настройками.
                      </Typography>
                    )}
                    <Stack direction="row" spacing={2}>
                      <Button
                        variant="contained"
                        onClick={handleSaveSystemSettings}
                        disabled={settingsLoading || settingsSaving}
                      >
                        {settingsSaving ? 'Сохранение...' : 'Сохранить'}
                      </Button>
                      <Button
                        variant="outlined"
                        startIcon={<Send />}
                        onClick={handleTestTelegram}
                        disabled={settingsLoading || telegramTesting}
                      >
                        {telegramTesting ? 'Отправка...' : 'Отправить тест'}
                      </Button>
                    </Stack>
                  </Stack>
                </Stack>
              </Paper>
            )}
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
                  <input hidden type="file" accept=".xls,.xlsx,.csv" onChange={handleUpload} />
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

          {searchProgress && (
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
                <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={1}>
                  <Typography variant="h6" sx={{ fontWeight: 600 }}>
                    {searchProgress.running ? 'Прогресс поиска' : 'Поиск завершён'}
                  </Typography>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                    <Chip
                      label={`Обработано ${searchProgress.processed} из ${searchProgress.total}`}
                      color="primary"
                      variant="outlined"
                    />
                    <Chip label={`Найдено: ${searchProgress.found}`} color="success" variant="outlined" />
                    {searchProgress.failed > 0 && (
                      <Chip label={`Ошибок: ${searchProgress.failed}`} color="error" variant="outlined" />
                    )}
                    {!searchProgress.running && (
                      <Tooltip title="Скрыть">
                        <IconButton size="small" onClick={() => setSearchProgress(null)} aria-label="Скрыть прогресс">
                          <Close fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                  </Stack>
                </Box>
                <LinearProgress
                  variant="determinate"
                  color={searchProgress.running ? 'secondary' : searchProgress.failed ? 'warning' : 'success'}
                  value={searchProgress.total ? (searchProgress.processed / searchProgress.total) * 100 : 0}
                />
                <Stack direction="row" spacing={1} flexWrap="wrap">
                  {stageProgress.map((stage) => (
                    <Chip
                      key={stage.name}
                      label={`${stageLabels[stage.name]} · ${progressStateLabel[stage.state]}`}
                      color={progressStateColor[stage.state]}
                      variant={stage.state === 'done' || stage.state === 'warning' || stage.state === 'error' ? 'filled' : 'outlined'}
                      size="small"
                      title={stage.message ?? undefined}
                    />
                  ))}
                </Stack>
              </Stack>
            </Paper>
          )}

          <Paper
            ref={productsSectionRef}
            elevation={10}
            sx={{
              p: { xs: 3, md: 4 },
              borderRadius: fullscreenMode ? 0 : 4,
              border: '1px solid',
              borderColor: 'divider',
              ...(fullscreenMode ? { overflow: 'auto', bgcolor: 'background.default' } : {})
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
                  <Tooltip title={fullscreenMode ? "Выйти из полноэкранного режима" : "Полноэкранный режим"}>
                    <IconButton
                      size="small"
                      color={fullscreenMode ? "primary" : "default"}
                      onClick={toggleFullscreen}
                      sx={{ border: '1px solid', borderColor: 'divider' }}
                    >
                      {fullscreenMode ? <FullscreenExit /> : <Fullscreen />}
                    </IconButton>
                  </Tooltip>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={fitToScreen}
                        onChange={(e) => setFitToScreen(e.target.checked)}
                        size="small"
                      />
                    }
                    label="Подогнать под экран"
                    sx={{ ml: 1 }}
                  />
                  <FormControlLabel
                    control={
                      <Switch
                        checked={tableDraggable}
                        onChange={(e) => setTableDraggable(e.target.checked)}
                        size="small"
                      />
                    }
                    label="Перетаскивание"
                    sx={{ ml: 1 }}
                  />
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

              {selectedVisibleIds.length > 0 && (
                <Box display="flex" alignItems="center" gap={2} flexWrap="wrap">
                  <Typography variant="body2" color="text.secondary">
                    Выбрано строк: {selectedVisibleIds.length}
                  </Typography>
                  <Stack direction="row" spacing={1}>
                    <Tooltip title="Поиск через Google Search для выбранных строк">
                      <Button
                        size="small"
                        variant="contained"
                        color="secondary"
                        startIcon={<Search />}
                        onClick={() => handleBatchSearch(['googlesearch'])}
                        disabled={loading}
                      >
                        Google Search
                      </Button>
                    </Tooltip>
                    <Tooltip title="Поиск через OpenAI для выбранных строк">
                      <Button
                        size="small"
                        variant="contained"
                        color="success"
                        startIcon={<Psychology />}
                        onClick={() => handleBatchSearch(['OpenAI'])}
                        disabled={loading}
                      >
                        OpenAI
                      </Button>
                    </Tooltip>
                    <Tooltip title="Общий поиск (Internet → Google → OpenAI) для выбранных строк">
                      <Button
                        size="small"
                        variant="contained"
                        color="primary"
                        startIcon={<Search />}
                        onClick={() => handleBatchSearch(null)}
                        disabled={loading}
                      >
                        Общий поиск
                      </Button>
                    </Tooltip>
                    <Tooltip title="Удалить выбранные строки">
                      <Button
                        size="small"
                        variant="contained"
                        color="error"
                        startIcon={<DeleteForever />}
                        onClick={handleBatchDelete}
                        disabled={loading}
                      >
                        Удалить ({selectedVisibleIds.length})
                      </Button>
                    </Tooltip>
                  </Stack>
                </Box>
              )}

              {filteredTableData.length === 0 ? (
                <Typography color="text.secondary">Нет данных. Загрузите Excel файл или добавьте товары вручную.</Typography>
              ) : (
                <Draggable
                  disabled={!tableDraggable || tablePinned}
                  position={tableDraggable ? tablePosition : { x: 0, y: 0 }}
                  onStop={(_, data) => {
                    if (tableDraggable && !tablePinned) {
                      setTablePosition({ x: data.x, y: data.y })
                    }
                  }}
                  handle=".drag-handle"
                  grid={[1, 1]}
                  scale={1}
                >
                  <Box
                    sx={{
                      position: tableDraggable ? 'fixed' : 'relative',
                      width: tableDraggable ? 'calc(100vw - 40px)' : '100%',
                      maxWidth: '100%',
                      height: 'auto',
                      minHeight: 'auto',
                      maxHeight: 'none',
                      resize: 'none',
                      overflow: 'visible',
                      border: tableDraggable ? '3px solid' : 'none',
                      borderColor: tableDraggable ? 'primary.main' : 'primary.light',
                      borderRadius: 3,
                      boxShadow: tableDraggable ? '0 8px 32px rgba(0,0,0,0.3)' : 'none',
                      zIndex: tableDraggable ? 1000 : 'auto',
                      backgroundColor: 'background.paper',
                      cursor: tableDraggable ? 'default' : 'auto',
                      transition: tableDraggable ? 'none' : 'all 0.3s ease-in-out',
                      // Responsive adjustments
                      '@media (max-width: 1200px)': {
                        width: '100%',
                        maxWidth: '100%'
                      },
                      '@media (max-width: 768px)': {
                        minHeight: 'auto',
                        fontSize: '0.875rem'
                      }
                    }}
                  >
                    {tableDraggable && (
                      <Box
                        sx={{
                          p: 1,
                          backgroundColor: tablePinned ? 'success.main' : 'primary.main',
                          color: 'primary.contrastText',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          borderTopLeftRadius: 3,
                          borderTopRightRadius: 3,
                          fontWeight: 600,
                          fontSize: '0.875rem',
                          userSelect: 'none'
                        }}
                      >
                        <Box sx={{ width: 40 }} />
                        <Box
                          className="drag-handle"
                          sx={{
                            cursor: tablePinned ? 'not-allowed' : 'move',
                            flex: 1,
                            textAlign: 'center'
                          }}
                        >
                          {tablePinned ? '📌 Таблица закреплена' : '⋮⋮⋮ Перетащите таблицу ⋮⋮⋮'}
                        </Box>
                        <Tooltip title={tablePinned ? 'Открепить таблицу' : 'Закрепить таблицу'}>
                          <IconButton
                            size="small"
                            onClick={() => setTablePinned(!tablePinned)}
                            sx={{ color: 'primary.contrastText' }}
                          >
                            {tablePinned ? <PushPin fontSize="small" /> : <PushPinOutlined fontSize="small" />}
                          </IconButton>
                        </Tooltip>
                      </Box>
                    )}
                  <TableContainer
                    component={Paper}
                    variant="outlined"
                    sx={{
                      maxHeight: 'none',
                      height: 'auto',
                      borderRadius: 3,
                      overflowX: 'visible',
                      overflowY: 'visible',
                      width: '100%',
                      '& .MuiTable-root': {
                        minWidth: 'auto',
                        width: '100%',
                        tableLayout: 'auto'
                      },
                      fontSize: tableFontSize,
                      transition: 'all 0.3s ease-in-out'
                    }}
                  >
                  <Table
                    stickyHeader={false}
                    size={tableSize}
                    sx={{
                      tableLayout: 'auto',
                      width: '100%',
                      minWidth: 'auto',
                      '& .MuiTableCell-root': {
                        fontSize: tableFontSize,
                        padding: '6px 8px',
                        whiteSpace: 'normal',
                        wordWrap: 'break-word'
                      },
                      // Responsive cell sizing
                      '@media (max-width: 1200px)': {
                        '& .MuiTableCell-root': {
                          fontSize: '0.875rem',
                          padding: '8px'
                        }
                      },
                      '@media (max-width: 768px)': {
                        '& .MuiTableCell-root': {
                          fontSize: '0.8rem',
                          padding: '6px'
                        }
                      }
                    }}
                  >
                    <TableHead>
                      <TableRow>
                        <TableCell padding="checkbox" sx={{ width: fitToScreen ? 'auto' : columnWidths.checkbox }}>
                          <Checkbox
                            checked={visibleIds.size > 0 && selectedVisibleIds.length === visibleIds.size}
                            indeterminate={selectedVisibleIds.length > 0 && selectedVisibleIds.length < visibleIds.size}
                            onChange={(e) => handleSelectAll(e.target.checked)}
                          />
                        </TableCell>
                        {/* Известные данные */}
                        {fitToScreen ? (
                          <>
                            <TableCell sx={{ fontWeight: 600 }}>Article</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Req.Mnfc</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Manufacturer</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Alias</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Match</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Confidence</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Source</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Что производит</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Сайт производителя</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Алиасы</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Страна</TableCell>
                            <TableCell sx={{ fontWeight: 600, textAlign: 'center' }}>Действия</TableCell>
                          </>
                        ) : (
                          <>
                            <ResizableCell column="article" width={columnWidths.article} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Article
                            </ResizableCell>
                            <ResizableCell column="submitted" width={columnWidths.submitted} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Req.Mnfc
                            </ResizableCell>
                            <ResizableCell column="manufacturer" width={columnWidths.manufacturer} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Manufacturer
                            </ResizableCell>
                            <ResizableCell column="alias" width={columnWidths.alias} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Alias
                            </ResizableCell>
                            <ResizableCell column="match" width={columnWidths.match} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Match
                            </ResizableCell>
                            <ResizableCell column="confidence" width={columnWidths.confidence} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Confidence
                            </ResizableCell>
                            <ResizableCell column="source" width={columnWidths.source} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Source
                            </ResizableCell>
                            <ResizableCell column="whatProduces" width={columnWidths.whatProduces} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Что производит
                            </ResizableCell>
                            <ResizableCell column="website" width={columnWidths.website} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Сайт производителя
                            </ResizableCell>
                            <ResizableCell column="manufacturerAliases" width={columnWidths.manufacturerAliases} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Алиасы
                            </ResizableCell>
                            <ResizableCell column="country" width={columnWidths.country} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              Страна
                            </ResizableCell>
                            <ResizableCell column="actions" width={columnWidths.actions} onResize={handleColumnResize} onResizeEnd={handleResizeEnd}>
                              <Box textAlign="center">Действия</Box>
                            </ResizableCell>
                          </>
                        )}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {filteredTableData.map((row, rowIndex) => {
                        const isExpanded = expandedTableRows.has(row.id)
                        const hasLogs = Boolean(row.debugLog) || (row.stageHistory?.length ?? 0) > 0
                        return (
                          <Fragment key={row.key}>
                            <TableRow hover sx={{ height: fitToScreen ? 'auto' : rowHeight }}>
                              <TableCell
                                padding="checkbox"
                                sx={{
                                  width: fitToScreen ? 'auto' : columnWidths.checkbox,
                                  height: fitToScreen ? 'auto' : rowHeight,
                                  position: 'relative',
                                  userSelect: rowResizer.isResizing ? 'none' : 'auto'
                                }}
                              >
                                <Stack direction="row" alignItems="center" spacing={0.5}>
                                  {hasLogs && (
                                    <IconButton
                                      size="small"
                                      onClick={() => {
                                        setExpandedTableRows(prev => {
                                          const next = new Set(prev)
                                          if (next.has(row.id)) {
                                            next.delete(row.id)
                                          } else {
                                            next.add(row.id)
                                          }
                                          return next
                                        })
                                      }}
                                    >
                                      {isExpanded ? <KeyboardArrowUp fontSize="small" /> : <KeyboardArrowDown fontSize="small" />}
                                    </IconButton>
                                  )}
                                  <Checkbox
                                    checked={selectedIds.has(row.id)}
                                    onChange={(e) => {
                                      setSelectedIds(prev => {
                                        const next = new Set(prev)
                                        if (e.target.checked) {
                                          next.add(row.id)
                                        } else {
                                          next.delete(row.id)
                                        }
                                        return next
                                      })
                                    }}
                                  />
                                </Stack>
                                {!fitToScreen && rowIndex === 0 && (
                                  <Box
                                    onMouseDown={(e) => rowResizer.handleMouseDown(e, rowHeight)}
                                    sx={{
                                      position: 'absolute',
                                      bottom: 0,
                                      left: 0,
                                      right: 0,
                                      height: 5,
                                      cursor: 'row-resize',
                                      backgroundColor: rowResizer.isResizing ? 'primary.main' : 'transparent',
                                      '&:hover': {
                                        backgroundColor: 'primary.light'
                                      },
                                      zIndex: 1
                                    }}
                                  />
                                )}
                              </TableCell>
                              {/* Известные данные */}
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.article, height: fitToScreen ? 'auto' : rowHeight, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.article}
                              </TableCell>
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.submitted, height: fitToScreen ? 'auto' : rowHeight, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.submitted}
                              </TableCell>
                              {/* Данные от поиска */}
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.manufacturer, height: fitToScreen ? 'auto' : rowHeight, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.manufacturer}
                              </TableCell>
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.alias, height: fitToScreen ? 'auto' : rowHeight, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.alias}
                              </TableCell>
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.match, height: fitToScreen ? 'auto' : rowHeight }}>
                                {renderMatchChip(row.matchStatus, row.matchConfidence)}
                              </TableCell>
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.confidence, height: fitToScreen ? 'auto' : rowHeight }}>
                                {row.confidence ? `${(row.confidence * 100).toFixed(1)}%` : '—'}
                              </TableCell>
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.source, height: fitToScreen ? 'auto' : rowHeight }}>
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
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.whatProduces, height: fitToScreen ? 'auto' : rowHeight, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.whatProduces}
                              </TableCell>
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.website, height: fitToScreen ? 'auto' : rowHeight }}>
                                {row.website !== '—' ? (
                                  <Tooltip title={row.website}>
                                    <Box
                                      component="a"
                                      href={row.website}
                                      target="_blank"
                                      rel="noreferrer"
                                      sx={{
                                        color: 'secondary.main',
                                        textDecoration: 'none',
                                        '&:hover': { textDecoration: 'underline' },
                                        display: 'block',
                                        maxWidth: fitToScreen ? 'none' : 150,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap'
                                      }}
                                    >
                                      {row.website}
                                    </Box>
                                  </Tooltip>
                                ) : (
                                  '—'
                                )}
                              </TableCell>
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.manufacturerAliases, height: fitToScreen ? 'auto' : rowHeight, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.manufacturerAliases}
                              </TableCell>
                              <TableCell sx={{ width: fitToScreen ? 'auto' : columnWidths.country, height: fitToScreen ? 'auto' : rowHeight, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.country}
                              </TableCell>
                              <TableCell align="center" sx={{ width: fitToScreen ? 'auto' : columnWidths.actions, height: fitToScreen ? 'auto' : rowHeight }}>
                                <Tooltip title="Удалить строку">
                                  <IconButton
                                    size="small"
                                    color="error"
                                    onClick={() => handleDeletePartRow(row.id)}
                                  >
                                    <DeleteForever fontSize="small" />
                                  </IconButton>
                                </Tooltip>
                              </TableCell>
                            </TableRow>
                            {hasLogs && (
                              <TableRow>
                                <TableCell style={{ paddingBottom: 0, paddingTop: 0 }} colSpan={13}>
                                  <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                                    <Box sx={{
                                      margin: { xs: 1, md: 2 },
                                      p: { xs: 1.5, md: 2 },
                                      bgcolor: 'background.default',
                                      borderRadius: 2,
                                      '@media (max-width: 768px)': {
                                        fontSize: '0.875rem'
                                      }
                                    }}>
                                      <Stack spacing={2}>
                                        <Box display="flex" justifyContent="space-between" alignItems="center">
                                          <Typography variant="h6" gutterBottom component="div">
                                            Детали поиска
                                          </Typography>
                                          <IconButton
                                            size="small"
                                            onClick={() => {
                                              const logText = JSON.stringify({
                                                article: row.article,
                                                search_stage: row.searchStage,
                                                debug_log: row.debugLog,
                                                stage_history: row.stageHistory
                                              }, null, 2)
                                              handleCopy(logText, 'Логи скопированы в буфер обмена')
                                            }}
                                          >
                                            <ContentCopy fontSize="small" />
                                          </IconButton>
                                        </Box>
                                        {row.searchStage && (
                                          <Box>
                                            <Typography variant="subtitle2" color="text.secondary">
                                              Этап поиска
                                            </Typography>
                                            <Typography variant="body2">{row.searchStage}</Typography>
                                          </Box>
                                        )}
                                        {row.stageHistory && row.stageHistory.length > 0 && (
                                          <Box>
                                            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                                              История этапов
                                            </Typography>
                                            <Stack spacing={1}>
                                              {row.stageHistory.map((stage, idx) => (
                                                <Paper key={idx} sx={{
                                                  p: { xs: 1, md: 1.5 },
                                                  bgcolor: 'action.hover',
                                                  '@media (max-width: 768px)': {
                                                    fontSize: '0.85rem'
                                                  }
                                                }}>
                                                  <Stack spacing={0.5}>
                                                    <Box display="flex" gap={1} alignItems="center" flexWrap="wrap">
                                                      <Chip
                                                        label={stage.name}
                                                        size="small"
                                                        color="primary"
                                                        variant="outlined"
                                                        sx={{
                                                          '@media (max-width: 768px)': {
                                                            fontSize: '0.75rem',
                                                            height: '24px'
                                                          }
                                                        }}
                                                      />
                                                      <Chip
                                                        label={stageStatusDescription[stage.status] || stage.status}
                                                        size="small"
                                                        color={stageStatusChipColor[stage.status] || 'default'}
                                                        sx={{
                                                          '@media (max-width: 768px)': {
                                                            fontSize: '0.75rem',
                                                            height: '24px'
                                                          }
                                                        }}
                                                      />
                                                      {stage.provider && (
                                                        <Chip
                                                          label={stage.provider}
                                                          size="small"
                                                          variant="outlined"
                                                          sx={{
                                                            '@media (max-width: 768px)': {
                                                              fontSize: '0.75rem',
                                                              height: '24px'
                                                            }
                                                          }}
                                                        />
                                                      )}
                                                    </Box>
                                                    {stage.confidence !== null && stage.confidence !== undefined && (
                                                      <Typography variant="caption" color="text.secondary">
                                                        Уверенность: {(stage.confidence * 100).toFixed(1)}%
                                                      </Typography>
                                                    )}
                                                    {stage.urls_considered !== undefined && (
                                                      <Typography variant="caption" color="text.secondary">
                                                        URLs проверено: {stage.urls_considered}
                                                      </Typography>
                                                    )}
                                                    {stage.message && (
                                                      <Typography variant="caption" color="text.secondary">
                                                        {stage.message}
                                                      </Typography>
                                                    )}
                                                  </Stack>
                                                </Paper>
                                              ))}
                                            </Stack>
                                          </Box>
                                        )}
                                        {row.debugLog && (
                                          <Box>
                                            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                                              Debug Log (полный)
                                            </Typography>
                                            <Paper
                                              sx={{
                                                p: 2,
                                                bgcolor: 'action.hover',
                                                maxHeight: 'none',
                                                overflow: 'visible',
                                                fontFamily: 'monospace',
                                                fontSize: '0.85rem',
                                                whiteSpace: 'pre-wrap',
                                                wordBreak: 'break-word',
                                                lineHeight: 1.6
                                              }}
                                            >
                                              {row.debugLog}
                                            </Paper>
                                          </Box>
                                        )}
                                      </Stack>
                                    </Box>
                                  </Collapse>
                                </TableCell>
                              </TableRow>
                            )}
                          </Fragment>
                        )
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
                  </Box>
                </Draggable>
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
                    <Button variant="contained" startIcon={<FilterAlt />} onClick={() => loadLogs(logFilters)} disabled={logsLoading}>
                      Обновить
                    </Button>
                    <FormControlLabel
                      control={
                        <Switch
                          checked={autoRefreshLogs}
                          onChange={(e) => setAutoRefreshLogs(e.target.checked)}
                          size="small"
                        />
                      }
                      label="Авто-обновление"
                    />
                    {autoRefreshLogs && (
                      <TextField
                        size="small"
                        label="Интервал (сек)"
                        type="number"
                        value={refreshInterval / 1000}
                        onChange={(e) => {
                          const seconds = Math.max(1, parseInt(e.target.value) || 5)
                          setRefreshInterval(seconds * 1000)
                        }}
                        sx={{ width: 120 }}
                        inputProps={{ min: 1, max: 60 }}
                      />
                    )}
                  </Stack>
                </Box>
                {logsLoading && <LinearProgress />}
                <TableContainer
                  component={Paper}
                  variant="outlined"
                  sx={{ maxHeight: 540, borderRadius: 3 }}
                >
                  <Table stickyHeader size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ fontWeight: 600, width: 50 }} />
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
                          <TableCell colSpan={7}>
                            <Typography color="text.secondary">Логи отсутствуют или не соответствуют фильтрам.</Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        logs.map((entry) => {
                          const isExpanded = expandedLogIds.has(entry.id)
                          // Форматируем JSON только для раскрытой записи
                          const formattedPayload = isExpanded ? formatJSON(entry.payload) : ''
                          return (
                            <Fragment key={entry.id}>
                              <TableRow hover>
                                <TableCell>
                                  <IconButton
                                    size="small"
                                    onClick={() => toggleLogExpansion(entry.id)}
                                    aria-label="expand row"
                                  >
                                    {isExpanded ? <KeyboardArrowUp /> : <KeyboardArrowDown />}
                                  </IconButton>
                                </TableCell>
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
                                <TableCell sx={{ maxWidth: 400 }}>
                                  <Typography variant="body2" noWrap>
                                    {entry.query}
                                  </Typography>
                                </TableCell>
                                <TableCell>{entry.status_code ?? '—'}</TableCell>
                                <TableCell sx={{ maxWidth: 400 }}>
                                  <Box display="flex" alignItems="center" gap={1}>
                                    <Typography variant="body2" noWrap sx={{ flex: 1 }}>
                                      {entry.payload ? (entry.payload.length > 100 ? entry.payload.substring(0, 100) + '...' : entry.payload) : '—'}
                                    </Typography>
                                    {entry.payload && (
                                      <IconButton
                                        size="small"
                                        onClick={(e) => {
                                          e.stopPropagation()
                                          handleCopy(formatJSON(entry.payload) || (entry.payload ?? ''))
                                        }}
                                        title="Копировать полный payload"
                                      >
                                        <ContentCopy fontSize="small" />
                                      </IconButton>
                                    )}
                                  </Box>
                                </TableCell>
                              </TableRow>
                              <TableRow>
                                <TableCell style={{ paddingBottom: 0, paddingTop: 0 }} colSpan={7}>
                                  <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                                    <Box sx={{ margin: 2, p: 2, bgcolor: 'background.default', borderRadius: 2 }}>
                                      <Stack spacing={2}>
                                        <Box display="flex" justifyContent="space-between" alignItems="center">
                                          <Typography variant="h6" gutterBottom component="div">
                                            Полная информация
                                          </Typography>
                                          <Button
                                            size="small"
                                            startIcon={<ContentCopy />}
                                            onClick={() => handleCopy(formattedPayload || entry.query)}
                                          >
                                            Копировать
                                          </Button>
                                        </Box>
                                        <Box>
                                          <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                                            Запрос:
                                          </Typography>
                                          <Paper variant="outlined" sx={{ p: 2, bgcolor: 'background.paper' }}>
                                            <Typography
                                              variant="body2"
                                              component="pre"
                                              sx={{
                                                fontFamily: 'monospace',
                                                whiteSpace: 'pre-wrap',
                                                wordBreak: 'break-word',
                                                margin: 0
                                              }}
                                            >
                                              {entry.query}
                                            </Typography>
                                          </Paper>
                                        </Box>
                                        {entry.payload && (
                                          <Box>
                                            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
                                              <Typography variant="subtitle2" color="text.secondary">
                                                Payload {entry.direction === 'response' ? '(Ответ)' : '(Запрос)'} - Полный:
                                              </Typography>
                                              <Button
                                                size="small"
                                                variant="outlined"
                                                startIcon={<ContentCopy />}
                                                onClick={() => handleCopy(formattedPayload || (entry.payload ?? ''))}
                                              >
                                                Копировать payload
                                              </Button>
                                            </Box>
                                            <Paper
                                              variant="outlined"
                                              sx={{
                                                p: 2,
                                                bgcolor: 'background.paper',
                                                maxHeight: 'none',
                                                overflow: 'auto',
                                                border: '1px solid',
                                                borderColor: 'divider'
                                              }}
                                            >
                                              <Typography
                                                variant="body2"
                                                component="pre"
                                                sx={{
                                                  fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                                                  whiteSpace: 'pre-wrap',
                                                  wordBreak: 'break-word',
                                                  margin: 0,
                                                  fontSize: '0.8rem',
                                                  lineHeight: 1.6,
                                                  color: 'text.primary'
                                                }}
                                              >
                                                {formattedPayload}
                                              </Typography>
                                            </Paper>
                                          </Box>
                                        )}
                                        {entry.status_code && (
                                          <Box>
                                            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                                              Статус код:
                                            </Typography>
                                            <Chip
                                              label={entry.status_code}
                                              color={entry.status_code >= 200 && entry.status_code < 300 ? 'success' : 'error'}
                                              size="small"
                                            />
                                          </Box>
                                        )}
                                      </Stack>
                                    </Box>
                                  </Collapse>
                                </TableCell>
                              </TableRow>
                            </Fragment>
                          )
                        })
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
      <Dialog
        open={apiConfigOpen}
        onClose={() => setApiConfigOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          <Box display="flex" alignItems="center" gap={1}>
            <Api color="primary" />
            <Typography variant="h6">Настройка API подключения</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          <Stack spacing={3} sx={{ mt: 2 }}>
            <TextField
              label="API URL"
              value={apiConfig.apiUrl}
              onChange={(e) => handleApiConfigChange('apiUrl', e.target.value)}
              fullWidth
              placeholder="https://api.example.com"
              helperText="Базовый URL для API запросов"
            />
            <TextField
              label="API Key"
              value={apiConfig.apiKey}
              onChange={(e) => handleApiConfigChange('apiKey', e.target.value)}
              fullWidth
              placeholder="your-api-key"
              helperText="API ключ для аутентификации"
              type="password"
            />
            <TextField
              label="API Token"
              value={apiConfig.apiToken}
              onChange={(e) => handleApiConfigChange('apiToken', e.target.value)}
              fullWidth
              placeholder="Bearer token"
              helperText="Токен авторизации (если требуется)"
              type="password"
            />
            <TextField
              label="Swagger URL"
              value={apiConfig.swaggerUrl}
              onChange={(e) => handleApiConfigChange('swaggerUrl', e.target.value)}
              fullWidth
              placeholder="https://api.example.com/swagger/v1/swagger.json"
              helperText="URL Swagger документации"
            />
            <TextField
              label="Дополнительные заголовки"
              value={apiConfig.customHeaders}
              onChange={(e) => handleApiConfigChange('customHeaders', e.target.value)}
              fullWidth
              multiline
              rows={4}
              placeholder='{"Content-Type": "application/json", "X-Custom-Header": "value"}'
              helperText="JSON объект с дополнительными HTTP заголовками"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setApiConfigOpen(false)}>
            Отмена
          </Button>
          <Button variant="contained" onClick={handleSaveApiConfig} startIcon={<Api />}>
            Сохранить настройки
          </Button>
        </DialogActions>
      </Dialog>
    </ThemeProvider>
  )
}
