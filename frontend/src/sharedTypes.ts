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

export type FlatOutlineHeading = {
  id: string
  label: string
  level: number
}
