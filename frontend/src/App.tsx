import { Fragment, SyntheticEvent, useEffect, useMemo, useRef, useState } from 'react'
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
import InputAdornment from '@mui/material/InputAdornment'
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
  Factory,
  DeleteForever,
  VisibilityOff,
  Visibility,
  ListAlt,
  FilterAlt
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

const colorPulse = keyframes`
  0% { filter: hue-rotate(0deg) brightness(1); }
  50% { filter: hue-rotate(18deg) brightness(1.35); }
  100% { filter: hue-rotate(0deg) brightness(1); }
`

const snowfall = keyframes`
  0% { transform: translate3d(0, -12vh, 0); }
  100% { transform: translate3d(var(--drift, 0px), 110vh, 0); }
`

const gallop = keyframes`
  0% { transform: translateX(0) translateY(0); }
  25% { transform: translateX(6px) translateY(-3px); }
  50% { transform: translateX(12px) translateY(0); }
  75% { transform: translateX(18px) translateY(-2px); }
  100% { transform: translateX(24px) translateY(0); }
`

const floatBob = keyframes`
  0% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
  100% { transform: translateY(0); }
`

const panBackground = keyframes`
  0% { transform: scale(1.02) translate3d(0, 0, 0); filter: saturate(1.05); }
  50% { transform: scale(1.08) translate3d(-2%, -1%, 0); filter: saturate(1.1); }
  100% { transform: scale(1.02) translate3d(0, 0, 0); filter: saturate(1.05); }
`

const starPulse = keyframes`
  0% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 0.95; transform: scale(1.1); }
  100% { opacity: 0.35; transform: scale(0.85); }
`

const shootingStar = keyframes`
  0% { opacity: 0; transform: translate3d(120%, -40%, 0) rotate(-18deg); }
  10% { opacity: 0.9; }
  40% { opacity: 1; transform: translate3d(-10%, 40%, 0) rotate(-18deg); }
  60% { opacity: 0; transform: translate3d(-30%, 60%, 0) rotate(-18deg); }
  100% { opacity: 0; transform: translate3d(-60%, 90%, 0) rotate(-18deg); }
`

const auroraFlow = keyframes`
  0% { background-position: 0% 50%; opacity: 0.18; }
  50% { background-position: 100% 50%; opacity: 0.36; }
  100% { background-position: 0% 50%; opacity: 0.22; }
`

const starField = [
  { x: 6, y: 12, size: 3, duration: 5.6, delay: 0.3 },
  { x: 18, y: 18, size: 2.5, duration: 6.2, delay: 1.1 },
  { x: 32, y: 10, size: 2.2, duration: 7.4, delay: 0.6 },
  { x: 44, y: 22, size: 3.2, duration: 5.9, delay: 1.4 },
  { x: 58, y: 14, size: 2.8, duration: 7.1, delay: 0.8 },
  { x: 72, y: 16, size: 3, duration: 6.4, delay: 1.6 },
  { x: 86, y: 12, size: 2.4, duration: 7.8, delay: 0.5 },
  { x: 12, y: 36, size: 2.6, duration: 6.7, delay: 1.9 },
  { x: 28, y: 42, size: 3.4, duration: 6.1, delay: 0.9 },
  { x: 46, y: 34, size: 2.2, duration: 7.2, delay: 1.3 },
  { x: 62, y: 40, size: 3.1, duration: 5.7, delay: 0.7 },
  { x: 76, y: 36, size: 2.5, duration: 6.9, delay: 1.5 },
  { x: 88, y: 44, size: 3.3, duration: 6.3, delay: 1.2 }
]

const holidayBackdropSvg = encodeURIComponent(`
  <svg width="1600" height="900" viewBox="0 0 1600 900" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="sky" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="#0b1a3d"/>
        <stop offset="45%" stop-color="#0d2b66"/>
        <stop offset="100%" stop-color="#0a1735"/>
      </linearGradient>
      <radialGradient id="moon" cx="76%" cy="16%" r="14%">
        <stop offset="0%" stop-color="#cde7ff" stop-opacity="1"/>
        <stop offset="60%" stop-color="#7fb7ff" stop-opacity="0.6"/>
        <stop offset="100%" stop-color="#1a2e57" stop-opacity="0"/>
      </radialGradient>
      <radialGradient id="snowGlow" cx="50%" cy="85%" r="60%">
        <stop offset="0%" stop-color="#ffffff" stop-opacity="0.55"/>
        <stop offset="65%" stop-color="#d8ecff" stop-opacity="0.18"/>
        <stop offset="100%" stop-color="#0a1735" stop-opacity="0"/>
      </radialGradient>
      <radialGradient id="tree" cx="50%" cy="0%" r="100%">
        <stop offset="0%" stop-color="#1cb36b" stop-opacity="0.95"/>
        <stop offset="70%" stop-color="#0f6b3f" stop-opacity="0.92"/>
        <stop offset="100%" stop-color="#0d3b2a" stop-opacity="0.9"/>
      </radialGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#sky)"/>
    <rect width="1600" height="900" fill="url(#moon)"/>
    <rect width="1600" height="900" fill="url(#snowGlow)"/>
    <g fill="#e3f5ff" opacity="0.82">
      <circle cx="140" cy="160" r="1.8"/><circle cx="220" cy="120" r="2.2"/><circle cx="320" cy="90" r="1.6"/>
      <circle cx="520" cy="110" r="2.5"/><circle cx="880" cy="140" r="1.4"/><circle cx="1080" cy="110" r="1.9"/>
      <circle cx="1220" cy="180" r="2.4"/><circle cx="1350" cy="90" r="1.8"/><circle cx="1480" cy="130" r="2.1"/>
    </g>
    <g fill="#d1e4ff" opacity="0.35">
      <ellipse cx="280" cy="820" rx="420" ry="180"/>
      <ellipse cx="1120" cy="810" rx="480" ry="170"/>
    </g>
    <g opacity="0.78">
      <path d="M1180 380 Q1220 360 1260 365 Q1320 380 1345 410 Q1320 395 1290 398 Q1240 402 1180 380 Z" fill="#fefefe"/>
      <path d="M1180 380 Q1225 345 1280 332 Q1345 320 1410 340 Q1360 340 1298 355 Q1240 370 1180 380 Z" fill="#b0d8ff" opacity="0.62"/>
    </g>
    <g transform="translate(180,420)" opacity="0.94">
      <path d="M140 260 L180 180 L220 260 Z" fill="#ffd166"/>
      <path d="M100 320 L180 120 L260 320 Z" fill="url(#tree)"/>
      <path d="M140 310 L180 210 L220 310 Z" fill="#0e8a4f" opacity="0.9"/>
      <rect x="172" y="320" width="16" height="40" rx="4" fill="#7a4c31"/>
      <circle cx="180" cy="210" r="6" fill="#ffe066"/>
      <g fill="#ff6b6b" opacity="0.95">
        <circle cx="180" cy="250" r="7"/><circle cx="150" cy="270" r="6"/><circle cx="210" cy="270" r="6"/>
        <circle cx="168" cy="290" r="5"/><circle cx="192" cy="292" r="5"/>
      </g>
    </g>
    <g transform="translate(1030,240)" opacity="0.88">
      <path d="M0 120 Q60 110 120 120 Q180 135 210 150 Q180 145 120 152 Q60 158 0 150 Z" fill="#fefefe"/>
      <path d="M0 120 Q60 100 120 95 Q180 90 240 105 Q200 105 140 112 Q80 118 0 120 Z" fill="#8bc7ff" opacity="0.55"/>
    </g>
    <g transform="translate(960,360)" fill="#d9edff" stroke="#b1d6ff" stroke-width="2" stroke-linecap="round" opacity="0.9">
      <path d="M40 0 Q70 -10 100 0 L140 30 Q110 22 80 25 Q60 28 40 32 Z" fill="#fefefe"/>
      <path d="M0 30 Q40 10 90 10 Q140 10 180 30" fill="none"/>
      <path d="M50 40 Q80 30 110 40" fill="none"/>
      <path d="M110 38 Q140 28 170 38" fill="none"/>
    </g>
  </svg>
`)
const holidayBackdropImage = `url("data:image/svg+xml,${holidayBackdropSvg}")`

const HolidayGarland = () => {
  const palette = ['#ff6b6b', '#ffd166', '#6dd3c2', '#74c0fc', '#c8b6ff', '#ffa8e2']
  return (
    <Box
      sx={{
        position: 'absolute',
        top: 12,
        left: 0,
        right: 0,
        display: 'flex',
        justifyContent: 'space-evenly',
        px: 4,
        zIndex: 2,
        animation: `${garlandSwing} 6s ease-in-out infinite`
      }}
    >
      {Array.from({ length: 32 }).map((_, index) => (
        <Box
          key={index}
          sx={{
            width: 13,
            height: 13,
            borderRadius: '50%',
            background: palette[index % palette.length],
            boxShadow: `0 0 14px ${palette[index % palette.length]}`,
            animation: `${twinkle} 2.4s ease-in-out infinite, ${colorPulse} 4.8s linear infinite`,
            animationDelay: `${index * 60}ms`
          }}
        />
      ))}
    </Box>
  )
}

let snowflakeId = 0

const HolidayBackdrop = () => (
  <Box
    sx={{
      position: 'fixed',
      inset: 0,
      pointerEvents: 'none',
      zIndex: 0,
      overflow: 'hidden'
    }}
  >
    <Box
      sx={{
        position: 'absolute',
        inset: '-6%',
        backgroundImage: `linear-gradient(120deg, rgba(10,20,48,0.45), rgba(10,14,28,0.2) 30%, rgba(5,10,26,0.55)), ${holidayBackdropImage}`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        filter: 'drop-shadow(0 20px 40px rgba(0,0,0,0.25))',
        transformOrigin: 'center',
        animation: `${panBackground} 28s ease-in-out infinite`
      }}
    />

    <Box
      sx={{
        position: 'absolute',
        inset: 0,
        background:
          'radial-gradient(circle at 20% 20%, rgba(60,120,220,0.14), transparent 35%), radial-gradient(circle at 80% 10%, rgba(255,180,120,0.14), transparent 30%), linear-gradient(180deg, rgba(5,10,30,0.12), rgba(5,8,20,0.65) 60%, rgba(5,8,20,0.78))',
        backdropFilter: 'blur(2px)',
        mixBlendMode: 'screen'
      }}
    />

    <Box
      sx={{
        position: 'absolute',
        inset: 0,
        background:
          'radial-gradient(circle at 50% 70%, rgba(255,255,255,0.12), transparent 45%), radial-gradient(circle at 10% 80%, rgba(255,255,255,0.22), transparent 35%)',
        opacity: 0.9
      }}
    />
  </Box>
)

const SnowCanvas = () => {
  type Snowflake = {
    id: number
    left: number
    size: number
    duration: number
    delay: number
    opacity: number
    drift: number
    band: number
  }

  const createSnowflake = (): Snowflake => ({
    id: snowflakeId++,
    left: Math.random(),
    size: 3 + Math.random() * 5,
    duration: 8 + Math.random() * 12,
    delay: -Math.random() * 12,
    opacity: 0.45 + Math.random() * 0.4,
    drift: (Math.random() - 0.5) * 18,
    band: Math.random()
  })

  const [flakes, setFlakes] = useState<Snowflake[]>(() => Array.from({ length: 90 }, createSnowflake))

  useEffect(() => {
    const timer = window.setInterval(() => {
      setFlakes((prev) => (prev.length < 200 ? [...prev, createSnowflake()] : prev))
    }, 900)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      const x = event.clientX / window.innerWidth
      const y = event.clientY / window.innerHeight
      setFlakes((prev) =>
        prev.filter((flake) => Math.abs(flake.left - x) > 0.08 || Math.abs(flake.band - y) > 0.12)
      )
    }
    window.addEventListener('mousemove', handleMouseMove)
    return () => window.removeEventListener('mousemove', handleMouseMove)
  }, [])

  return (
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 1,
        overflow: 'hidden'
      }}
    >
      {flakes.map((flake) => (
        <Box
          key={flake.id}
          sx={{
            position: 'absolute',
            left: `${flake.left * 100}%`,
            top: '-12vh',
            width: flake.size,
            height: flake.size,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, rgba(255,255,255,0.95), rgba(255,255,255,0.68))',
            boxShadow: '0 0 10px rgba(255,255,255,0.8)',
            opacity: flake.opacity,
            animation: `${snowfall} ${flake.duration}s linear infinite`,
            animationDelay: `${flake.delay}s`,
            '--drift': `${flake.drift}px`
          }}
        />
      ))}
    </Box>
  )
}

const FestiveScene = () => {
  const ornaments = useMemo(
    () =>
      Array.from({ length: 12 }).map((_, index) => ({
        left: 26 + Math.random() * 18,
        top: 18 + Math.random() * 48,
        color: ['#ff6b6b', '#ffd166', '#6dd3c2', '#74c0fc', '#c8b6ff'][index % 5]
      })),
    []
  )

  const gnomes = useMemo(
    () => [
      { left: '8%', delay: 0 },
      { left: '18%', delay: 1.2 },
      { left: '27%', delay: 2.4 }
    ],
    []
  )

  return (
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 0
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(circle at 10% 10%, rgba(15,163,177,0.18), transparent 42%), radial-gradient(circle at 80% 20%, rgba(255,107,154,0.16), transparent 46%), radial-gradient(circle at 30% 80%, rgba(139,92,246,0.2), transparent 42%), linear-gradient(180deg, rgba(232,246,255,0.52) 0%, rgba(231,240,255,0.35) 45%, rgba(248,243,255,0.35) 100%)',
          opacity: 0.75,
          mixBlendMode: 'screen'
        }}
      />

      <Box
        sx={{
          position: 'absolute',
          left: '-15%',
          right: '-15%',
          bottom: -30,
          height: 240,
          background:
            'radial-gradient(circle at 20% 20%, rgba(15,163,177,0.16), transparent 35%), radial-gradient(circle at 80% 30%, rgba(255,107,154,0.18), transparent 32%), radial-gradient(circle at 45% 70%, rgba(139,92,246,0.18), transparent 40%)',
          filter: 'blur(3px)',
          opacity: 0.65,
          animation: `${drift} 18s ease-in-out infinite`
        }}
      />

      <HolidayGarland />

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

      <Box
        sx={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: 180,
          background: 'linear-gradient(180deg, rgba(255,255,255,0), rgba(255,255,255,0.86))',
          backdropFilter: 'blur(6px)',
          overflow: 'hidden'
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            left: '52%',
            bottom: 20,
            width: 0,
            height: 0,
            borderLeft: '70px solid transparent',
            borderRight: '70px solid transparent',
            borderBottom: '140px solid #2f9e44',
            filter: 'drop-shadow(0 16px 16px rgba(0,0,0,0.08))',
            transform: 'translateX(-50%)'
          }}
        />
        <Box
          sx={{
            position: 'absolute',
            left: '52%',
            bottom: 150,
            width: 14,
            height: 14,
            background: 'linear-gradient(135deg, #ffd166, #ffa94d)',
            clipPath: 'polygon(50% 0%, 61% 35%, 98% 35%, 68% 57%, 79% 91%, 50% 70%, 21% 91%, 32% 57%, 2% 35%, 39% 35%)',
            transform: 'translateX(-50%)',
            boxShadow: '0 0 12px rgba(255,209,102,0.8)'
          }}
        />
        <Box
          sx={{
            position: 'absolute',
            left: '52%',
            bottom: 30,
            width: 24,
            height: 32,
            background: '#874d30',
            borderRadius: 8,
            transform: 'translateX(-50%)',
            boxShadow: '0 8px 12px rgba(0,0,0,0.12)'
          }}
        />
        {ornaments.map((ornament, index) => (
          <Box
            key={index}
            sx={{
              position: 'absolute',
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: ornament.color,
              left: `${ornament.left}%`,
              bottom: `${ornament.top}px`,
              boxShadow: `0 0 8px ${ornament.color}`,
              animation: `${twinkle} 3.4s ease-in-out infinite`,
              animationDelay: `${index * 90}ms`
            }}
          />
        ))}

        <Box
          sx={{
            position: 'absolute',
            right: '12%',
            bottom: 26,
            width: 120,
            height: 70,
            borderRadius: '40% 40% 38% 50%',
            background: 'linear-gradient(135deg, #c68e59, #9c6b3f)',
            boxShadow: '0 10px 18px rgba(0,0,0,0.18)',
            animation: `${gallop} 2.4s ease-in-out infinite`,
            transformOrigin: 'left bottom'
          }}
        >
          <Box
            sx={{
              position: 'absolute',
              width: 52,
              height: 42,
              background: 'linear-gradient(135deg, #c68e59, #d0a070)',
              borderRadius: '45% 45% 40% 40%',
              top: -26,
              right: 14,
              transform: 'rotate(-6deg)',
              boxShadow: '0 6px 12px rgba(0,0,0,0.12)'
            }}
          />
          <Box
            sx={{
              position: 'absolute',
              width: 10,
              height: 26,
              background: '#8b5a2b',
              borderRadius: '4px',
              bottom: -10,
              left: 18,
              boxShadow: '14px 4px 0 0 #8b5a2b, 46px 2px 0 0 #8b5a2b'
            }}
          />
          <Box
            sx={{
              position: 'absolute',
              width: 8,
              height: 18,
              background: '#8b5a2b',
              borderRadius: '4px',
              bottom: -6,
              right: 18,
              boxShadow: '14px -2px 0 0 #8b5a2b'
            }}
          />
          <Box
            sx={{
              position: 'absolute',
              width: 10,
              height: 12,
              background: '#f2d0a4',
              borderRadius: '50%',
              top: -12,
              right: 0,
              boxShadow: '0 0 12px rgba(255,255,255,0.4)'
            }}
          />
        </Box>

        {gnomes.map((gnome, index) => (
          <Box
            key={index}
            sx={{
              position: 'absolute',
              width: 74,
              height: 140,
              left: gnome.left,
              bottom: 6,
              transformOrigin: 'center bottom',
              animation: `${floatBob} 6s ease-in-out infinite`,
              animationDelay: `${gnome.delay}s`
            }}
          >
            <Box
              sx={{
                position: 'absolute',
                top: 0,
                left: '50%',
                width: 80,
                height: 80,
                background: 'linear-gradient(135deg, #9c6b3f, #c68e59)',
                borderRadius: '50% 50% 40% 40%',
                transform: 'translateX(-50%) rotate(-4deg)',
                boxShadow: '0 12px 24px rgba(0,0,0,0.18)'
              }}
            />
            <Box
              sx={{
                position: 'absolute',
                top: 62,
                left: '50%',
                width: 76,
                height: 64,
                background: 'linear-gradient(135deg, #e63946, #ff6b6b)',
                clipPath: 'polygon(50% 0%, 100% 100%, 0% 100%)',
                transform: 'translateX(-50%)',
                boxShadow: '0 16px 28px rgba(0,0,0,0.14)'
              }}
            />
            <Box
              sx={{
                position: 'absolute',
                top: 72,
                left: '50%',
                width: 62,
                height: 70,
                background: 'linear-gradient(135deg, #f1f3f5, #dee2e6)',
                borderRadius: '0 0 22px 22px',
                transform: 'translateX(-50%)',
                boxShadow: '0 8px 16px rgba(0,0,0,0.12)'
              }}
            />
            <Box
              sx={{
                position: 'absolute',
                top: 98,
                left: '50%',
                width: 18,
                height: 18,
                background: '#ffd166',
                borderRadius: '50%',
                transform: 'translateX(-50%)',
                boxShadow: '0 0 12px rgba(255,209,102,0.8)'
              }}
            />
            <Box
              sx={{
                position: 'absolute',
                top: 46,
                left: '50%',
                width: 42,
                height: 32,
                background: 'linear-gradient(135deg, #f8e0c2, #f3caa0)',
                borderRadius: '40% 40% 34% 34%',
                transform: 'translateX(-50%)'
              }}
            />
            <Box
              sx={{
                position: 'absolute',
                top: 58,
                left: '50%',
                width: 10,
                height: 10,
                background: '#f08080',
                borderRadius: '50%',
                transform: 'translateX(-50%)',
                boxShadow: '-12px 2px 0 0 #f08080, 12px 2px 0 0 #f08080'
              }}
            />
            <Box
              sx={{
                position: 'absolute',
                top: 86,
                left: '50%',
                width: 16,
                height: 20,
                background: '#ffffff',
                borderRadius: '40% 40% 50% 50%',
                transform: 'translateX(-50%)',
                boxShadow: '0 10px 12px rgba(0,0,0,0.12)'
              }}
            />
            <Box
              sx={{
                position: 'absolute',
                bottom: 6,
                left: '50%',
                width: 52,
                height: 12,
                background: 'linear-gradient(135deg, #a5d8ff, #d0ebff)',
                borderRadius: 12,
                transform: 'translateX(-50%)',
                boxShadow: '0 12px 16px rgba(0,0,0,0.16)'
              }}
            />
          </Box>
        ))}
      </Box>
    </Box>
  )
}

const HolidayExperience = () => (
  <>
    <HolidayBackdrop />
    <FestiveScene />
    <SnowCanvas />
  </>
)

const DarkStarrySky = () => (
  <Box
    sx={{
      position: 'absolute',
      inset: 0,
      overflow: 'hidden',
      pointerEvents: 'none',
      zIndex: 0,
      mixBlendMode: 'screen'
    }}
  >
      <Box
        sx={{
          position: 'absolute',
          inset: '-20% -10% 40% -10%',
          background: `
            radial-gradient(circle at 20% 20%, rgba(82,140,255,0.25), transparent 45%),
            radial-gradient(circle at 80% 15%, rgba(121,92,255,0.18), transparent 45%),
            radial-gradient(circle at 45% 60%, rgba(66,186,227,0.2), transparent 50%)
          `,
          filter: 'blur(38px)',
          animation: `${auroraFlow} 22s ease-in-out infinite`
        }}
      />
    <Box
      sx={{
        position: 'absolute',
        inset: 0,
        background: 'linear-gradient(180deg, rgba(5,9,15,0) 0%, rgba(5,9,15,0.6) 45%, rgba(5,9,15,0.9) 80%)'
      }}
    />
    {starField.map((star, index) => (
      <Box
        key={`${star.x}-${star.y}-${index}`}
        sx={{
          position: 'absolute',
          top: `${star.y}%`,
          left: `${star.x}%`,
          width: star.size,
          height: star.size,
          borderRadius: '50%',
          background: 'radial-gradient(circle, #e5f2ff 0%, #8fc7ff 40%, rgba(143,199,255,0.4) 70%, transparent 100%)',
          boxShadow: '0 0 12px rgba(143,199,255,0.9)',
          animation: `${starPulse} ${star.duration}s ease-in-out ${star.delay}s infinite`
        }}
      />
    ))}
    {[0, 1, 2].map((index) => (
      <Box
        key={`shooting-${index}`}
        sx={{
          position: 'absolute',
          top: `${10 + index * 24}%`,
          right: '-40%',
          width: 220,
          height: 2,
          background: `
            linear-gradient(
              90deg,
              rgba(255, 255, 255, 0) 0%,
              rgba(173, 210, 255, 0.9) 45%,
              rgba(91, 167, 255, 0.95) 65%,
              rgba(255, 255, 255, 0) 100%
            )
          `,
          filter: 'drop-shadow(0 0 6px rgba(120,180,255,0.75))',
          animation: `${shootingStar} 9s ease-in-out ${index * 2.8}s infinite`
        }}
      />
    ))}
  </Box>
)

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
  const [tableFilters, setTableFilters] = useState<{
    article: string
    manufacturer: string
    alias: string
    submitted: string
    service: string
    source: string
    match: 'all' | 'matched' | 'mismatch' | 'pending' | 'none'
  }>({
    article: '',
    manufacturer: '',
    alias: '',
    submitted: '',
    service: '',
    source: '',
    match: 'all'
  })
  const [selectedRows, setSelectedRows] = useState<number[]>([])
  const [activePage, setActivePage] = useState<'dashboard' | 'logs'>('dashboard')
  const [logs, setLogs] = useState<SearchLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [selectedLog, setSelectedLog] = useState<SearchLog | null>(null)
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
      confidence: record.confidence ?? null,
      service: record.search_stage
        ? stageLabels[record.search_stage as StageName] ?? record.search_stage
        : '—',
      source: record.source_url ?? '—',
      stageHistory: record.stage_history ?? [],
      debugLog: record.debug_log ?? null,
      createdAt: record.created_at
    }))
  }, [history])
  const filteredTableData = useMemo(() => {
    const articleTerm = tableFilters.article.trim().toLowerCase()
    const manufacturerTerm = tableFilters.manufacturer.trim().toLowerCase()
    const aliasTerm = tableFilters.alias.trim().toLowerCase()
    const submittedTerm = tableFilters.submitted.trim().toLowerCase()
    const serviceTerm = tableFilters.service.trim().toLowerCase()
    const sourceTerm = tableFilters.source.trim().toLowerCase()
    return tableData.filter((row) => {
      const isFound = row.manufacturer !== '—' && row.matchStatus !== 'mismatch'
      const isMissing = row.manufacturer === '—' || row.matchStatus === 'mismatch'
      if (manufacturerFilter === 'found' && !isFound) return false
      if (manufacturerFilter === 'missing' && !isMissing) return false

      const matchesArticle = row.article.toLowerCase().includes(articleTerm)
      const matchesManufacturer = row.manufacturer.toLowerCase().includes(manufacturerTerm)
      const matchesAlias = row.alias.toLowerCase().includes(aliasTerm)
      const matchesSubmitted = row.submitted.toLowerCase().includes(submittedTerm)
      const matchesService = row.service.toLowerCase().includes(serviceTerm)
      const matchesSource = row.source.toLowerCase().includes(sourceTerm)
      const matchesMatchStatus = (() => {
        if (tableFilters.match === 'all') return true
        if (tableFilters.match === 'none') return row.matchStatus === null
        return row.matchStatus === tableFilters.match
      })()

      return (
        matchesArticle &&
        matchesManufacturer &&
        matchesAlias &&
        matchesSubmitted &&
        matchesService &&
        matchesSource &&
        matchesMatchStatus
      )
    })
  }, [manufacturerFilter, tableData, tableFilters])
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
  useEffect(() => {
    setSelectedRows((prev) => prev.filter((id) => filteredTableData.some((row) => row.id === id)))
  }, [filteredTableData])
  const [snackbar, setSnackbar] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [stageProgress, setStageProgress] = useState<StageProgressEntry[]>(() =>
    STAGE_SEQUENCE.map((name) => ({ name, state: 'idle' }))
  )
  const [uploadState, setUploadState] = useState<{ status: 'idle' | 'uploading' | 'done' | 'error'; message?: string }>(
    { status: 'idle' }
  )
  const [uploadedItems, setUploadedItems] = useState<PartRequestItem[]>([])
  const uploadInputRef = useRef<HTMLInputElement | null>(null)
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

  const prettifyPayload = (value?: string | null) => {
    if (!value) return '—'
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch (error) {
      return value
    }
  }

  const handleSelectAllRows = (checked: boolean) => {
    setSelectedRows(checked ? filteredTableData.map((row) => row.id) : [])
  }

  const handleToggleRowSelection = (id: number) => {
    setSelectedRows((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]))
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

  const performSearch = async (targets: PartRequestItem[]) => {
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
      const response = await searchParts(filled, debugMode)
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
      setSnackbar(`Добавлено: ${created.part_number}`)
      await refreshHistory()
    } catch (error) {
      setSnackbar('Не удалось добавить запись вручную')
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
      setUploadState({ status: 'done', message: `${statusMessage}. Готово к поиску` })
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
            {themeMode === 'holiday' && <HolidayExperience />}
            {themeMode === 'dark' && <DarkStarrySky />}
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
          {themeMode === 'holiday' && <HolidayExperience />}
          {themeMode === 'dark' && <DarkStarrySky />}
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
        {activePage === 'dashboard' ? (
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
              <Stack
                direction={{ xs: 'column', md: 'row' }}
                spacing={3}
                alignItems="flex-start"
                justifyContent="space-between"
              >
                <Box>
                  <Typography variant="h3" sx={{ fontWeight: 600 }}>
                    Поиск производителей нового поколения
                  </Typography>
                  <Typography variant="body1" color="text.secondary" sx={{ mt: 1.5 }}>
                    Анализируем datasheet-и, доменные подсказки и OpenAI, чтобы точно определить бренд по артикулу и алиасу.
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1.5} flexWrap="wrap">
                  <Chip label="67% AI threshold" color="secondary" />
                  <Chip label="SOCKS5 ready" variant="outlined" color="primary" />
                  <Chip label="PDF · Excel экспорт" variant="outlined" />
                </Stack>
              </Stack>
              <Stack direction="row" spacing={2} alignItems="center">
                <Avatar sx={{ bgcolor: 'primary.main', width: 48, height: 48, fontWeight: 600 }}>AI</Avatar>
                <Typography color="text.secondary">
                  Интернет → Google Custom Search → OpenAI. Каждый этап логируется и отображается в интерфейсе.
                </Typography>
              </Stack>
            </Stack>
          </Paper>


          <Grid container spacing={4}>
            <Grid item xs={12}>
              <Paper
                elevation={6}
                sx={{
                  p: { xs: 3, md: 4 },
                  borderRadius: 4,
                  border: '1px solid',
                  borderColor: 'divider',
                  backgroundColor: (theme) => alpha(theme.palette.background.paper, 0.95)
                }}
              >
                <Stack spacing={3}>
                  <Box display="flex" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={2}>
                    <Box>
                      <Typography variant="h5" sx={{ fontWeight: 600 }}>
                        Поиск и загрузка производителей
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Запустите поиск по артикулу вручную или импортируйте таблицу, затем выгрузите результаты в нужном формате.
                      </Typography>
                    </Box>
                    <Chip label={`Текущий сервис: ${currentService}`} color="primary" variant="outlined" />
                  </Box>
                  <Grid container spacing={3} alignItems="stretch">
                    <Grid item xs={12} lg={7}>
                      <Paper
                        variant="outlined"
                        sx={{
                          p: { xs: 2.5, md: 3 },
                          height: '100%',
                          borderRadius: 3,
                          borderColor: 'divider',
                          backgroundColor: (theme) => alpha(theme.palette.background.default, 0.55)
                        }}
                      >
                        <Stack spacing={3} height="100%">
                          <Box>
                            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                              Поиск производителя по артикулу
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              Добавьте несколько артикулов, задайте предположительный бренд или алиас и запустите оркестратор поиска.
                            </Typography>
                          </Box>
                          <Stack spacing={2} flex={1}>
                            {items.map((item, index) => (
                              <Paper
                                key={index}
                                variant="outlined"
                                sx={{
                                  p: 2,
                                  borderRadius: 3,
                                  borderColor: 'divider',
                                  bgcolor: (theme) => alpha(theme.palette.background.paper, 0.5)
                                }}
                              >
                                <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="flex-start">
                                  <TextField
                                    label="Артикул"
                                    value={item.part_number}
                                    onChange={(event) => handleItemChange(index, 'part_number', event.target.value)}
                                    fullWidth
                                    required
                                  />
                                  <TextField
                                    label="Предполагаемый производитель или алиас"
                                    value={item.manufacturer_hint ?? ''}
                                    onChange={(event) => handleItemChange(index, 'manufacturer_hint', event.target.value)}
                                    fullWidth
                                  />
                                  <Button variant="text" color="error" onClick={() => removeRow(index)}>
                                    Удалить
                                  </Button>
                                </Stack>
                              </Paper>
                            ))}
                          </Stack>
                          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ xs: 'stretch', md: 'center' }}>
                            <Button
                              startIcon={<Search />}
                              variant="contained"
                              color="secondary"
                              onClick={submitSearch}
                              disabled={loading}
                            >
                              {loading ? 'Поиск…' : 'Запустить поиск'}
                            </Button>
                            <Button startIcon={<Bolt />} variant="text" onClick={submitManual}>
                              Ручное добавление
                            </Button>
                          </Stack>
                          <FormControlLabel
                            control={<Switch checked={debugMode} onChange={() => setDebugMode((prev) => !prev)} />}
                            label="Включить режим отладки"
                          />
                        </Stack>
                      </Paper>
                    </Grid>
                    <Grid item xs={12} lg={5}>
                      <Stack spacing={3} height="100%">
                        <Paper
                          elevation={0}
                          variant="outlined"
                          sx={{
                            p: { xs: 2.5, md: 3 },
                            borderRadius: 3,
                            borderColor: 'divider',
                            height: '100%'
                          }}
                        >
                          <Stack spacing={2}>
                            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                              Статус загрузки
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              Используйте панель действий над общей таблицей, чтобы выбрать файл, выгрузить шаблон или экспортировать результаты.
                            </Typography>
                            <Stack spacing={1}>
                              {uploadState.status === 'uploading' && <LinearProgress color="secondary" />}
                              <Chip
                                label={
                                  uploadState.message ??
                                  (uploadState.status === 'idle'
                                    ? 'Файл не выбран'
                                    : uploadState.status === 'done'
                                    ? 'Готово к поиску'
                                    : 'Ошибка загрузки')
                                }
                                color={
                                  uploadState.status === 'done'
                                    ? 'success'
                                    : uploadState.status === 'uploading'
                                    ? 'info'
                                    : uploadState.status === 'idle'
                                    ? 'default'
                                    : 'error'
                                }
                                variant="outlined"
                              />
                              <Typography variant="caption" color="text.secondary">
                                Загружено позиций: {uploadedItems.length}
                              </Typography>
                            </Stack>
                            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
                              <Button
                                startIcon={<Search />}
                                variant="contained"
                                color="secondary"
                                disabled={uploadState.status !== 'done' || !uploadedItems.length || loading}
                                onClick={runUploadedSearch}
                              >
                                Запуск поиска
                              </Button>
                              <Button
                                variant="text"
                                onClick={() => {
                                  setUploadedItems([])
                                  setUploadState({ status: 'idle' })
                                }}
                              >
                                Очистить загрузку
                              </Button>
                            </Stack>
                          </Stack>
                        </Paper>
                        {isAdmin && (
                          <Paper
                            elevation={0}
                            variant="outlined"
                            sx={{ p: { xs: 2.5, md: 3 }, borderRadius: 3, borderColor: 'divider' }}
                          >
                            <Stack spacing={2}>
                              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                                Управление доступом
                              </Typography>
                              <Typography variant="body2" color="text.secondary">
                                Измените логин и пароль пользовательской учётной записи для операторов сервиса.
                              </Typography>
                              <TextField
                                label="Новый логин"
                                value={credentialsForm.username}
                                onChange={(event) => setCredentialsForm((prev) => ({ ...prev, username: event.target.value }))}
                                fullWidth
                              />
                              <TextField
                                label="Новый пароль"
                                type="password"
                                value={credentialsForm.password}
                                onChange={(event) => setCredentialsForm((prev) => ({ ...prev, password: event.target.value }))}
                                fullWidth
                              />
                              <Stack direction="row" spacing={2}>
                                <Button variant="contained" onClick={handleCredentialsUpdate} disabled={credentialsLoading}>
                                  {credentialsLoading ? 'Сохранение…' : 'Сохранить'}
                                </Button>
                                <Button variant="text" onClick={() => setCredentialsForm({ username: '', password: '' })}>
                                  Очистить
                                </Button>
                              </Stack>
                              <Typography variant="caption" color="text.secondary">
                                Вход выполнен как администратор: {auth.username}
                              </Typography>
                            </Stack>
                          </Paper>
                        )}
                      </Stack>
                    </Grid>
                  </Grid>
                </Stack>
              </Paper>
            </Grid>
            <Grid item xs={12}>
              <Paper
                elevation={6}
                sx={{
                  p: { xs: 2.5, md: 3 },
                  borderRadius: 4,
                  border: '1px solid',
                  borderColor: 'divider',
                  backgroundColor: (theme) => alpha(theme.palette.background.paper, 0.92),
                  maxWidth: 1100,
                  mx: 'auto'
                }}
              >
                <Stack spacing={1.5}>
                  <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={2}>
                    <Typography variant="h6" sx={{ fontWeight: 700 }}>
                      Прогресс поиска
                    </Typography>
                    <Chip size="small" label={`Текущий сервис: ${currentService}`} color="primary" variant="outlined" />
                  </Box>
                  {loading && <LinearProgress color="secondary" />}
                  <Stepper
                    alternativeLabel
                    activeStep={activeStepperIndex}
                    nonLinear
                    sx={{
                      pt: 0.5,
                      '& .MuiStepIcon-root': { fontSize: '1.75rem' },
                      '& .MuiStepLabel-label': { fontSize: { xs: '0.9rem', sm: '1rem' } },
                      '& .MuiStepLabel-labelContainer .MuiTypography-caption': { fontSize: '0.75rem' }
                    }}
                  >
                    {stageProgress.map((stage) => (
                      <Step
                        key={stage.name}
                        completed={stage.state === 'done'}
                        active={stage.state === 'active'}
                      >
                        <StepLabel
                          error={stage.state === 'error'}
                          optional={
                            <Typography variant="caption" color="text.secondary">
                              {stage.message ?? progressStateLabel[stage.state]}
                            </Typography>
                          }
                        >
                          {stageLabels[stage.name]}
                        </StepLabel>
                      </Step>
                    ))}
                  </Stepper>
                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={0.75} flexWrap="wrap">
                    {stageProgress.map((stage) => (
                      <Chip
                        key={stage.name}
                        size="small"
                        label={`${stageLabels[stage.name]} · ${progressStateLabel[stage.state]}`}
                        color={progressStateColor[stage.state]}
                        variant={stage.state === 'active' ? 'filled' : 'outlined'}
                        title={stage.message ?? undefined}
                      />
                    ))}
                  </Stack>
                </Stack>
              </Paper>
            </Grid>
          </Grid>

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
                    Общая таблица поиска и производителей
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Все найденные строки, импорт и результаты поиска объединены в одной адаптивной таблице.
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1} alignItems="center">
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
              <Stack
                direction={{ xs: 'column', lg: 'row' }}
                spacing={1.5}
                alignItems={{ xs: 'stretch', lg: 'center' }}
                justifyContent="space-between"
              >
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap" useFlexGap>
                  <Button startIcon={<Upload />} variant="contained" onClick={() => uploadInputRef.current?.click()}>
                    Выбрать файл
                  </Button>
                  <input
                    ref={uploadInputRef}
                    hidden
                    type="file"
                    accept=".xls,.xlsx"
                    onChange={handleUpload}
                  />
                  <Button startIcon={<FileDownload />} variant="outlined" onClick={() => handleExport('excel')}>
                    Excel шаблон
                  </Button>
                  <Button startIcon={<FileDownload />} variant="outlined" onClick={() => handleExport('excel')}>
                    Выгрузить Excel
                  </Button>
                  <Button startIcon={<FileDownload />} variant="outlined" onClick={() => handleExport('pdf')}>
                    Выгрузить PDF
                  </Button>
                  <Button startIcon={<AddCircleOutline />} variant="text" onClick={addRow}>
                    Добавить строку
                  </Button>
                </Stack>
                <Stack
                  direction={{ xs: 'column', sm: 'row' }}
                  spacing={1}
                  alignItems={{ xs: 'stretch', sm: 'center' }}
                  justifyContent="flex-end"
                >
                  <Chip
                    label={
                      uploadState.message ??
                      (uploadState.status === 'idle'
                        ? 'Файл не выбран'
                        : uploadState.status === 'done'
                        ? 'Файл загружен'
                        : 'Ошибка загрузки')
                    }
                    color={
                      uploadState.status === 'done'
                        ? 'success'
                        : uploadState.status === 'uploading'
                        ? 'info'
                        : uploadState.status === 'idle'
                        ? 'default'
                        : 'error'
                    }
                    variant="outlined"
                  />
                  <Button
                    startIcon={<Search />}
                    variant="contained"
                    color="secondary"
                    disabled={uploadState.status !== 'done' || !uploadedItems.length || loading}
                    onClick={runUploadedSearch}
                  >
                    Запуск поиска
                  </Button>
                </Stack>
              </Stack>
              {filteredTableData.length === 0 ? (
                <Typography color="text.secondary">Пока нет данных. Выполните поиск или импорт.</Typography>
              ) : (
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                    <Chip label={`Всего записей: ${tableData.length}`} size="small" color="default" />
                    <Chip
                      label={`Отфильтровано: ${filteredTableData.length}`}
                      size="small"
                      color="secondary"
                      variant="outlined"
                    />
                    <Chip
                      label={`Выбрано: ${selectedRows.length}`}
                      size="small"
                      color={selectedRows.length ? 'success' : 'default'}
                      variant={selectedRows.length ? 'filled' : 'outlined'}
                    />
                  </Stack>

                  <TableContainer
                    component={Paper}
                    variant="outlined"
                    sx={{
                      maxHeight: { xs: '60vh', lg: '70vh' },
                      borderRadius: 3,
                      overflow: 'auto',
                      borderColor: 'divider',
                      width: '100%',
                      maxWidth: '100%',
                      backgroundImage:
                        'linear-gradient(90deg, rgba(255,255,255,0.02) 0%, rgba(255,255,255,0.06) 40%, rgba(255,255,255,0.02) 100%)'
                    }}
                  >
                    <Table
                      stickyHeader
                      size="small"
                      sx={{ minWidth: { xs: 980, md: 1180 }, tableLayout: 'fixed' }}
                    >
                      <TableHead>
                        <TableRow>
                          <TableCell padding="checkbox">
                            <Checkbox
                              color="primary"
                              indeterminate={
                                selectedRows.length > 0 && selectedRows.length < filteredTableData.length
                              }
                              checked={
                                filteredTableData.length > 0 &&
                                selectedRows.length === filteredTableData.length
                              }
                              onChange={(e) => handleSelectAllRows(e.target.checked)}
                              inputProps={{ 'aria-label': 'Выбрать все строки' }}
                            />
                          </TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }}>Артикул</TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }}>Производитель</TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }}>Alias</TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }}>
                            Заявленный производитель
                          </TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }}>Статус</TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }}>Достоверность</TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }}>Сервис</TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }}>Источник</TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }}>Стадии</TableCell>
                          <TableCell sx={{ fontWeight: 700, textTransform: 'uppercase' }} align="right">
                            Действия
                          </TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell padding="checkbox">
                            <Typography variant="caption" color="text.secondary">
                              Фильтр
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <TextField
                              fullWidth
                              size="small"
                              placeholder="Например, QE75..."
                              value={tableFilters.article}
                              onChange={(e) =>
                                setTableFilters((prev) => ({ ...prev, article: e.target.value }))
                              }
                              InputProps={{
                                startAdornment: (
                                  <InputAdornment position="start">
                                    <Search fontSize="small" />
                                  </InputAdornment>
                                )
                              }}
                            />
                          </TableCell>
                          <TableCell>
                            <TextField
                              fullWidth
                              size="small"
                              placeholder="Найденный производитель"
                              value={tableFilters.manufacturer}
                              onChange={(e) =>
                                setTableFilters((prev) => ({ ...prev, manufacturer: e.target.value }))
                              }
                              InputProps={{
                                startAdornment: (
                                  <InputAdornment position="start">
                                    <Factory fontSize="small" />
                                  </InputAdornment>
                                )
                              }}
                            />
                          </TableCell>
                          <TableCell>
                            <TextField
                              fullWidth
                              size="small"
                              placeholder="Alias"
                              value={tableFilters.alias}
                              onChange={(e) => setTableFilters((prev) => ({ ...prev, alias: e.target.value }))}
                              InputProps={{
                                startAdornment: (
                                  <InputAdornment position="start">
                                    <Bolt fontSize="small" />
                                  </InputAdornment>
                                )
                              }}
                            />
                          </TableCell>
                          <TableCell>
                            <TextField
                              fullWidth
                              size="small"
                              placeholder="Из заявки"
                              value={tableFilters.submitted}
                              onChange={(e) =>
                                setTableFilters((prev) => ({ ...prev, submitted: e.target.value }))
                              }
                              InputProps={{
                                startAdornment: (
                                  <InputAdornment position="start">
                                    <ListAlt fontSize="small" />
                                  </InputAdornment>
                                )
                              }}
                            />
                          </TableCell>
                          <TableCell>
                            <TextField
                              fullWidth
                              size="small"
                              select
                              label="Статус"
                              SelectProps={{ native: true }}
                              value={tableFilters.match}
                              onChange={(e) =>
                                setTableFilters((prev) => ({ ...prev, match: e.target.value as typeof prev.match }))
                              }
                            >
                              <option value="all">Все</option>
                              <option value="matched">Совпадает</option>
                              <option value="mismatch">Расхождение</option>
                              <option value="pending">Ожидает</option>
                              <option value="none">Нет данных</option>
                            </TextField>
                          </TableCell>
                          <TableCell>
                            <Typography variant="caption" color="text.secondary">
                              Поиск не требуется
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <TextField
                              fullWidth
                              size="small"
                              placeholder="Сервис"
                              value={tableFilters.service}
                              onChange={(e) =>
                                setTableFilters((prev) => ({ ...prev, service: e.target.value }))
                              }
                              InputProps={{
                                startAdornment: (
                                  <InputAdornment position="start">
                                    <Bolt fontSize="small" />
                                  </InputAdornment>
                                )
                              }}
                            />
                          </TableCell>
                          <TableCell>
                            <TextField
                              fullWidth
                              size="small"
                              placeholder="URL или источник"
                              value={tableFilters.source}
                              onChange={(e) =>
                                setTableFilters((prev) => ({ ...prev, source: e.target.value }))
                              }
                              InputProps={{
                                startAdornment: (
                                  <InputAdornment position="start">
                                    <FilterAlt fontSize="small" />
                                  </InputAdornment>
                                )
                              }}
                            />
                          </TableCell>
                          <TableCell>
                            <Typography variant="caption" color="text.secondary">
                              Стадии по результату
                            </Typography>
                          </TableCell>
                          <TableCell />
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {filteredTableData.map((row) => {
                          const isSelected = selectedRows.includes(row.id)
                          const confidenceValue =
                            row.matchConfidence
                              ? row.matchConfidence * 100
                              : row.confidence
                              ? row.confidence * 100
                              : null
                          return (
                            <Fragment key={row.key}>
                              <TableRow
                                hover
                                selected={isSelected}
                                sx={{
                                  '&:nth-of-type(even)': { backgroundColor: 'action.hover' },
                                  transition: 'background-color 150ms ease',
                                  backgroundColor: (theme) => {
                                    if (row.matchStatus === 'mismatch') {
                                      return alpha(theme.palette.error.light, 0.12)
                                    }
                                    if (row.matchStatus === 'pending') {
                                      return alpha(theme.palette.warning.light, 0.12)
                                    }
                                    return undefined
                                  }
                                }}
                              >
                                <TableCell padding="checkbox">
                                  <Checkbox
                                    color="primary"
                                    checked={isSelected}
                                    onChange={() => handleToggleRowSelection(row.id)}
                                    inputProps={{ 'aria-label': `Выбрать ${row.article}` }}
                                  />
                                </TableCell>
                                <TableCell sx={{ fontWeight: 700 }}>
                                  <Stack spacing={0.5}>
                                    <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                                      {row.article}
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                      Добавлено: {new Date(row.createdAt).toLocaleString()}
                                    </Typography>
                                  </Stack>
                                </TableCell>
                                <TableCell>
                                  <Stack spacing={0.5}>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                      {row.manufacturer}
                                    </Typography>
                                    <Chip
                                      size="small"
                                      label={row.manufacturer === '—' ? 'Не найдено' : 'Подтянуто'}
                                      color={row.manufacturer === '—' ? 'warning' : 'success'}
                                      variant={row.manufacturer === '—' ? 'outlined' : 'filled'}
                                    />
                                  </Stack>
                                </TableCell>
                                <TableCell>
                                  <Stack spacing={0.5}>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                      {row.alias}
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                      Из источников поиска
                                    </Typography>
                                  </Stack>
                                </TableCell>
                                <TableCell>
                                  <Stack spacing={0.5}>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                      {row.submitted}
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                      От пользователя
                                    </Typography>
                                  </Stack>
                                </TableCell>
                                <TableCell>{renderMatchChip(row.matchStatus, row.matchConfidence)}</TableCell>
                                <TableCell>
                                  {confidenceValue ? (
                                    <Stack spacing={0.5}>
                                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                        {confidenceValue.toFixed(1)}%
                                      </Typography>
                                      <LinearProgress
                                        variant="determinate"
                                        value={confidenceValue}
                                        color={
                                          row.matchStatus === 'mismatch'
                                            ? 'error'
                                            : row.matchStatus === 'pending'
                                            ? 'warning'
                                            : 'success'
                                        }
                                        sx={{ height: 8, borderRadius: 6 }}
                                      />
                                    </Stack>
                                  ) : (
                                    <Typography color="text.secondary">—</Typography>
                                  )}
                                </TableCell>
                                <TableCell>
                                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                    {row.service}
                                  </Typography>
                                </TableCell>
                                <TableCell sx={{ maxWidth: 220 }}>
                                  {row.source !== '—' ? (
                                    <Box
                                      component="a"
                                      href={row.source}
                                      target="_blank"
                                      rel="noreferrer"
                                      sx={{ color: 'secondary.main', wordBreak: 'break-all' }}
                                    >
                                      {row.source}
                                    </Box>
                                  ) : (
                                    <Typography color="text.secondary">—</Typography>
                                  )}
                                </TableCell>
                                <TableCell sx={{ maxWidth: 260 }}>
                                  {row.stageHistory && row.stageHistory.length > 0 ? (
                                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                                      {row.stageHistory.map((stage) => (
                                        <Chip
                                          key={`${row.key}-${stage.name}`}
                                          size="small"
                                          label={`${stage.name}: ${stageStatusDescription[stage.status]}`}
                                          color={stageStatusChipColor[stage.status]}
                                          title={stage.message ?? undefined}
                                        />
                                      ))}
                                    </Stack>
                                  ) : (
                                    <Typography color="text.secondary">—</Typography>
                                  )}
                                </TableCell>
                                <TableCell align="right">
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
                              {debugMode && row.debugLog ? (
                                <TableRow>
                                  <TableCell colSpan={11} sx={{ backgroundColor: 'action.hover' }}>
                                    <Typography variant="body2" color="text.secondary">
                                      {row.debugLog}
                                    </Typography>
                                  </TableCell>
                                </TableRow>
                              ) : null}
                            </Fragment>
                          )
                        })}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Stack>
              )}
            </Stack>
          </Paper>

          <Paper
            elevation={6}
            sx={{
              p: { xs: 3, md: 4 },
              borderRadius: 4,
              border: '1px solid',
              borderColor: 'divider'
            }}
          >
            <Stack spacing={3}>
              <Box display="flex" alignItems="center" justifyContent="space-between" gap={2} flexWrap="wrap">
                <Typography variant="h4" sx={{ fontWeight: 600 }}>
                  История поиска
                </Typography>
                <Stack direction="row" spacing={1} alignItems="center">
                  <TextField
                    size="small"
                    label="Фильтр"
                    value={historyFilter}
                    onChange={(e) => setHistoryFilter(e.target.value)}
                  />
                  <Button
                    variant="outlined"
                    startIcon={historyHidden ? <Visibility /> : <VisibilityOff />}
                    onClick={() => setHistoryHidden((prev) => !prev)}
                  >
                    {historyHidden ? 'Показать' : 'Скрыть'}
                  </Button>
                </Stack>
              </Box>
              {historyHidden ? (
                <Typography color="text.secondary">История скрыта.</Typography>
              ) : filteredHistory.length === 0 ? (
                <Typography color="text.secondary">История пуста.</Typography>
              ) : (
                <Grid container spacing={3}>
                  {filteredHistory.map((record) => (
                    <Grid item xs={12} md={6} key={record.id}>
                      <Paper variant="outlined" sx={{ p: 3, borderRadius: 3, borderColor: 'divider' }}>
                        <Stack spacing={1}>
                          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                            {record.part_number}
                          </Typography>
                          <Typography>Производитель: {record.manufacturer_name ?? '—'}</Typography>
                          <Typography>Алиас: {record.alias_used ?? '—'}</Typography>
                          <Typography>
                            Заявленный производитель: {record.submitted_manufacturer ?? '—'}
                          </Typography>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Typography>Сопоставление:</Typography>
                            {renderMatchChip(record.match_status as MatchStatus, record.match_confidence ?? null)}
                          </Stack>
                          <Typography>
                            Достоверность: {record.confidence ? `${(record.confidence * 100).toFixed(1)}%` : '—'}
                          </Typography>
                          {debugMode && record.debug_log && (
                            <Paper variant="outlined" sx={{ p: 2, mt: 1 }}>
                              <Typography variant="body2" color="secondary">
                                {record.debug_log}
                              </Typography>
                            </Paper>
                          )}
                        </Stack>
                      </Paper>
                    </Grid>
                  ))}
                </Grid>
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
                              <Stack spacing={0.5}>
                                <Typography variant="body2" noWrap title={entry.payload ?? undefined}>
                                  {entry.payload ?? '—'}
                                </Typography>
                                <Button
                                  size="small"
                                  variant="outlined"
                                  onClick={() => setSelectedLog(entry)}
                                  disabled={!entry.payload && !entry.query}
                                >
                                  Смотреть JSON
                                </Button>
                              </Stack>
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
      <Dialog
        open={Boolean(selectedLog)}
        onClose={() => setSelectedLog(null)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Детали поискового запроса</DialogTitle>
        <DialogContent dividers>
          {selectedLog && (
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} flexWrap="wrap">
                <Chip label={`Провайдер: ${selectedLog.provider}`} size="small" />
                <Chip
                  label={selectedLog.direction === 'request' ? 'Запрос' : 'Ответ'}
                  color={selectedLog.direction === 'request' ? 'default' : 'primary'}
                  size="small"
                  variant="outlined"
                />
                <Chip
                  label={`Статус: ${selectedLog.status_code ?? '—'}`}
                  size="small"
                  variant="outlined"
                />
                <Chip
                  label={new Date(selectedLog.created_at).toLocaleString()}
                  size="small"
                  variant="outlined"
                />
              </Stack>
              <Box>
                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
                  Строка запроса
                </Typography>
                <Box
                  component="pre"
                  sx={{
                    bgcolor: 'background.default',
                    p: 1.5,
                    borderRadius: 2,
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    border: '1px solid',
                    borderColor: 'divider'
                  }}
                >
                  {selectedLog.query}
                </Box>
              </Box>
              <Box>
                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
                  Payload / JSON
                </Typography>
                <Box
                  component="pre"
                  sx={{
                    bgcolor: 'background.default',
                    p: 1.5,
                    borderRadius: 2,
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    border: '1px solid',
                    borderColor: 'divider'
                  }}
                >
                  {prettifyPayload(selectedLog.payload)}
                </Box>
              </Box>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSelectedLog(null)}>Закрыть</Button>
        </DialogActions>
      </Dialog>
      <Snackbar
        open={Boolean(snackbar)}
        message={snackbar}
        autoHideDuration={4000}
        onClose={() => setSnackbar(null)}
      />
    </ThemeProvider>
  )
}
