import { createTheme, ThemeOptions } from '@mui/material/styles'

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

export const buildTheme = (mode: 'light' | 'dark') =>
  createTheme(mode === 'light' ? lightThemeOptions : darkThemeOptions)
