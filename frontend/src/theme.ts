import { createTheme, ThemeOptions } from '@mui/material/styles'

export type ThemeMode = 'light' | 'dark' | 'holiday'

const lightThemeOptions: ThemeOptions = {
  palette: {
    mode: 'light',
    primary: {
      main: '#0b7285'
    },
    secondary: {
      main: '#845ef7'
    },
    background: {
      default: '#f8f9fa',
      paper: '#ffffff'
    }
  },
  typography: {
    fontFamily: '"Inter", "Segoe UI", sans-serif'
  }
}

const darkThemeOptions: ThemeOptions = {
  palette: {
    mode: 'dark',
    primary: {
      main: '#4dabf7'
    },
    secondary: {
      main: '#f783ac'
    },
    background: {
      default: 'rgba(7, 12, 19, 0.94)',
      paper: 'rgba(23, 32, 42, 0.9)'
    }
  },
  typography: {
    fontFamily: '"Inter", "Segoe UI", sans-serif'
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(255,255,255,0.08)'
        }
      }
    }
  }
}

const holidayThemeOptions: ThemeOptions = {
  palette: {
    mode: 'light',
    primary: {
      main: '#0fa3b1'
    },
    secondary: {
      main: '#ff6b9a'
    },
    background: {
      default: '#e7f1ff',
      paper: 'rgba(255, 255, 255, 0.82)'
    }
  },
  typography: {
    fontFamily: '"Inter", "Segoe UI", sans-serif'
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backdropFilter: 'blur(18px)',
          border: '1px solid rgba(15, 163, 177, 0.18)',
          boxShadow: '0 30px 80px rgba(15, 163, 177, 0.15)'
        }
      }
    },
    MuiButton: {
      styleOverrides: {
        contained: {
          background: 'linear-gradient(135deg, #0fa3b1, #8b5cf6)',
          color: '#ffffff'
        }
      }
    }
  }
}

export const buildTheme = (mode: ThemeMode) =>
  createTheme(
    mode === 'light' ? lightThemeOptions : mode === 'dark' ? darkThemeOptions : holidayThemeOptions
  )
