import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AppBar,
  Box,
  Button,
  Chip,
  Container,
  CssBaseline,
  FormControlLabel,
  Grid,
  IconButton,
  LinearProgress,
  Paper,
  Snackbar,
  Stack,
  Switch,
  TextField,
  Toolbar,
  Tooltip,
  Typography
} from '@mui/material'
import { ThemeProvider } from '@mui/material/styles'
import { DarkMode, LightMode, BugReport, FileDownload, Upload } from '@mui/icons-material'

import { buildTheme } from './theme'
import {
  createPart,
  exportExcel,
  exportPdf,
  listParts,
  searchParts,
  uploadExcel
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

export function App() {
  const [themeMode, setThemeMode] = useState<'light' | 'dark'>('light')
  const [debugMode, setDebugMode] = useState(false)
  const [items, setItems] = useState<PartRequestItem[]>([{ ...emptyItem }])
  const [results, setResults] = useState<SearchResult[]>([])
  const [history, setHistory] = useState<PartRead[]>([])
  const [snackbar, setSnackbar] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [stageProgress, setStageProgress] = useState<StageProgressEntry[]>(() =>
    STAGE_SEQUENCE.map((name) => ({ name, state: 'idle' }))
  )
  const [currentService, setCurrentService] = useState('—')
  const progressTimerRef = useRef<number | null>(null)
  const progressIndexRef = useRef(0)

  const theme = useMemo(() => buildTheme(themeMode), [themeMode])

  useEffect(() => {
    listParts().then(setHistory).catch(() => setSnackbar('Не удалось получить историю поиска'))
  }, [])

  useEffect(() => {
    return () => {
      if (progressTimerRef.current) {
        window.clearInterval(progressTimerRef.current)
      }
    }
  }, [])

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
      setHistory(await listParts())
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
      setHistory(await listParts())
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
      setHistory(await listParts())
    } catch (error) {
      setSnackbar('Не удалось загрузить файл')
    }
  }

  const handleExport = async (type: 'pdf' | 'excel') => {
    try {
      const response = type === 'pdf' ? await exportPdf() : await exportExcel()
      window.open(response.url, '_blank')
    } catch (error) {
      setSnackbar('Не удалось выгрузить данные')
    }
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ minHeight: '100vh', bgcolor: 'background.default', color: 'text.primary' }}>
        <AppBar position="sticky" color="transparent" elevation={0} sx={{ backdropFilter: 'blur(10px)' }}>
          <Toolbar>
            <Typography variant="h6" sx={{ flexGrow: 1 }}>
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
          </Toolbar>
        </AppBar>

        <Container sx={{ py: 6 }}>
          <Grid container spacing={4}>
            <Grid item xs={12} md={7}>
              <Paper elevation={8} sx={{ p: 4 }}>
                <Typography variant="h5" gutterBottom>
                  Поиск производителя по артикулу
                </Typography>
                <Stack spacing={2}>
                  {items.map((item, index) => (
                    <Stack key={index} direction={{ xs: 'column', md: 'row' }} spacing={2}>
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
                      <Button variant="outlined" color="error" onClick={() => removeRow(index)}>
                        Удалить
                      </Button>
                    </Stack>
                  ))}
                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                    <Button variant="contained" onClick={addRow}>
                      Добавить строку
                    </Button>
                    <Button variant="contained" color="secondary" onClick={submitSearch} disabled={loading}>
                      {loading ? 'Поиск...' : 'Запустить поиск'}
                    </Button>
                    <Button variant="outlined" onClick={submitManual}>
                      Ручное добавление
                    </Button>
                  </Stack>
                  <FormControlLabel
                    control={<Switch checked={debugMode} onChange={() => setDebugMode((prev) => !prev)} />}
                    label="Включить режим отладки"
                  />
                  <Paper variant="outlined" sx={{ p: 2 }}>
                    <Stack spacing={1}>
                      <Typography variant="subtitle1">Прогресс поиска</Typography>
                      {loading && <LinearProgress color="secondary" />}
                      <Typography variant="body2" color="text.secondary">
                        Текущий сервис: {currentService}
                      </Typography>
                      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap">
                        {stageProgress.map((stage) => (
                          <Chip
                            key={stage.name}
                            label={`${stageLabels[stage.name]} · ${progressStateLabel[stage.state]}`}
                            color={progressStateColor[stage.state]}
                            variant={stage.state === 'active' ? 'filled' : 'outlined'}
                            title={stage.message ?? undefined}
                            sx={{ minWidth: { sm: 200 }, textAlign: 'left' }}
                          />
                        ))}
                      </Stack>
                    </Stack>
                  </Paper>
                </Stack>
              </Paper>
            </Grid>

            <Grid item xs={12} md={5}>
              <Stack spacing={4}>
                <Paper elevation={6} sx={{ p: 3 }}>
                  <Typography variant="h6" gutterBottom>
                    Загрузка из Excel
                  </Typography>
                  <Button component="label" startIcon={<Upload />} variant="contained">
                    Выбрать файл
                    <input hidden type="file" accept=".xls,.xlsx" onChange={handleUpload} />
                  </Button>
                </Paper>

                <Paper elevation={6} sx={{ p: 3 }}>
                  <Typography variant="h6" gutterBottom>
                    Выгрузка результатов
                  </Typography>
                  <Stack direction="row" spacing={2}>
                    <Button startIcon={<FileDownload />} variant="outlined" onClick={() => handleExport('excel')}>
                      Excel
                    </Button>
                    <Button startIcon={<FileDownload />} variant="contained" onClick={() => handleExport('pdf')}>
                      PDF
                    </Button>
                  </Stack>
                </Paper>
              </Stack>
            </Grid>
          </Grid>

          <Grid container spacing={4} sx={{ mt: 4 }}>
            <Grid item xs={12}>
              <Paper elevation={10} sx={{ p: 4 }}>
                <Typography variant="h5" gutterBottom>
                  Результаты поиска
                </Typography>
                {results.length === 0 ? (
                  <Typography color="text.secondary">Запустите поиск, чтобы увидеть результаты.</Typography>
                ) : (
                  <Stack spacing={2}>
                    {results.map((result, index) => (
                      <Box key={`${result.part_number}-${index}`} sx={{ p: 2, borderRadius: 2, bgcolor: 'background.paper' }}>
                        <Typography variant="subtitle1">{result.part_number}</Typography>
                        <Typography>Производитель: {result.manufacturer_name ?? '—'}</Typography>
                        <Typography>Алиас: {result.alias_used ?? '—'}</Typography>
                        <Typography>
                          Достоверность: {result.confidence ? `${(result.confidence * 100).toFixed(1)}%` : '—'}
                        </Typography>
                        {result.search_stage && (
                          <Typography variant="body2" color="text.secondary">
                            Финальный сервис: {stageLabels[result.search_stage as StageName] ?? result.search_stage}
                          </Typography>
                        )}
                        {result.source_url && (
                          <Typography>
                            Источник: <a href={result.source_url} target="_blank" rel="noreferrer">{result.source_url}</a>
                          </Typography>
                        )}
                        {result.stage_history && result.stage_history.length > 0 && (
                          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap" mt={1}>
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
                      </Box>
                    ))}
                  </Stack>
                )}
              </Paper>
            </Grid>

            <Grid item xs={12}>
              <Paper elevation={6} sx={{ p: 4 }}>
                <Typography variant="h5" gutterBottom>
                  История поиска
                </Typography>
                {history.length === 0 ? (
                  <Typography color="text.secondary">История пуста.</Typography>
                ) : (
                  <Stack spacing={2}>
                    {history.map((record) => (
                      <Box key={record.id} sx={{ p: 2, borderRadius: 2, bgcolor: 'background.paper' }}>
                        <Typography variant="subtitle1">{record.part_number}</Typography>
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
                      </Box>
                    ))}
                  </Stack>
                )}
              </Paper>
            </Grid>
          </Grid>
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
