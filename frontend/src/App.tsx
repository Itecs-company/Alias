import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AppBar,
  Avatar,
  Box,
  Button,
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
  Logout
} from '@mui/icons-material'

import { buildTheme } from './theme'
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
  fetchProfile
} from './api'
import { PartRead, PartRequestItem, SearchResult, StageStatus } from './types'

const emptyItem: PartRequestItem = { part_number: '', manufacturer_hint: '' }

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

type AuthState = { token: string; username: string; role: 'admin' | 'user' }
const AUTH_STORAGE_KEY = 'aliasfinder:auth'

export function App() {
  const [themeMode, setThemeMode] = useState<'light' | 'dark'>('light')
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
  const tableData = useMemo(() => {
    const sorted = [...history].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    )
    return sorted.map((record, index) => ({
      order: index + 1,
      article: record.part_number,
      manufacturerAlias:
        [record.manufacturer_name, record.alias_used].filter(Boolean).join(' / ') || '—'
    }))
  }, [history])
  const [snackbar, setSnackbar] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [stageProgress, setStageProgress] = useState<StageProgressEntry[]>(() =>
    STAGE_SEQUENCE.map((name) => ({ name, state: 'idle' }))
  )
  const [currentService, setCurrentService] = useState('—')
  const progressTimerRef = useRef<number | null>(null)
  const progressIndexRef = useRef(0)
  const refreshHistory = async () => {
    try {
      const data = await listParts()
      setHistory(data)
    } catch (error) {
      setSnackbar('Не удалось получить историю поиска')
    }
  }

  const theme = useMemo(() => buildTheme(themeMode), [themeMode])
  const isAdmin = auth?.role === 'admin'
  const gradientBackground = useMemo(
    () =>
      themeMode === 'light'
        ?
          'radial-gradient(circle at 20% 20%, rgba(13,114,133,0.08), transparent 40%), radial-gradient(circle at 80% 0%, rgba(132,94,247,0.12), transparent 45%), linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%)'
        :
          'radial-gradient(circle at 25% 25%, rgba(77,171,247,0.15), transparent 45%), radial-gradient(circle at 80% 0%, rgba(247,131,172,0.15), transparent 45%), linear-gradient(180deg, #05090f 0%, #0f1827 100%)',
    [themeMode]
  )
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

  const submitSearch = async () => {
    const filled = items.filter((item) => item.part_number.trim().length)
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
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const response = await uploadExcel(file, debugMode)
      setSnackbar(`Импортировано: ${response.imported}, пропущено: ${response.skipped}`)
      if (response.errors.length) {
        setSnackbar(`Ошибки: ${response.errors.join(', ')}`)
      }
      await refreshHistory()
    } catch (error) {
      setSnackbar('Не удалось загрузить файл')
    }
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
            backgroundImage: gradientBackground,
            display: 'flex',
            alignItems: 'center',
            py: 8
          }}
        >
          <Container maxWidth="sm">
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
              <Button variant="text" onClick={() => setThemeMode(themeMode === 'light' ? 'dark' : 'light')}>
                {themeMode === 'light' ? 'Темная тема' : 'Светлая тема'}
              </Button>
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
        backgroundImage: gradientBackground,
        color: 'text.primary'
      }}
    >
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
          <Tooltip title={themeMode === 'light' ? 'Темная тема' : 'Светлая тема'}>
            <IconButton color="inherit" onClick={() => setThemeMode(themeMode === 'light' ? 'dark' : 'light')}>
              {themeMode === 'light' ? <DarkMode /> : <LightMode />}
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

      <Container maxWidth="xl" sx={{ pt: { xs: 10, md: 14 }, pb: 8 }}>
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
            <Grid item xs={12} md={8}>
              <Stack spacing={4}>
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
                    <Box>
                      <Typography variant="h5" sx={{ fontWeight: 600 }}>
                        Поиск производителя по артикулу
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Добавьте несколько артикулов, задайте предположительный бренд или алиас и запустите оркестратор поиска.
                      </Typography>
                    </Box>
                    <Stack spacing={2}>
                      {items.map((item, index) => (
                        <Paper
                          key={index}
                          variant="outlined"
                          sx={{
                            p: 2,
                            borderRadius: 3,
                            borderColor: 'divider',
                            bgcolor: (theme) => alpha(theme.palette.background.default, 0.4)
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
                    <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                      <Button startIcon={<AddCircleOutline />} variant="outlined" onClick={addRow}>
                        Добавить строку
                      </Button>
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
                  <Stack spacing={2}>
                    <Box display="flex" alignItems="center" justifyContent="space-between">
                      <Typography variant="h6" sx={{ fontWeight: 600 }}>
                        Прогресс поиска
                      </Typography>
                      <Chip label={`Текущий сервис: ${currentService}`} color="primary" variant="outlined" />
                    </Box>
                    {loading && <LinearProgress color="secondary" />}
                    <Stepper alternativeLabel activeStep={activeStepperIndex} nonLinear sx={{ pt: 1 }}>
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
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap">
                      {stageProgress.map((stage) => (
                        <Chip
                          key={stage.name}
                          label={`${stageLabels[stage.name]} · ${progressStateLabel[stage.state]}`}
                          color={progressStateColor[stage.state]}
                          variant={stage.state === 'active' ? 'filled' : 'outlined'}
                          title={stage.message ?? undefined}
                        />
                      ))}
                    </Stack>
                  </Stack>
                </Paper>
              </Stack>
            </Grid>

            <Grid item xs={12} md={4}>
              <Stack spacing={4}>
                <Paper
                  elevation={6}
                  sx={{
                    p: { xs: 3, md: 4 },
                    borderRadius: 4,
                    border: '1px solid',
                    borderColor: 'divider'
                  }}
                >
                  <Stack spacing={2}>
                    <Typography variant="h6" sx={{ fontWeight: 600 }}>
                      Загрузка из Excel
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Шаблон таблицы: обязательные столбцы «Article» и «Manufacturer/Alias», «№» можно опустить. Эти же поля
                      используются при выгрузке.
                    </Typography>
                    <Button component="label" startIcon={<Upload />} variant="contained">
                      Выбрать файл
                      <input hidden type="file" accept=".xls,.xlsx" onChange={handleUpload} />
                    </Button>
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
                  <Stack spacing={2}>
                    <Typography variant="h6" sx={{ fontWeight: 600 }}>
                      Выгрузка результатов
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Сформируйте свежие отчёты PDF/Excel прямо из текущей базы.
                    </Typography>
                    <Stack direction="row" spacing={2}>
                      <Button startIcon={<FileDownload />} variant="outlined" onClick={() => handleExport('excel')}>
                        Excel
                      </Button>
                      <Button startIcon={<FileDownload />} variant="contained" onClick={() => handleExport('pdf')}>
                        PDF
                      </Button>
                    </Stack>
                  </Stack>
                </Paper>
                {isAdmin && (
                  <Paper
                    elevation={6}
                    sx={{
                      p: { xs: 3, md: 4 },
                      borderRadius: 4,
                      border: '1px solid',
                      borderColor: 'divider'
                    }}
                  >
                    <Stack spacing={2}>
                      <Typography variant="h6" sx={{ fontWeight: 600 }}>
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
                <Typography variant="h4" sx={{ fontWeight: 600 }}>
                  Результаты поиска
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Источник → производитель → достоверность. Все стадии доступны в один клик.
                </Typography>
              </Box>
              {results.length === 0 ? (
                <Typography color="text.secondary">Запустите поиск, чтобы увидеть результаты.</Typography>
              ) : (
                <Grid container spacing={3}>
                  {results.map((result, index) => (
                    <Grid item xs={12} md={6} key={`${result.part_number}-${index}`}>
                      <Paper
                        variant="outlined"
                        sx={{
                          p: 3,
                          borderRadius: 3,
                          borderColor: 'divider',
                          backgroundImage: (theme) =>
                            theme.palette.mode === 'light'
                              ? 'linear-gradient(135deg, rgba(255,255,255,0.95), rgba(243,246,255,0.9))'
                              : 'linear-gradient(135deg, rgba(20,26,35,0.95), rgba(10,16,25,0.9))'
                        }}
                      >
                        <Stack spacing={1.5}>
                          <Stack direction="row" justifyContent="space-between" alignItems="center">
                            <Box>
                              <Typography variant="h6">{result.part_number}</Typography>
                              <Typography variant="body2" color="text.secondary">
                                {result.search_stage
                                  ? `Финальный сервис: ${
                                      stageLabels[result.search_stage as StageName] ?? result.search_stage
                                    }`
                                  : 'Сервис не определён'}
                              </Typography>
                            </Box>
                            <Chip
                              label={
                                result.confidence
                                  ? `${(result.confidence * 100).toFixed(1)}%`
                                  : '—'
                              }
                              color="secondary"
                              variant="outlined"
                            />
                          </Stack>
                          <Divider light />
                          <Typography>
                            Производитель: <strong>{result.manufacturer_name ?? '—'}</strong>
                          </Typography>
                          <Typography>Алиас: {result.alias_used ?? '—'}</Typography>
                          {result.source_url && (
                            <Typography>
                              Источник{' '}
                              <Box component="a" href={result.source_url} target="_blank" rel="noreferrer" sx={{ color: 'secondary.main' }}>
                                {result.source_url}
                              </Box>
                            </Typography>
                          )}
                          {result.stage_history && result.stage_history.length > 0 && (
                            <Stack direction="row" spacing={1} flexWrap="wrap" mt={1}>
                              {result.stage_history.map((stage) => (
                                <Chip
                                  key={`${result.part_number}-${stage.name}`}
                                  size="small"
                                  label={`${stage.name}: ${stageStatusDescription[stage.status]}`}
                                  color={stageStatusChipColor[stage.status]}
                                  title={stage.message ?? undefined}
                                />
                              ))}
                            </Stack>
                          )}
                          {debugMode && result.debug_log && (
                            <Paper variant="outlined" sx={{ p: 2, mt: 1 }}>
                              <Typography variant="body2" color="secondary">
                                {result.debug_log}
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
                <Typography variant="h4" sx={{ fontWeight: 600 }}>
                  Таблица производителей
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Каждое найденное соответствие мгновенно попадает в таблицу и базу данных.
                </Typography>
              </Box>
              {tableData.length === 0 ? (
                <Typography color="text.secondary">Пока нет данных. Выполните поиск или импорт.</Typography>
              ) : (
                <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 420, borderRadius: 3 }}>
                  <Table stickyHeader size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ fontWeight: 600, width: 80 }}>№</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Article</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Manufacturer/Alias</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {tableData.map((row) => (
                        <TableRow key={`${row.order}-${row.article}`} hover>
                          <TableCell width={80}>{row.order}</TableCell>
                          <TableCell>{row.article}</TableCell>
                          <TableCell>{row.manufacturerAlias}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
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
              <Typography variant="h4" sx={{ fontWeight: 600 }}>
                История поиска
              </Typography>
              {history.length === 0 ? (
                <Typography color="text.secondary">История пуста.</Typography>
              ) : (
                <Grid container spacing={3}>
                  {history.map((record) => (
                    <Grid item xs={12} md={6} key={record.id}>
                      <Paper variant="outlined" sx={{ p: 3, borderRadius: 3, borderColor: 'divider' }}>
                        <Stack spacing={1}>
                          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                            {record.part_number}
                          </Typography>
                          <Typography>Производитель: {record.manufacturer_name ?? '—'}</Typography>
                          <Typography>Алиас: {record.alias_used ?? '—'}</Typography>
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
