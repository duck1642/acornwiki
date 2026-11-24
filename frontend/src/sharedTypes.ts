// Types shared across multiple UI components. Component-local types stay in their own files.

export type ThemeId = 'warm-charcoal' | 'warm-paper'
export type SurfaceMode = 'framed' | 'seamless'
export type PageWidthPreset = '74ch' | '96ch' | '100%'

export type AppearanceFonts = { ui: string[]; body: string[]; monospace: string[] }
export type AppearanceFontSizes = { ui: number; body: number; monospace: number }
export type AppearanceFontWeights = { ui: number; body: number; monospace: number }

export type AppearancePatch = {
  theme?: ThemeId
  surface_mode?: SurfaceMode
  page_width?: PageWidthPreset
  fonts?: AppearanceFonts
  font_sizes?: AppearanceFontSizes
  font_weights?: AppearanceFontWeights
}

export type AppearanceView = {
  theme: ThemeId
  surface_mode: SurfaceMode
  page_width: string
  fonts: AppearanceFonts
  font_sizes: AppearanceFontSizes
  font_weights: AppearanceFontWeights
}

export type EditorPreferences = {
  autosave: boolean
  auto_reload: boolean
  reload_notice: boolean
}

export type EditorStatus = {
  dirty: boolean
  saving: boolean
  conflict: boolean
}

export type DocumentKind = 'markdown' | 'text'

export type EditorViewSettings = {
  lineNumbers: boolean
  wordWrap: boolean
}

export type LoadedFileSnapshot = {
  path: string
  content: string
  version: string
  has_bom?: boolean
}

export type TextFileReadResult =
  | {
    ok: true
    path: string
    content: string
    version: string
    has_bom: boolean
    size_bytes: number
  }
  | {
    ok: false
    path: string
    reason: 'too_large' | 'binary' | 'unsupported_encoding'
    size_bytes: number
    max_bytes: number
  }

export type FlatOutlineHeading = {
  id: string
  label: string
  level: number
}
