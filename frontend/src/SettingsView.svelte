<script lang="ts">
  import { tick } from 'svelte'
  import Icon from './Icon.svelte'
  import PopupMenu from './PopupMenu.svelte'

  type ThemeId = 'warm-charcoal' | 'warm-paper'
  type SurfaceMode = 'framed' | 'seamless'
  type PageWidthPreset = '74ch' | '96ch' | '100%'
  type EditorPreferences = { autosave: boolean; auto_reload: boolean; reload_notice: boolean }
  type AppearancePatch = { theme?: ThemeId; surface_mode?: SurfaceMode; page_width?: PageWidthPreset }
  type AppearanceView = { theme: ThemeId; surface_mode: SurfaceMode; page_width: string }
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
    blockedExtensions = $bindable(),
    blockedMessage,
    ready,
    connectionMessage,
    onSetAppearance,
    onSetEditorPreference,
    onSaveCreationFolder,
    onSaveBlockedExtensions,
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
    ready: boolean
    connectionMessage: string
    onSetAppearance: (patch: AppearancePatch) => void | Promise<void>
    onSetEditorPreference: (key: keyof EditorPreferences, input: HTMLInputElement) => void | Promise<void>
    onSaveCreationFolder: () => void | Promise<void>
    onSaveBlockedExtensions: () => void | Promise<void>
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

  let scope = $state<Scope>('workspace')
  let query = $state('')
  let newExtension = $state('')
  let themeMenuOpen = $state(false)
  let surfaceMenuOpen = $state(false)
  let widthMenuOpen = $state(false)
  let appearanceDisabled = $derived(!workspaceId || appearanceSaving)
  let currentThemeLabel = $derived(themeOptions.find((option) => option.value === appearance.theme)?.label ?? appearance.theme)
  let currentSurfaceLabel = $derived(surfaceOptions.find((option) => option.value === appearance.surface_mode)?.label ?? appearance.surface_mode)
  let currentWidthLabel = $derived(pageWidthPresets.find((preset) => preset.value === appearance.page_width)?.label ?? appearance.page_width)
  let blockedList = $derived(blockedExtensions.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean))
  let normalizedQuery = $derived(query.trim().toLowerCase())
  let searching = $derived(normalizedQuery.length > 0)

  async function addBlockedExtension() {
    const raw = newExtension.split(/[\s,]+/).map((item) => item.trim().toLowerCase()).filter(Boolean)
    if (!raw.length) return
    const existing = new Set(blockedList.map((item) => item.toLowerCase()))
    const additions: string[] = []
    for (const token of raw) {
      const normalized = token.startsWith('.') ? token : `.${token}`
      if (!existing.has(normalized)) {
        existing.add(normalized)
        additions.push(normalized)
      }
    }
    newExtension = ''
    if (!additions.length) return
    blockedExtensions = [...blockedList, ...additions].join(', ')
    await tick()
    await onSaveBlockedExtensions()
  }

  async function removeBlockedExtension(target: string) {
    blockedExtensions = blockedList.filter((item) => item !== target).join(', ')
    await tick()
    await onSaveBlockedExtensions()
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
    showAppearanceGroup || showWorkspaceFilesGroup || showExclusionsGroup || showEditorGroup || showFileAccessGroup || showConnectionGroup,
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
                    bind:value={newExtension}
                  />
                  <button class="text-button" type="submit" disabled={!newExtension.trim()}>Add</button>
                </form>
              </div>
              {#if blockedList.length}
                <div class="extension-chips" role="list" aria-label="Blocked extensions">
                  {#each blockedList as ext (ext)}
                    <span class="extension-chip" role="listitem">
                      <span>{ext}</span>
                      <button
                        type="button"
                        class="extension-chip-remove"
                        aria-label={`Remove ${ext}`}
                        title={`Remove ${ext}`}
                        onclick={() => void removeBlockedExtension(ext)}
                      ><Icon name="x" size={11} /></button>
                    </span>
                  {/each}
                </div>
              {:else}
                <p class="setting-desc">No extensions are currently blocked.</p>
              {/if}
              {#if blockedMessage}<span role="status" class="setting-feedback">{blockedMessage}</span>{/if}
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
