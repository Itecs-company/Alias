import { useEffect, useMemo, useState } from 'react'
import {
  AppBar,
  Box,
  Button,
  Container,
  CssBaseline,
  FormControlLabel,
  Grid,
  IconButton,
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
import { PartRead, PartRequestItem, SearchResult } from './types'

const emptyItem: PartRequestItem = { part_number: '', manufacturer_hint: '' }

export function App() {
  const [themeMode, setThemeMode] = useState<'light' | 'dark'>('light')
  const [debugMode, setDebugMode] = useState(false)
  const [items, setItems] = useState<PartRequestItem[]>([{ ...emptyItem }])
  const [results, setResults] = useState<SearchResult[]>([])
  const [history, setHistory] = useState<PartRead[]>([])
  const [snackbar, setSnackbar] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const theme = useMemo(() => buildTheme(themeMode), [themeMode])

  useEffect(() => {
    listParts().then(setHistory).catch(() => setSnackbar('Не удалось получить историю поиска'))
  }, [])

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
    setLoading(true)
    try {
      const filled = items.filter((item) => item.part_number.trim().length)
      if (!filled.length) {
        setSnackbar('Добавьте хотя бы один артикул для поиска')
        return
      }
      const response = await searchParts(filled, debugMode)
      setResults(response.results)
      setHistory(await listParts())
      if (!response.results.length) {
        setSnackbar('Производители не найдены')
      }
    } catch (error) {
      setSnackbar('Ошибка при выполнении поиска')
    } finally {
      setLoading(false)
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
                        {result.source_url && (
                          <Typography>
                            Источник: <a href={result.source_url} target="_blank" rel="noreferrer">{result.source_url}</a>
                          </Typography>
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
