<script module lang="ts">
  type SortMode = 'alphabetic' | 'modified'
  type FileTreeItem = { name: string; is_directory: boolean; modified_time: number | null }
  type DirectorySnapshot = {
    workspace_id: string; path: string; items: FileTreeItem[] | null
    loading: boolean; stale: boolean; error: string | null
  }
  type TreeSnapshot = {
    workspace_id: string; revision: number; directories: DirectorySnapshot[]
    watcher_error: string | null
  }
  type TreeRow =
    | { kind: 'item'; path: string; item: FileTreeItem; depth: number }
    | { kind: 'status'; path: string; message: string; depth: number; error: boolean }
  type NoteSnapshot = { path: string; content: string; version: string }
  type ThemeId = 'warm-charcoal' | 'warm-paper'
  type SurfaceMode = 'framed' | 'seamless'
  type FileIconId = 'file' | 'markdown' | 'image' | 'pdf' | 'code'
  type WorkspaceAppearance = {
    theme: string
    surface_mode: string
    file_icons: { set: string; extensions: Record<string, string> }
  }
  type AppearancePatch = { theme?: ThemeId; surface_mode?: SurfaceMode }
  type AppearanceState = { theme: ThemeId; surface_mode: SurfaceMode; file_icons: WorkspaceAppearance['file_icons'] }
  type TreeApi = {
    ping: () => Promise<string>
    get_settings: () => Promise<{ workspaces: string[]; blocked_extensions: string[]; editor: { autosave: boolean; auto_reload: boolean; reload_notice: boolean } }>
    set_editor_preference: (name: string, value: boolean) => Promise<void>
    get_workspace_settings: (path: string) => Promise<{ automatic_link_update: boolean; appearance: WorkspaceAppearance }>
    set_workspace_appearance: (workspace_id: string, appearance: AppearancePatch) => Promise<void>
    open_workspace: (path: string) => Promise<TreeSnapshot>
    get_tree: (id: string) => Promise<TreeSnapshot>
    set_directory_visible: (id: string, path: string, visible: boolean) => Promise<TreeSnapshot>
    set_tree_sort: (id: string, sort: SortMode) => Promise<TreeSnapshot>
    refresh_tree: (id: string, path: string | null) => Promise<TreeSnapshot>
    read_note: (id: string, path: string) => Promise<NoteSnapshot>
    list_plan_notes: (id: string) => Promise<string[]>
    read_plan_notes: (id: string, paths: string[], start: number, maxBytes: number, maxNotes: number) => Promise<{ notes: NoteSnapshot[]; next_index: number }>
    plan_link_targets_batch: (id: string, source: string, destination: string, notes: { path: string; targets: string[] }[]) => Promise<(string | null)[][]>
    commit_move: (id: string, source: string, destination: string, snapshots: { path: string; version: string }[] | null, rewrites: NoteSnapshot[]) => Promise<{ destination: string; updated: string[]; failures: { path: string; error: string }[] }>
    create_note: (id: string, directory: string, name: string) => Promise<string>
    create_directory: (id: string, directory: string, name: string) => Promise<string>
    resolve_note_link: (id: string, note: string, href: string) => Promise<{ path: string; fragment: string }>
    open_workspace_file: (id: string, path: string) => Promise<boolean>
    reveal_workspace_file: (id: string, path: string) => Promise<void>
    set_blocked_extensions: (extensions: string[]) => Promise<void>
    media_url: (id: string) => Promise<string>
    open_external_link: (url: string) => Promise<void>
    save_note: (id: string, path: string, content: string, version: string) => Promise<NoteSnapshot>
    set_active_note: (id: string, path: string) => Promise<void>
    finish_close: () => Promise<void>
  }
  declare global {
    interface Window {
      pywebview?: { api?: TreeApi; state: EventTarget }
    }
  }
</script>

<script lang="ts">
  import { onMount, tick } from 'svelte'
  import Icon from './Icon.svelte'
  import NoteEditor from './NoteEditor.svelte'
  import { openWorkspaceFile } from './fileActions'
  import { planMoveLinks } from './markdownLinkPlan'

  const defaultAppearance: AppearanceState = {
    theme: 'warm-charcoal',
    surface_mode: 'framed',
    file_icons: { set: 'minimal', extensions: {} },
  }
  const imageExtensions = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.avif']
  const codeExtensions = ['.json', '.yaml', '.yml', '.toml', '.py', '.ts', '.tsx', '.js', '.jsx', '.css', '.html', '.sh', '.sql']

  let ready = $state(false)
  let message = $state('Waiting for backend...')
  let workspaces = $state<string[]>([])
  let workspacesLoaded = $state(false)
  let workspaceMessage = $state('')
  let blockedExtensions = $state('')
  let blockedMessage = $state('')
  let loadingWorkspace = $state(false)
  let selectedWorkspace = $state<string | null>(null)
  let workspaceId = $state<string | null>(null)
  let appearance = $state<AppearanceState>(defaultAppearance)
  let appearanceSaving = $state(false)
  let settingsOpen = $state(false)
  let filePanelOpen = $state(true)
  let workspacePicker: HTMLDetailsElement | undefined = $state()
  let settingsMenu: HTMLDetailsElement | undefined = $state()
  let editor: NoteEditor | undefined = $state()
  let selectedNote = $state<string | null>(null)
  let latestRevision = -1
  let sortMode = $state<SortMode>('alphabetic')
  let directories = $state.raw<Record<string, DirectorySnapshot>>({})
  let expandedFolders = $state<string[]>([])
  let creationFolder = $state('')
  let creating = $state(false)
  let moving = $state(false)
  let editorMounted = $state(true)
  let automaticLinkUpdate = true
  let watcherError = $state<string | null>(null)
  let visibleTree = $derived(buildVisibleTree())
  let rootDirectory = $derived(directories[''])
  const rowHeight = 32
  const overscan = 8
  let scrollTop = $state(0)
  let viewportHeight = $state(0)
  let viewport: HTMLDivElement | undefined = $state()
  const refreshIndicatorDelay = 400
  let delayedRefreshes = $state<string[]>([])
  const refreshTimers = new Map<string, ReturnType<typeof setTimeout>>()
  let startRow = $derived(Math.max(0, Math.min(visibleTree.length, Math.floor(scrollTop / rowHeight) - overscan)))
  let endRow = $derived(Math.min(visibleTree.length, Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan))
  let renderedRows = $derived(visibleTree.slice(startRow, endRow))
  $effect(() => {
    document.documentElement.dataset.theme = appearance.theme
    document.documentElement.dataset.surface = appearance.surface_mode
  })

  $effect(() => {
    const currentViewport = viewport
    if (filePanelOpen && currentViewport && currentViewport.scrollTop !== scrollTop) {
      currentViewport.scrollTop = scrollTop
    }
  })

  $effect(() => {
    const refreshing = new Set(Object.values(directories)
      .filter((directory) => directory.items !== null && !directory.error && (directory.loading || directory.stale))
      .map((directory) => directory.path))
    for (const [path, timer] of refreshTimers) {
      if (!refreshing.has(path)) {
        clearTimeout(timer)
        refreshTimers.delete(path)
      }
    }
    const finished = delayedRefreshes.filter((path) => !refreshing.has(path))
    if (finished.length) delayedRefreshes = delayedRefreshes.filter((path) => refreshing.has(path))
    for (const path of refreshing) {
      if (refreshTimers.has(path) || delayedRefreshes.includes(path)) continue
      refreshTimers.set(path, setTimeout(() => {
        refreshTimers.delete(path)
        delayedRefreshes = [...delayedRefreshes, path]
      }, refreshIndicatorDelay))
    }
  })

  function applySnapshot(snapshot: TreeSnapshot) {
    if (snapshot.workspace_id !== workspaceId || snapshot.revision < latestRevision) return
    latestRevision = snapshot.revision
    directories = Object.fromEntries(snapshot.directories.map((directory) => [directory.path, directory]))
    watcherError = snapshot.watcher_error
  }

  async function syncTree() {
    const api = window.pywebview?.api
    const id = workspaceId
    if (!api || !id) return
    try { applySnapshot(await api.get_tree(id)) }
    catch (error) { if (id === workspaceId) console.error(error) }
  }

  onMount(() => {
    let subscribedState: EventTarget | undefined
    function handleStateChange(event: Event) {
      const detail = (event as CustomEvent<{ key: string }>).detail
      if (detail?.key === 'file_tree_revision') { void syncTree(); editor?.scheduleExternalCheck() }
      if (detail?.key === 'note_revision') editor?.scheduleExternalCheck()
      if (detail?.key === 'close_request') void closeWindow()
    }
    async function closeWindow() {
      if (moving) return
      if (!editor || await editor.prepareClose()) await window.pywebview?.api?.finish_close()
    }
    function updateBridgeStatus() {
      const webview = window.pywebview
      if (!ready && webview?.api && webview.state) {
        subscribedState = webview.state
        subscribedState.addEventListener('change', handleStateChange)
        ready = true
        message = 'Backend connected.'
        void loadWorkspaces()
        void syncTree()
      }
    }
    function onFocus() { void refreshTree(null); editor?.scheduleExternalCheck() }
    window.addEventListener('pywebviewready', updateBridgeStatus)
    window.addEventListener('focus', onFocus)
    updateBridgeStatus()
    return () => {
      window.removeEventListener('pywebviewready', updateBridgeStatus)
      window.removeEventListener('focus', onFocus)
      subscribedState?.removeEventListener('change', handleStateChange)
      for (const timer of refreshTimers.values()) clearTimeout(timer)
      refreshTimers.clear()
    }
  })

  async function ping() {
    try { message = await window.pywebview?.api?.ping() ?? message }
    catch (error) { message = 'Could not connect to the backend.'; console.error(error) }
  }
  async function loadWorkspaces() {
    const api = window.pywebview?.api
    if (!api) return
    try {
      const settings = await api.get_settings()
      workspaces = settings.workspaces
      blockedExtensions = (settings.blocked_extensions ?? []).join(', ')
      workspacesLoaded = true
    }
    catch (error) { workspaceMessage = 'Could not load workspaces.'; console.error(error) }
  }
  async function saveBlockedExtensions() {
    try {
      const extensions = blockedExtensions.split(/[\s,]+/).filter(Boolean)
      await window.pywebview?.api?.set_blocked_extensions(extensions)
      blockedMessage = 'Blocked extensions saved.'
    } catch (error) { blockedMessage = 'Could not save blocked extensions. Use extensions such as .exe.'; console.error(error) }
  }
  async function openTreeFile(path: string) {
    if (!workspaceId) return
    try { await openWorkspaceFile(workspaceId, path) }
    catch (error) { workspaceMessage = 'Could not open the file.'; console.error(error) }
  }
  async function selectWorkspace(path: string) {
    const api = window.pywebview?.api
    if (!api) return
    if (appearanceSaving) return
    if (editor && !(await editor.prepareClose())) return
    if (workspacePicker) workspacePicker.open = false
    loadingWorkspace = true
    workspaceMessage = ''
    selectedWorkspace = null
    selectedNote = null
    workspaceId = null
    appearance = { ...defaultAppearance, file_icons: { set: 'minimal', extensions: {} } }
    latestRevision = -1
    directories = {}
    expandedFolders = []
    creationFolder = ''
    scrollTop = 0
    if (viewport) viewport.scrollTop = 0
    sortMode = 'alphabetic'
    try {
      const preferences = await api.get_workspace_settings(path)
      const snapshot = await api.open_workspace(path)
      workspaceId = snapshot.workspace_id
      selectedWorkspace = path
      automaticLinkUpdate = preferences.automatic_link_update !== false
      appearance = normalizeAppearance(preferences.appearance)
      applySnapshot(snapshot)
      await syncTree()
    } catch (error) {
      workspaceMessage = `Could not open workspace: ${path}. Check the folder and its settings.`
      console.error(error)
    } finally { loadingWorkspace = false }
  }
  function toggleFilePanel() {
    filePanelOpen = !filePanelOpen
  }
  async function toggleSettings() {
    settingsOpen = !settingsOpen
    if (!settingsOpen) return
    await tick()
    settingsMenu?.querySelector<HTMLElement>('summary')?.focus()
  }
  function normalizeAppearance(value: WorkspaceAppearance): AppearanceState {
    if (value.theme !== 'warm-charcoal' && value.theme !== 'warm-paper') {
      console.warn(`Unsupported workspace theme "${value.theme}". Using Warm Charcoal in the interface.`)
    }
    if (value.surface_mode !== 'framed' && value.surface_mode !== 'seamless') {
      console.warn(`Unsupported workspace surface "${value.surface_mode}". Using Framed in the interface.`)
    }
    if (value.file_icons.set !== 'minimal') {
      console.warn(`Unsupported workspace file icon set "${value.file_icons.set}". Using the minimal icon set in the interface.`)
    }
    for (const [extension, icon] of Object.entries(value.file_icons.extensions)) {
      if (!isFileIconId(icon)) console.warn(`Unsupported icon ID "${icon}" for "${extension}". Using that extension's minimal default icon.`)
    }
    return {
      theme: value.theme === 'warm-paper' ? 'warm-paper' : 'warm-charcoal',
      surface_mode: value.surface_mode === 'seamless' ? 'seamless' : 'framed',
      file_icons: value.file_icons,
    }
  }
  function isFileIconId(value: string): value is FileIconId {
    return value === 'file' || value === 'markdown' || value === 'image' || value === 'pdf' || value === 'code'
  }
  function minimalFileIcon(extension: string): FileIconId {
    if (extension === '.md' || extension === '.markdown') return 'markdown'
    if (imageExtensions.includes(extension)) return 'image'
    if (extension === '.pdf') return 'pdf'
    if (codeExtensions.includes(extension)) return 'code'
    return 'file'
  }
  function fileIconFor(name: string): FileIconId {
    const dot = name.lastIndexOf('.')
    const extension = dot >= 0 ? name.slice(dot).toLowerCase() : ''
    const override = Object.entries(appearance.file_icons.extensions)
      .find(([key]) => key.toLowerCase() === extension)?.[1]
    return override && isFileIconId(override) ? override : minimalFileIcon(extension)
  }
  async function setAppearance(patch: AppearancePatch) {
    const api = window.pywebview?.api
    const id = workspaceId
    if (!api || !id || appearanceSaving) return
    const previous = { ...appearance }
    appearanceSaving = true
    appearance = { ...appearance, ...patch }
    workspaceMessage = ''
    try {
      await api.set_workspace_appearance(id, patch)
      if (id === workspaceId) workspaceMessage = 'Appearance saved.'
    } catch (error) {
      if (id === workspaceId) {
        appearance = previous
        workspaceMessage = 'Could not save appearance settings.'
      }
      console.error(error)
    } finally { appearanceSaving = false }
  }
  async function toggleFolder(path: string) {
    const api = window.pywebview?.api
    const id = workspaceId
    if (!api || !id) return
    const closing = expandedFolders.includes(path)
    const affected = closing ? expandedFolders.filter((p) => p === path || p.startsWith(`${path}/`)) : [path]
    expandedFolders = closing ? expandedFolders.filter((p) => !affected.includes(p)) : [...expandedFolders, path]
    if (closing && affected.includes(creationFolder)) creationFolder = ''
    try {
      for (const folder of affected) applySnapshot(await api.set_directory_visible(id, folder, !closing))
    } catch (error) { if (id === workspaceId) { workspaceMessage = 'Could not update the folder.'; console.error(error) } }
  }
  async function createEntry(kind: 'note' | 'folder') {
    const api = window.pywebview?.api
    const id = workspaceId
    if (!api || !id || creating) return
    const name = window.prompt(kind === 'note' ? 'New note name:' : 'New folder name:')
    if (name === null) return
    creating = true
    workspaceMessage = ''
    try {
      if (kind === 'note') await api.create_note(id, creationFolder, name)
      else await api.create_directory(id, creationFolder, name)
      if (id === workspaceId) await syncTree()
    } catch (error) {
      if (id === workspaceId) workspaceMessage = 'Could not create the item. Check its name, location, and whether it already exists.'
      console.error(error)
    } finally { creating = false }
  }
  async function moveEntry(source: string) {
    const api = window.pywebview?.api
    const id = workspaceId
    if (!api || !id || moving) return
    const destination = window.prompt('Move or rename to (workspace-relative path):', source)
    if (destination === null || destination === source) return
    moving = true
    workspaceMessage = ''
    try {
      if (editor && !(await editor.prepareClose())) return
      // Close the approved editor before planning so edits cannot race with the move.
      editorMounted = false
      selectedNote = null
      await tick()
      workspaceMessage = 'Preparing link updates...'
      const plan = automaticLinkUpdate ? await planMoveLinks(api, id, source, destination) : null
      workspaceMessage = 'Moving and updating links...'
      const result = await api.commit_move(id, source, destination, plan?.snapshots ?? null, plan?.rewrites ?? [])
      for (const folder of expandedFolders) {
        if (folder !== source && !folder.startsWith(`${source}/`)) {
          try { await api.set_directory_visible(id, folder, false) } catch (error) { console.error(error) }
        }
      }
      expandedFolders = []
      creationFolder = ''
      await syncTree()
      workspaceMessage = result.failures.length
        ? `Moved, but some notes could not be updated: ${result.failures.map(item => `${item.path}: ${item.error}`).join('; ')}`
        : `Moved. Updated links in ${result.updated.length} notes.`
    } catch (error) {
      workspaceMessage = `Could not complete the move: ${String(error)}`
      console.error(error)
    } finally {
      editorMounted = true
      moving = false
    }
  }
  async function changeSortMode(event: Event) {
    const target = event.currentTarget
    const api = window.pywebview?.api
    const id = workspaceId
    if (!(target instanceof HTMLSelectElement) || !api || !id) return
    if (target.value !== 'alphabetic' && target.value !== 'modified') return
    sortMode = target.value
    try { applySnapshot(await api.set_tree_sort(id, sortMode)) }
    catch (error) { workspaceMessage = 'Could not change sorting.'; console.error(error) }
  }
  async function refreshTree(path: string | null) {
    const api = window.pywebview?.api
    const id = workspaceId
    if (!api || !id) return
    try { applySnapshot(await api.refresh_tree(id, path)) }
    catch (error) { if (id === workspaceId) { workspaceMessage = 'Could not refresh the file tree.'; console.error(error) } }
  }
  async function handleTreeKeydown(event: KeyboardEvent) {
    if (event.key !== 'Tab' || !(event.target instanceof HTMLButtonElement) || !viewport) return
    const entry = event.target.closest<HTMLElement>('[data-row-index]')
    if (!entry) return
    const buttons = Array.from(entry.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
    const position = buttons.indexOf(event.target)
    if ((!event.shiftKey && position < buttons.length - 1) || (event.shiftKey && position > 0)) return
    const current = Number(entry.dataset.rowIndex)
    const direction = event.shiftKey ? -1 : 1
    let next = current + direction
    while (next >= 0 && next < visibleTree.length) {
      const row = visibleTree[next]
      if (row.kind === 'item' || (row.kind === 'status' && row.error)) break
      next += direction
    }
    if (next < 0 || next >= visibleTree.length) return
    event.preventDefault()
    const top = next * rowHeight
    if (top < viewport.scrollTop || top + rowHeight > viewport.scrollTop + viewport.clientHeight) {
      viewport.scrollTop = Math.max(0, top - viewport.clientHeight / 2)
      scrollTop = viewport.scrollTop
    }
    await tick()
    const nextButtons = viewport.querySelectorAll<HTMLButtonElement>(`[data-row-index="${next}"] button`)
    nextButtons[event.shiftKey ? nextButtons.length - 1 : 0]?.focus()
  }
  function handleTreeScroll(event: Event) {
    if (!(event.currentTarget instanceof HTMLDivElement)) return
    const element = event.currentTarget
    scrollTop = element.scrollTop
    const focusedRow = document.activeElement?.closest<HTMLElement>('[data-row-index]')
    if (!focusedRow || !element.contains(focusedRow)) return
    const index = Number(focusedRow.dataset.rowIndex)
    const first = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
    const last = Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan
    if (index < first || index >= last) element.focus({ preventScroll: true })
  }
  function buildVisibleTree(): TreeRow[] {
    const rows: TreeRow[] = []
    function addChildren(parent: string, depth: number) {
      for (const item of directories[parent]?.items ?? []) {
        const path = parent ? `${parent}/${item.name}` : item.name
        rows.push({ kind: 'item', path, item, depth })
        if (!item.is_directory || !expandedFolders.includes(path)) continue
        const dir = directories[path]
        if (dir?.items) addChildren(path, depth + 1)
        if (dir?.error) rows.push({ kind: 'status', path, message: `Refresh failed: ${dir.error}`, depth: depth + 1, error: true })
        else if ((!dir || dir.loading || dir.stale) && (!dir?.items || delayedRefreshes.includes(path))) rows.push({ kind: 'status', path, message: dir?.items ? 'Refreshing...' : 'Loading...', depth: depth + 1, error: false })
      }
    }
    addChildren('', 0)
    return rows
  }
</script>

<main class="app-shell">
  <header class="menu-bar" aria-label="Application menu">
    <div class="menu-items" aria-label="Menus">
      <button class="menu-sidebar-toggle" onclick={toggleFilePanel} aria-label="Toggle files panel" aria-pressed={filePanelOpen} title="Toggle files panel"><Icon name="folder" /></button>
      {#each ['File', 'Edit', 'View', 'Navigate', 'Help'] as menu}
        <button class="menu-item" disabled title="This menu is not available yet">{menu}</button>
      {/each}
    </div>
    <div class="appearance-controls" aria-label="Appearance">
      <div class="appearance-group" role="group" aria-label="Theme">
        <button class:active={appearance.theme === 'warm-charcoal'} aria-pressed={appearance.theme === 'warm-charcoal'} disabled={!workspaceId || appearanceSaving} onclick={() => setAppearance({ theme: 'warm-charcoal' })}>Warm Charcoal</button>
        <button class:active={appearance.theme === 'warm-paper'} aria-pressed={appearance.theme === 'warm-paper'} disabled={!workspaceId || appearanceSaving} onclick={() => setAppearance({ theme: 'warm-paper' })}>Warm Paper</button>
      </div>
      <div class="appearance-group surface-group" role="group" aria-label="Document surface">
        <button class:active={appearance.surface_mode === 'framed'} aria-pressed={appearance.surface_mode === 'framed'} disabled={!workspaceId || appearanceSaving} onclick={() => setAppearance({ surface_mode: 'framed' })}>Framed</button>
        <button class:active={appearance.surface_mode === 'seamless'} aria-pressed={appearance.surface_mode === 'seamless'} disabled={!workspaceId || appearanceSaving} onclick={() => setAppearance({ surface_mode: 'seamless' })}>Seamless</button>
      </div>
    </div>
    <div class="header-actions">
      <p class="connection-status" aria-live="polite"><span class="connection-dot" class:connected={ready}></span>{message}</p>
      <button class="icon-button" onclick={ping} disabled={!ready} aria-label="Check connection" title="Check connection"><Icon name="refresh" /></button>
      <details bind:open={settingsOpen} bind:this={settingsMenu} class="settings-menu">
        <summary>Settings</summary>
        <div class="settings-content">
          <strong>Blocked file extensions</strong>
          <p>Files with these extensions are shown in the tree but cannot be opened directly.</p>
          <label>Extensions <textarea bind:value={blockedExtensions} rows="3"></textarea></label>
          <button class="text-button" onclick={saveBlockedExtensions}>Save extensions</button>
          {#if blockedMessage}<p role="status">{blockedMessage}</p>{/if}
        </div>
      </details>
    </div>
  </header>

  <div class="workspace-layout" class:files-hidden={!filePanelOpen}>
    <nav class="activity-bar" aria-label="Application tools">
      <button class="activity-button" class:active={filePanelOpen} onclick={toggleFilePanel} aria-label="Files" aria-pressed={filePanelOpen} title="Files"><Icon name="folder" /></button>
      <button class="activity-button" disabled aria-label="Graph view" title="Graph view is not available yet"><Icon name="network" /></button>
      <button class="activity-button" disabled aria-label="Command palette" title="Command palette is not available yet"><Icon name="terminal" /></button>
      <div class="activity-spacer"></div>
      <button class="activity-button" onclick={toggleSettings} aria-label="Settings" aria-expanded={settingsOpen} title="Settings"><Icon name="settings" /></button>
    </nav>

    {#if filePanelOpen}
      <aside class="file-tree" aria-label="Workspace file tree" inert={moving}>
        <div class="tree-heading">
          <h2>Files</h2>
          <div class="tree-actions">
            <button class="icon-button" onclick={() => refreshTree(null)} disabled={!workspaceId} aria-label="Refresh file tree" title="Refresh file tree"><Icon name="refresh" /></button>
            <button class="icon-button" disabled={!workspaceId || creating} onclick={() => createEntry('note')} aria-label="New note" title="New note"><Icon name="file-plus" /></button>
            <button class="icon-button" disabled={!workspaceId || creating} onclick={() => createEntry('folder')} aria-label="New folder" title="New folder"><Icon name="folder-plus" /></button>
          </div>
        </div>
        {#if workspaceId}
          <div class="tree-options">
            <label>Sort <select value={sortMode} onchange={changeSortMode}><option value="alphabetic">Alphabetical</option><option value="modified">Modified</option></select></label>
            <label>New item in <select aria-label="Destination" bind:value={creationFolder}><option value="">Workspace root</option>{#each expandedFolders as folder}<option value={folder}>{folder}</option>{/each}</select></label>
          </div>
          {#if watcherError}<p class="tree-alert" role="alert">File watcher: {watcherError}. Refresh manually.</p>{/if}
          {#if rootDirectory?.error}<p class="tree-alert" role="alert">{rootDirectory.error} <button class="text-button" onclick={() => refreshTree('')}>Retry</button></p>{/if}
          {#if rootDirectory?.loading && (!rootDirectory.items || delayedRefreshes.includes(''))}<p class="tree-status-message" aria-live="polite">{rootDirectory.items ? 'Refreshing...' : 'Loading workspace...'}</p>{/if}
          {#if rootDirectory?.items?.length === 0 && !rootDirectory.loading}<p class="tree-status-message">This workspace is empty.</p>{/if}
          <div class="tree-viewport" bind:this={viewport} bind:clientHeight={viewportHeight} tabindex="-1" aria-label="Scrollable file tree" onscroll={handleTreeScroll}>
            <ul class="tree-list">
              <li aria-hidden="true" style={`height: ${startRow * rowHeight}px`}></li>
              {#each renderedRows as row, index (row.kind === 'item' ? `item:${row.path}` : `status:${row.path}`)}
                <li class="tree-entry" data-row-index={startRow + index}>
                  {#if row.kind === 'item'}
                    <div class="tree-row" style={`padding-left: ${8 + row.depth * 20}px`}>
                      {#if row.item.is_directory}
                        <button class="tree-folder" onclick={() => toggleFolder(row.path)} onkeydown={handleTreeKeydown} aria-expanded={expandedFolders.includes(row.path)}>
                          <span class="tree-disclosure" aria-hidden="true">{expandedFolders.includes(row.path) ? '▾' : '▸'}</span>
                          <Icon name="folder" class="tree-icon folder-icon" />
                          <span class="tree-label" title={row.item.name}>{row.item.name}</span>
                        </button>
                      {:else if row.path.toLowerCase().endsWith('.md')}
                        <button class="tree-file tree-note" class:selected={selectedNote === row.path} aria-current={selectedNote === row.path ? 'true' : undefined} title={row.item.name} onclick={() => editor?.open(row.path)} onkeydown={handleTreeKeydown}>
                          <Icon name={fileIconFor(row.item.name)} class="tree-icon note-icon" />
                          <span class="tree-label">{row.item.name}</span>
                        </button>
                      {:else}
                        <button class="tree-file" title={row.item.name} onclick={() => openTreeFile(row.path)} onkeydown={handleTreeKeydown}>
                          <Icon name={fileIconFor(row.item.name)} class="tree-icon" />
                          <span class="tree-label">{row.item.name}</span>
                        </button>
                      {/if}
                      <button class="icon-button move-button" aria-label={`Move or rename ${row.item.name}`} title={`Move or rename ${row.item.name}`} onclick={() => moveEntry(row.path)} onkeydown={handleTreeKeydown}><Icon name="move" size={14} /></button>
                    </div>
                  {:else}
                    <div class="tree-status" style={`padding-left: ${8 + row.depth * 20}px`}>
                      <span title={row.message}>{row.message}</span> {#if row.error}<button class="text-button" onclick={() => refreshTree(row.path)} onkeydown={handleTreeKeydown}>Retry</button>{/if}
                    </div>
                  {/if}
                </li>
              {/each}
              <li aria-hidden="true" style={`height: ${(visibleTree.length - endRow) * rowHeight}px`}></li>
            </ul>
          </div>
        {:else}
          <p class="tree-status-message">Choose a workspace below to see its files.</p>
        {/if}
        <footer class="sidebar-footer">
          <details bind:this={workspacePicker} class="workspace-picker">
            <summary title={selectedWorkspace ?? 'Select workspace'}><span>{selectedWorkspace ?? 'Select workspace'}</span><span aria-hidden="true">⌄</span></summary>
            <div class="workspace-picker-menu">
              <strong>Workspaces</strong>
              {#if workspacesLoaded && workspaces.length === 0}<p class="empty-workspaces">No saved workspaces.</p>{/if}
              {#each workspaces as workspace}
                <button class:selected={selectedWorkspace === workspace} aria-current={selectedWorkspace === workspace ? 'page' : undefined} onclick={() => selectWorkspace(workspace)} disabled={loadingWorkspace || moving || appearanceSaving} title={workspace}>{workspace}</button>
              {/each}
            </div>
          </details>
        </footer>
      </aside>
    {/if}

    {#if workspaceId && editorMounted}
      <NoteEditor bind:this={editor} bind:selectedNote {workspaceId} {workspaceMessage} />
    {:else if selectedWorkspace}
      {#if workspaceMessage}<p class="workspace-message" role="alert">{workspaceMessage}</p>
      {:else}<section class="empty-state"><h2>No note selected</h2><p>Choose a Markdown file from the workspace tree.</p></section>{/if}
    {:else}
      <section class="empty-state" aria-live="polite">
        {#if workspaceMessage}<p class="workspace-message" role="alert">{workspaceMessage}</p>{/if}
        <h2>Select a workspace</h2>
        <p>Choose a workspace from the file panel.</p>
      </section>
    {/if}
  </div>
  <footer class="status-bar">
    <span>{selectedWorkspace ?? 'No workspace selected'}</span>
    <span>{selectedNote ?? 'No note open'} · {appearance.theme === 'warm-paper' ? 'Warm Paper' : 'Warm Charcoal'} · {appearance.surface_mode === 'seamless' ? 'Seamless' : 'Framed'}</span>
  </footer>
</main>
