<script lang="ts">
  import Icon from './Icon.svelte'
  import PopupMenu from './PopupMenu.svelte'
  import type {
    AppearanceFonts,
    AppearanceFontSizes,
    AppearancePatch,
    AppearanceView,
    EditorPreferences,
    PageWidthPreset,
    SurfaceMode,
    ThemeId,
  } from './sharedTypes'

  type Scope = 'workspace' | 'application'

  let {
    active,
    workspaceId,
    appearance,
    appearanceSaving,
    pageWidthPresets,
    editorPreferences,
    editorPreferencesLoaded,
    editorPreferenceSaving,
    settingsMessage,
    creationFolderInput = $bindable(),
    folderSettingsMessage,
    blockedExtensions,
    blockedMessage,
    blockedSaving,
    ready,
    connectionMessage,
    onSetAppearance,
    onSetEditorPreference,
    onSaveCreationFolder,
    onUpdateBlockedExtensions,
    onPing,
  }: {
    active: boolean
    workspaceId: string | null
    appearance: AppearanceView
    appearanceSaving: boolean
    pageWidthPresets: { value: PageWidthPreset; label: string; title: string }[]
    editorPreferences: EditorPreferences
    editorPreferencesLoaded: boolean
    editorPreferenceSaving: Partial<Record<keyof EditorPreferences, boolean>>
    settingsMessage: string
    creationFolderInput: string
    folderSettingsMessage: string
    blockedExtensions: string
    blockedMessage: string
    blockedSaving: boolean
    ready: boolean
    connectionMessage: string
    onSetAppearance: (patch: AppearancePatch) => void | Promise<void>
    onSetEditorPreference: (key: keyof EditorPreferences, input: HTMLInputElement) => void | Promise<void>
    onSaveCreationFolder: () => void | Promise<void>
    onUpdateBlockedExtensions: (transform: (current: string[]) => string[]) => Promise<boolean>
    onPing: () => void | Promise<void>
  } = $props()

  const themeOptions: { value: ThemeId; label: string }[] = [
    { value: 'warm-charcoal', label: 'Warm Charcoal' },
    { value: 'warm-paper', label: 'Warm Paper' },
  ]
  const surfaceOptions: { value: SurfaceMode; label: string }[] = [
    { value: 'framed', label: 'Framed' },
    { value: 'seamless', label: 'Seamless' },
  ]
  type FontPreset = { id: string; label: string; stack: string[]; matches?: string[] }
  const uiFontPresets: FontPreset[] = [
    { id: 'system', label: 'System UI', stack: ['Segoe UI', 'system-ui', '-apple-system', 'sans-serif'], matches: ['system-ui', 'Segoe UI'] },
    { id: 'inter', label: 'Inter', stack: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'], matches: ['Inter'] },
    { id: 'humanist', label: 'Humanist Sans', stack: ['Calibri', 'Trebuchet MS', 'Segoe UI', 'sans-serif'], matches: ['Calibri'] },
  ]
  const bodyFontPresets: FontPreset[] = [
    { id: 'palatino', label: 'Palatino (Serif)', stack: ['Palatino Linotype', 'Book Antiqua', 'Georgia', 'serif'], matches: ['serif', 'Palatino Linotype'] },
    { id: 'georgia', label: 'Georgia (Serif)', stack: ['Georgia', 'Cambria', 'Times New Roman', 'serif'], matches: ['Georgia'] },
    { id: 'sans', label: 'System Sans', stack: ['Segoe UI', 'system-ui', '-apple-system', 'sans-serif'], matches: ['Segoe UI', 'system-ui'] },
    { id: 'mono', label: 'Monospace', stack: ['Cascadia Code', 'Consolas', 'Courier New', 'monospace'], matches: ['Cascadia Code', 'monospace'] },
  ]
  const monoFontPresets: FontPreset[] = [
    { id: 'cascadia', label: 'Cascadia / Consolas', stack: ['Cascadia Code', 'Consolas', 'Courier New', 'monospace'], matches: ['monospace', 'Cascadia Code', 'Consolas'] },
    { id: 'jetbrains', label: 'JetBrains / Fira Mono', stack: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'monospace'], matches: ['JetBrains Mono', 'Fira Code'] },
    { id: 'courier', label: 'Courier', stack: ['Courier New', 'Consolas', 'monospace'], matches: ['Courier New'] },
  ]
  const colorTokens: { id: string; label: string; cssVar: string; role: string }[] = [
    { id: 'bg-app', label: 'Canvas', cssVar: '--bg-app', role: 'Outer backdrop' },
    { id: 'bg-panel', label: 'Panels', cssVar: '--bg-panel', role: 'Sidebars & bars' },
    { id: 'bg-paper', label: 'Paper', cssVar: '--bg-paper', role: 'Note surface' },
    { id: 'ink', label: 'Text', cssVar: '--ink', role: 'Primary ink' },
    { id: 'accent', label: 'Accent', cssVar: '--accent', role: 'Active & focus' },
    { id: 'link', label: 'Links', cssVar: '--link', role: 'Note & web links' },
    { id: 'warn', label: 'Warning', cssVar: '--warn', role: 'Unsaved & folders' },
    { id: 'border', label: 'Borders', cssVar: '--border', role: 'Dividers' },
  ]
  const markdownColorTokens: { id: string; label: string; cssVar: string; previewVar: string; role: string }[] = [
    { id: 'md-h1', label: 'Heading 1', cssVar: '--md-h1', previewVar: '--ink', role: '# Document title' },
    { id: 'md-h2', label: 'Heading 2', cssVar: '--md-h2', previewVar: '--ink', role: '## Section heading' },
    { id: 'md-h3', label: 'Heading 3', cssVar: '--md-h3', previewVar: '--ink-muted', role: '### Subsection heading' },
    { id: 'md-h4', label: 'Heading 4-6', cssVar: '--md-h4', previewVar: '--ink-muted', role: '#### Minor headings' },
    { id: 'md-emphasis', label: 'Bold & italic', cssVar: '--md-strong', previewVar: '--ink', role: '**Strong** and *emphasis*' },
    { id: 'md-code', label: 'Inline code', cssVar: '--md-code', previewVar: '--accent', role: '`monospace` spans' },
    { id: 'md-code-bg', label: 'Code block', cssVar: '--md-code-bg', previewVar: '--bg-panel', role: 'Fenced code surface' },
    { id: 'md-quote', label: 'Blockquote', cssVar: '--md-quote', previewVar: '--warn', role: '> Quote bar and text' },
    { id: 'md-link', label: 'Markdown links', cssVar: '--md-link', previewVar: '--link', role: '[Internal & web links]' },
    { id: 'md-syntax', label: 'Syntax markers', cssVar: '--md-syntax', previewVar: '--ink-faint', role: '#, *, > and fence markers' },
  ]

  function activeFontPreset(presets: FontPreset[], stack: string[]): FontPreset | undefined {
    const primary = stack[0] ?? ''
    return presets.find((preset) => preset.stack[0] === primary || preset.matches?.includes(primary))
  }

  function fontDisplayLabel(presets: FontPreset[], stack: string[]): string {
    return activeFontPreset(presets, stack)?.label ?? stack[0] ?? 'Default'
  }

  function updateFont(kind: keyof AppearanceFonts, stack: string[]) {
    void onSetAppearance({ fonts: { ...appearance.fonts, [kind]: [...stack] } })
  }

  function stepFontSize(kind: keyof AppearanceFontSizes, delta: number, min: number, max: number) {
    const next = Math.min(max, Math.max(min, appearance.font_sizes[kind] + delta))
    if (next === appearance.font_sizes[kind]) return
    void onSetAppearance({ font_sizes: { ...appearance.font_sizes, [kind]: next } })
  }

  let scope = $state<Scope>('workspace')
  let query = $state('')
  let newExtension = $state('')
  let themeMenuOpen = $state(false)
  let surfaceMenuOpen = $state(false)
  let widthMenuOpen = $state(false)
  let uiFontMenuOpen = $state(false)
  let bodyFontMenuOpen = $state(false)
  let monoFontMenuOpen = $state(false)
  let themeColorsOpen = $state(false)
  let appearanceDisabled = $derived(!workspaceId || appearanceSaving)
  let currentThemeLabel = $derived(themeOptions.find((option) => option.value === appearance.theme)?.label ?? appearance.theme)
  let currentSurfaceLabel = $derived(surfaceOptions.find((option) => option.value === appearance.surface_mode)?.label ?? appearance.surface_mode)
  let currentWidthLabel = $derived(pageWidthPresets.find((preset) => preset.value === appearance.page_width)?.label ?? appearance.page_width)
  let blockedList = $derived(blockedExtensions.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean))
  let normalizedQuery = $derived(query.trim().toLowerCase())
  let searching = $derived(normalizedQuery.length > 0)

  async function addBlockedExtension() {
    if (!editorPreferencesLoaded || blockedSaving) return
    const submitted = newExtension
    const raw = submitted.split(/[\s,]+/).map((item) => item.trim().toLowerCase()).filter(Boolean)
    if (!raw.length) return
    const normalized = raw.map((token) => (token.startsWith('.') ? token : `.${token}`))
    const saved = await onUpdateBlockedExtensions((current) => {
      const existing = new Set(current.map((item) => item.toLowerCase()))
      const additions = normalized.filter((item) => {
        if (existing.has(item)) return false
        existing.add(item)
        return true
      })
      return additions.length ? [...current, ...additions] : current
    })
    if (saved && newExtension === submitted) newExtension = ''
  }

  async function removeBlockedExtension(target: string) {
    if (!editorPreferencesLoaded || blockedSaving) return
    await onUpdateBlockedExtensions((current) => current.filter((item) => item !== target))
  }

  function matches(...terms: string[]): boolean {
    if (!normalizedQuery) return true
    return terms.some((term) => term.toLowerCase().includes(normalizedQuery))
  }

  let showTheme = $derived(matches('theme', 'warm charcoal', 'warm paper', 'color', 'palette', 'appearance'))
  let showSurface = $derived(matches('document surface', 'framed', 'seamless', 'appearance', 'canvas', 'card'))
  let showPageWidth = $derived(matches('page width', 'readable', 'wide', 'full', 'line width', 'appearance'))
  let showAppearanceGroup = $derived((searching || scope === 'workspace') && (showTheme || showSurface || showPageWidth))

  let showNewItemsFolder = $derived(matches('new items folder', 'workspace files', 'default folder', 'create', 'root'))
  let showWorkspaceFilesGroup = $derived((searching || scope === 'workspace') && showNewItemsFolder)

  let showUiFont = $derived(matches('interface font', 'ui font', 'typography', 'font', 'size', 'sans'))
  let showBodyFont = $derived(matches('reading font', 'body font', 'typography', 'font', 'size', 'serif', 'palatino', 'georgia'))
  let showMonoFont = $derived(matches('editor font', 'code font', 'monospace', 'typography', 'font', 'size', 'cascadia', 'jetbrains'))
  let showTypographyGroup = $derived((searching || scope === 'workspace') && (showUiFont || showBodyFont || showMonoFont))

  let showThemeColors = $derived(matches('theme colors', 'color overrides', 'colors', 'accent', 'paper', 'canvas', 'palette', 'swatch', 'markdown', 'heading', 'header', 'blockquote', 'code'))
  let showThemeColorsGroup = $derived((searching || scope === 'workspace') && showThemeColors)

  let showExclusions = $derived(matches('exclusions', 'excluded files', 'excluded folders', 'hide', 'ignore', 'index'))
  let showExclusionsGroup = $derived((searching || scope === 'workspace') && showExclusions)

  let showAutosave = $derived(matches('autosave', 'save changes automatically', 'editor'))
  let showAutoReload = $derived(matches('auto-reload', 'reload notes', 'disk version', 'editor'))
  let showReloadNotice = $derived(matches('reload notice', 'notice', 'externally', 'editor'))
  let showEditorGroup = $derived((searching || scope === 'application') && (showAutosave || showAutoReload || showReloadNotice))

  let showBlocked = $derived(matches('blocked extensions', 'file access', 'extensions', 'exe', 'bat'))
  let showFileAccessGroup = $derived((searching || scope === 'application') && showBlocked)

  let showConnection = $derived(matches('connection', 'backend', 'ping', 'status'))
  let showConnectionGroup = $derived((searching || scope === 'application') && showConnection)

  let hasAnyMatch = $derived(
    showAppearanceGroup || showThemeColorsGroup || showTypographyGroup || showWorkspaceFilesGroup || showExclusionsGroup || showEditorGroup || showFileAccessGroup || showConnectionGroup,
  )
</script>

<section class="settings-tab" class:inactive={!active} aria-label="Settings" aria-hidden={!active} inert={!active}>
  <div class="settings-tab-scroll">
    <div class="settings-container">
      <header class="settings-header">
        <div class="settings-header-top">
          <div>
            <h1>Settings</h1>
            <p class="settings-subtitle">Configure workspace appearance and application behavior.</p>
          </div>
          <input
            class="settings-search"
            type="search"
            aria-label="Filter settings"
            placeholder="Filter settings..."
            bind:value={query}
          />
        </div>
        <div class="settings-scope-tabs" role="tablist" aria-label="Settings scope">
          <button
            class="settings-scope-tab"
            class:active={!searching && scope === 'workspace'}
            role="tab"
            aria-selected={!searching && scope === 'workspace'}
            onclick={() => { scope = 'workspace'; query = '' }}
          >
            <span>Workspace</span>
          </button>
          <button
            class="settings-scope-tab"
            class:active={!searching && scope === 'application'}
            role="tab"
            aria-selected={!searching && scope === 'application'}
            onclick={() => { scope = 'application'; query = '' }}
          >
            <span>Application</span>
          </button>
        </div>
      </header>

      {#if settingsMessage}<p class="settings-banner settings-banner-alert" role="alert">{settingsMessage}</p>{/if}
      {#if !searching && scope === 'workspace' && !workspaceId}
        <p class="settings-banner">Open a workspace to customize workspace appearance and file settings.</p>
      {/if}

      {#if !hasAnyMatch}
        <p class="settings-empty">No settings match "{query.trim()}".</p>
      {/if}

      {#if showAppearanceGroup}
        <section class="settings-group">
          <div class="settings-group-header">
            <h2>Appearance</h2>
            {#if searching}<span class="settings-group-scope">Workspace</span>{/if}
          </div>
          <div class="settings-card">
            {#if showTheme}
              <div class="setting-row">
                <div class="setting-info">
                  <span class="setting-label">Theme</span>
                  <span class="setting-desc">Color palette used across panels and editor.</span>
                </div>
                <div class="setting-control">
                  <details class="setting-select" bind:open={themeMenuOpen}>
                    <summary aria-label="Theme" aria-disabled={appearanceDisabled} onclick={(event) => { if (appearanceDisabled) event.preventDefault() }}>
                      <span>{currentThemeLabel}</span>
                      <Icon name="chevron-down" size={14} />
                    </summary>
                    <PopupMenu class="setting-select-menu" label="Theme">
                      {#each themeOptions as option (option.value)}
                        <button
                          class="popup-menu-item"
                          aria-pressed={appearance.theme === option.value}
                          disabled={appearanceDisabled}
                          onclick={() => { themeMenuOpen = false; void onSetAppearance({ theme: option.value }) }}
                        >{option.label}{#if appearance.theme === option.value}<span class="popup-menu-mark"><Icon name="check" size={14} /></span>{/if}</button>
                      {/each}
                    </PopupMenu>
                  </details>
                </div>
              </div>
            {/if}
            {#if showSurface}
              <div class="setting-row">
                <div class="setting-info">
                  <span class="setting-label">Default document surface</span>
                  <span class="setting-desc">Framed paper card on canvas or seamless full-width surface.</span>
                </div>
                <div class="setting-control">
                  <details class="setting-select" bind:open={surfaceMenuOpen}>
                    <summary aria-label="Default document surface" aria-disabled={appearanceDisabled} onclick={(event) => { if (appearanceDisabled) event.preventDefault() }}>
                      <span>{currentSurfaceLabel}</span>
                      <Icon name="chevron-down" size={14} />
                    </summary>
                    <PopupMenu class="setting-select-menu" label="Default document surface">
                      {#each surfaceOptions as option (option.value)}
                        <button
                          class="popup-menu-item"
                          aria-pressed={appearance.surface_mode === option.value}
                          disabled={appearanceDisabled}
                          onclick={() => { surfaceMenuOpen = false; void onSetAppearance({ surface_mode: option.value }) }}
                        >{option.label}{#if appearance.surface_mode === option.value}<span class="popup-menu-mark"><Icon name="check" size={14} /></span>{/if}</button>
                      {/each}
                    </PopupMenu>
                  </details>
                </div>
              </div>
            {/if}
            {#if showPageWidth}
              <div class="setting-row">
                <div class="setting-info">
                  <span class="setting-label">Default page width</span>
                  <span class="setting-desc">Maximum line width for reading and editing notes.</span>
                </div>
                <div class="setting-control">
                  <details class="setting-select" bind:open={widthMenuOpen}>
                    <summary aria-label="Default page width" aria-disabled={appearanceDisabled} onclick={(event) => { if (appearanceDisabled) event.preventDefault() }}>
                      <span>{currentWidthLabel}</span>
                      <Icon name="chevron-down" size={14} />
                    </summary>
                    <PopupMenu class="setting-select-menu" label="Default page width">
                      {#each pageWidthPresets as preset (preset.value)}
                        <button
                          class="popup-menu-item"
                          aria-pressed={appearance.page_width === preset.value}
                          disabled={appearanceDisabled}
                          title={preset.title}
                          onclick={() => { widthMenuOpen = false; void onSetAppearance({ page_width: preset.value }) }}
                        >{preset.label}{#if appearance.page_width === preset.value}<span class="popup-menu-mark"><Icon name="check" size={14} /></span>{/if}</button>
                      {/each}
                    </PopupMenu>
                  </details>
                </div>
              </div>
            {/if}
          </div>
        </section>
      {/if}

      {#if showTypographyGroup}
        <section class="settings-group">
          <div class="settings-group-header">
            <h2>Typography</h2>
            {#if searching}<span class="settings-group-scope">Workspace</span>{/if}
          </div>
          <div class="settings-card">
            {#if showUiFont}
              <div class="setting-row">
                <div class="setting-info">
                  <span class="setting-label">Interface font</span>
                  <span class="setting-desc">Font family and size for menus, sidebars, and controls.</span>
                </div>
                <div class="setting-control">
                  <details class="setting-select" bind:open={uiFontMenuOpen}>
                    <summary aria-label="Interface font" aria-disabled={appearanceDisabled} onclick={(event) => { if (appearanceDisabled) event.preventDefault() }}>
                      <span>{fontDisplayLabel(uiFontPresets, appearance.fonts.ui)}</span>
                      <Icon name="chevron-down" size={14} />
                    </summary>
                    <PopupMenu class="setting-select-menu" label="Interface font">
                      {#each uiFontPresets as preset (preset.id)}
                        {@const selected = activeFontPreset(uiFontPresets, appearance.fonts.ui)?.id === preset.id}
                        <button class="popup-menu-item" aria-pressed={selected} disabled={appearanceDisabled} onclick={() => { uiFontMenuOpen = false; updateFont('ui', preset.stack) }}>
                          {preset.label}{#if selected}<span class="popup-menu-mark"><Icon name="check" size={14} /></span>{/if}
                        </button>
                      {/each}
                    </PopupMenu>
                  </details>
                  <div class="font-size-stepper" role="group" aria-label="Interface font size">
                    <button type="button" aria-label="Decrease interface font size" disabled={appearanceDisabled || appearance.font_sizes.ui <= 11} onclick={() => stepFontSize('ui', -1, 11, 18)}>−</button>
                    <span>{appearance.font_sizes.ui}px</span>
                    <button type="button" aria-label="Increase interface font size" disabled={appearanceDisabled || appearance.font_sizes.ui >= 18} onclick={() => stepFontSize('ui', 1, 11, 18)}>+</button>
                  </div>
                </div>
              </div>
            {/if}
            {#if showBodyFont}
              <div class="setting-row">
                <div class="setting-info">
                  <span class="setting-label">Reading font</span>
                  <span class="setting-desc">Font family and size for notes in Read mode.</span>
                </div>
                <div class="setting-control">
                  <details class="setting-select" bind:open={bodyFontMenuOpen}>
                    <summary aria-label="Reading font" aria-disabled={appearanceDisabled} onclick={(event) => { if (appearanceDisabled) event.preventDefault() }}>
                      <span>{fontDisplayLabel(bodyFontPresets, appearance.fonts.body)}</span>
                      <Icon name="chevron-down" size={14} />
                    </summary>
                    <PopupMenu class="setting-select-menu" label="Reading font">
                      {#each bodyFontPresets as preset (preset.id)}
                        {@const selected = activeFontPreset(bodyFontPresets, appearance.fonts.body)?.id === preset.id}
                        <button class="popup-menu-item" aria-pressed={selected} disabled={appearanceDisabled} onclick={() => { bodyFontMenuOpen = false; updateFont('body', preset.stack) }}>
                          {preset.label}{#if selected}<span class="popup-menu-mark"><Icon name="check" size={14} /></span>{/if}
                        </button>
                      {/each}
                    </PopupMenu>
                  </details>
                  <div class="font-size-stepper" role="group" aria-label="Reading font size">
                    <button type="button" aria-label="Decrease reading font size" disabled={appearanceDisabled || appearance.font_sizes.body <= 13} onclick={() => stepFontSize('body', -1, 13, 24)}>−</button>
                    <span>{appearance.font_sizes.body}px</span>
                    <button type="button" aria-label="Increase reading font size" disabled={appearanceDisabled || appearance.font_sizes.body >= 24} onclick={() => stepFontSize('body', 1, 13, 24)}>+</button>
                  </div>
                </div>
              </div>
            {/if}
            {#if showMonoFont}
              <div class="setting-row">
                <div class="setting-info">
                  <span class="setting-label">Editor &amp; code font</span>
                  <span class="setting-desc">Monospace font family and size for Source mode and code blocks.</span>
                </div>
                <div class="setting-control">
                  <details class="setting-select" bind:open={monoFontMenuOpen}>
                    <summary aria-label="Editor and code font" aria-disabled={appearanceDisabled} onclick={(event) => { if (appearanceDisabled) event.preventDefault() }}>
                      <span>{fontDisplayLabel(monoFontPresets, appearance.fonts.monospace)}</span>
                      <Icon name="chevron-down" size={14} />
                    </summary>
                    <PopupMenu class="setting-select-menu" label="Editor and code font">
                      {#each monoFontPresets as preset (preset.id)}
                        {@const selected = activeFontPreset(monoFontPresets, appearance.fonts.monospace)?.id === preset.id}
                        <button class="popup-menu-item" aria-pressed={selected} disabled={appearanceDisabled} onclick={() => { monoFontMenuOpen = false; updateFont('monospace', preset.stack) }}>
                          {preset.label}{#if selected}<span class="popup-menu-mark"><Icon name="check" size={14} /></span>{/if}
                        </button>
                      {/each}
                    </PopupMenu>
                  </details>
                  <div class="font-size-stepper" role="group" aria-label="Editor and code font size">
                    <button type="button" aria-label="Decrease editor font size" disabled={appearanceDisabled || appearance.font_sizes.monospace <= 11} onclick={() => stepFontSize('monospace', -1, 11, 22)}>−</button>
                    <span>{appearance.font_sizes.monospace}px</span>
                    <button type="button" aria-label="Increase editor font size" disabled={appearanceDisabled || appearance.font_sizes.monospace >= 22} onclick={() => stepFontSize('monospace', 1, 11, 22)}>+</button>
                  </div>
                </div>
              </div>
            {/if}
          </div>
        </section>
      {/if}

      {#if showThemeColorsGroup}
        <section class="settings-group">
          <div class="settings-group-header">
            <h2>Theme colors</h2>
            <span class="settings-group-scope">{searching ? 'Workspace · Coming soon' : 'Coming soon'}</span>
          </div>
          <details class="settings-card settings-disclosure" open={searching || themeColorsOpen} ontoggle={(event) => { if (!searching) themeColorsOpen = (event.currentTarget as HTMLDetailsElement).open }}>
            <summary class="setting-row settings-disclosure-summary">
              <div class="setting-info">
                <span class="setting-label">Customize theme colors</span>
                <span class="setting-desc">Override interface and Markdown color tokens, or import and export themes.</span>
              </div>
              <span class="settings-disclosure-chevron" aria-hidden="true"><Icon name="chevron-down" size={15} /></span>
            </summary>
            <div class="settings-disclosure-body">
              <div class="setting-row setting-row-stack">
                <div class="setting-info">
                  <span class="setting-label">Interface colors</span>
                  <span class="setting-desc">Customize semantic color roles for the active theme.</span>
                </div>
                <div class="color-token-list" aria-label="Interface color roles">
                  {#each colorTokens as token (token.id)}
                    <button class="color-token-item" type="button" disabled title="Not available yet">
                      <span class="color-token-swatch" style:background={`var(${token.cssVar})`}></span>
                      <span class="color-token-name">{token.label}</span>
                      <span class="color-token-role">{token.role}</span>
                      <span class="color-token-var">{token.cssVar}</span>
                    </button>
                  {/each}
                </div>
              </div>
              <div class="setting-row setting-row-stack">
                <div class="setting-info">
                  <span class="setting-label">Markdown colors</span>
                  <span class="setting-desc">Heading levels, code, quotes, links, and syntax markers in Source and Read modes.</span>
                </div>
                <div class="color-token-list" aria-label="Markdown color roles">
                  {#each markdownColorTokens as token (token.id)}
                    <button class="color-token-item" type="button" disabled title="Not available yet">
                      <span class="color-token-swatch" style:background={`var(${token.previewVar})`}></span>
                      <span class="color-token-name">{token.label}</span>
                      <span class="color-token-role">{token.role}</span>
                      <span class="color-token-var">{token.cssVar}</span>
                    </button>
                  {/each}
                </div>
              </div>
              <div class="setting-row theme-actions-row">
                <div class="theme-actions-group">
                  <button class="text-button" type="button" disabled title="Not available yet">Save as new theme</button>
                  <button class="text-button" type="button" disabled title="Not available yet">Import theme</button>
                  <button class="text-button" type="button" disabled title="Not available yet">Export theme</button>
                </div>
                <button class="text-button" type="button" disabled title="Not available yet">Reset defaults</button>
              </div>
            </div>
          </details>
        </section>
      {/if}

      {#if showWorkspaceFilesGroup}
        <section class="settings-group">
          <div class="settings-group-header">
            <h2>Workspace files</h2>
            {#if searching}<span class="settings-group-scope">Workspace</span>{/if}
          </div>
          <div class="settings-card">
            <div class="setting-row">
              <div class="setting-info">
                <label class="setting-label" for="settings-new-items-folder">New items folder</label>
                <span class="setting-desc">Default folder for new notes and folders, relative to the workspace. Use . for the workspace root.</span>
                {#if folderSettingsMessage}<span role="status" class="setting-feedback">{folderSettingsMessage}</span>{/if}
              </div>
              <div class="setting-control">
                <input
                  id="settings-new-items-folder"
                  class="setting-input"
                  aria-label="New items folder"
                  type="text"
                  bind:value={creationFolderInput}
                  disabled={!workspaceId}
                />
                <button class="text-button" onclick={onSaveCreationFolder} disabled={!workspaceId}>Save folder</button>
              </div>
            </div>
          </div>
        </section>
      {/if}

      {#if showExclusionsGroup}
        <section class="settings-group">
          <div class="settings-group-header">
            <h2>Exclusions</h2>
            <span class="settings-group-scope">{searching ? 'Workspace · Coming soon' : 'Coming soon'}</span>
          </div>
          <div class="settings-card">
            <div class="setting-row setting-row-stack">
              <div class="setting-info">
                <label class="setting-label" for="settings-excluded-paths">Excluded folders and files</label>
                <span class="setting-desc">Hide matching paths from the file tree and workspace search.</span>
              </div>
              <div class="exclusion-input-row">
                <input
                  id="settings-excluded-paths"
                  class="setting-input exclusion-input"
                  type="text"
                  placeholder="Add folder or pattern (e.g. archive/2024)"
                  disabled
                  title="Not available yet"
                />
                <button class="text-button" type="button" disabled title="Not available yet">Add pattern</button>
              </div>
              <div class="exclusion-list" aria-label="Excluded paths">
                <div class="exclusion-empty">No excluded folders or files yet.</div>
              </div>
            </div>
            <label class="setting-row setting-row-toggle setting-row-disabled">
              <div class="setting-info">
                <span class="setting-label">Separate index exclusions</span>
                <span class="setting-desc">Configure files excluded from indexing separately from file-tree visibility.</span>
              </div>
              <div class="setting-control">
                <input class="setting-switch" type="checkbox" checked disabled title="Not available yet" />
              </div>
            </label>
          </div>
        </section>
      {/if}

      {#if showEditorGroup}
        <section class="settings-group">
          <div class="settings-group-header">
            <h2>Editor</h2>
            {#if searching}<span class="settings-group-scope">Application</span>{/if}
          </div>
          <div class="settings-card">
            {#if showAutosave}
              <label class="setting-row setting-row-toggle">
                <div class="setting-info">
                  <span class="setting-label">Save changes automatically</span>
                  <span class="setting-desc">Write edits to disk after a short pause without pressing Ctrl+S.</span>
                </div>
                <div class="setting-control">
                  <input
                    class="setting-switch"
                    type="checkbox"
                    checked={editorPreferences.autosave}
                    disabled={!editorPreferencesLoaded || editorPreferenceSaving.autosave}
                    onchange={(event) => onSetEditorPreference('autosave', event.currentTarget)}
                  />
                </div>
              </label>
            {/if}
            {#if showAutoReload}
              <label class="setting-row setting-row-toggle">
                <div class="setting-info">
                  <span class="setting-label">Auto-reload unchanged notes</span>
                  <span class="setting-desc">Reload notes when the disk version changes and there are no local edits.</span>
                </div>
                <div class="setting-control">
                  <input
                    class="setting-switch"
                    type="checkbox"
                    checked={editorPreferences.auto_reload}
                    disabled={!editorPreferencesLoaded || editorPreferenceSaving.auto_reload}
                    onchange={(event) => onSetEditorPreference('auto_reload', event.currentTarget)}
                  />
                </div>
              </label>
            {/if}
            {#if showReloadNotice}
              <label class="setting-row setting-row-toggle">
                <div class="setting-info">
                  <span class="setting-label">Reload notice</span>
                  <span class="setting-desc">Show a notice after reloading a changed note.</span>
                </div>
                <div class="setting-control">
                  <input
                    class="setting-switch"
                    type="checkbox"
                    checked={editorPreferences.reload_notice}
                    disabled={!editorPreferencesLoaded || editorPreferenceSaving.reload_notice}
                    onchange={(event) => onSetEditorPreference('reload_notice', event.currentTarget)}
                  />
                </div>
              </label>
            {/if}
          </div>
        </section>
      {/if}

      {#if showFileAccessGroup}
        <section class="settings-group">
          <div class="settings-group-header">
            <h2>File access</h2>
            {#if searching}<span class="settings-group-scope">Application</span>{/if}
          </div>
          <div class="settings-card">
            <div class="setting-row setting-row-stack">
              <div class="setting-row-head">
                <div class="setting-info">
                  <label class="setting-label" for="settings-blocked-extensions">Blocked extensions</label>
                  <span class="setting-desc">Extensions listed here stay visible in the file tree but cannot be opened directly.</span>
                </div>
                <form class="setting-control" onsubmit={(event) => { event.preventDefault(); void addBlockedExtension() }}>
                  <input
                    id="settings-blocked-extensions"
                    class="setting-input setting-ext-input"
                    type="text"
                    placeholder=".exe"
                    disabled={!editorPreferencesLoaded}
                    bind:value={newExtension}
                  />
                  <button class="text-button" type="submit" disabled={!editorPreferencesLoaded || blockedSaving || !newExtension.trim()}>Add</button>
                </form>
              </div>
              {#if !editorPreferencesLoaded}
                <p class="setting-desc">Loading blocked extensions...</p>
              {:else if blockedList.length}
                <div class="extension-chips" role="list" aria-label="Blocked extensions">
                  {#each blockedList as ext (ext)}
                    <span class="extension-chip" role="listitem">
                      <span>{ext}</span>
                      <button
                        type="button"
                        class="extension-chip-remove"
                        aria-label={`Remove ${ext}`}
                        title={`Remove ${ext}`}
                        disabled={!editorPreferencesLoaded || blockedSaving}
                        onclick={() => void removeBlockedExtension(ext)}
                      ><Icon name="x" size={11} /></button>
                    </span>
                  {/each}
                </div>
              {:else}
                <p class="setting-desc">No extensions are currently blocked.</p>
              {/if}
              {#if blockedMessage}<span role={blockedMessage.startsWith('Could not') ? 'alert' : 'status'} class="setting-feedback" class:setting-feedback-error={blockedMessage.startsWith('Could not')}>{blockedMessage}</span>{/if}
            </div>
          </div>
        </section>
      {/if}

      {#if showConnectionGroup}
        <section class="settings-group">
          <div class="settings-group-header">
            <h2>Connection</h2>
            {#if searching}<span class="settings-group-scope">Application</span>{/if}
          </div>
          <div class="settings-card">
            <div class="setting-row">
              <div class="setting-info">
                <span class="setting-label">Backend bridge</span>
                <p class="connection-status setting-connection-status" aria-live="polite"><span class="connection-dot" class:connected={ready}></span>{connectionMessage}</p>
              </div>
              <div class="setting-control">
                <button class="text-button" onclick={onPing} disabled={!ready}>Check connection</button>
              </div>
            </div>
          </div>
        </section>
      {/if}
    </div>
  </div>
</section>
