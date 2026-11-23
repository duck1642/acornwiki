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
  type NoteTab = { key: string; path: string }
  type EditorPreferences = { autosave: boolean; auto_reload: boolean; reload_notice: boolean }
  type EditorStatus = { dirty: boolean; saving: boolean; conflict: boolean }
  type FlatOutlineHeading = { id: string; label: string; level: number }
  type OutlineHeading = FlatOutlineHeading & { children: OutlineHeading[] }
  type ThemeId = 'warm-charcoal' | 'warm-paper'
  type SurfaceMode = 'framed' | 'seamless'
  type PageWidthPreset = '74ch' | '96ch' | '100%'
  type FileIconId = 'file' | 'markdown' | 'image' | 'pdf' | 'code'
  type WorkspaceAppearance = {
    theme: string
    surface_mode: string
    page_width?: string
    file_icons: { set: string; extensions: Record<string, string> }
  }
  type AppearancePatch = { theme?: ThemeId; surface_mode?: SurfaceMode; page_width?: PageWidthPreset }
  type AppearanceState = { theme: ThemeId; surface_mode: SurfaceMode; page_width: string; file_icons: WorkspaceAppearance['file_icons'] }
  type TreeApi = {
    ping: () => Promise<string>
    get_settings: () => Promise<{ workspaces: string[]; blocked_extensions: string[]; editor: { autosave: boolean; auto_reload: boolean; reload_notice: boolean } }>
    set_editor_preference: (name: string, value: boolean) => Promise<void>
    get_workspace_settings: (path: string) => Promise<{ automatic_link_update: boolean; appearance: WorkspaceAppearance; new_notes_folder: string }>
    set_new_items_folder: (id: string, folder: string) => Promise<void>
    search_workspace: (id: string, query: string) => Promise<{ items: { path: string; is_directory: boolean }[]; truncated: boolean; error: string | null }>
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
    set_open_notes?: (id: string, paths: string[]) => Promise<void>
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
    page_width: '74ch',
    file_icons: { set: 'minimal', extensions: {} },
  }
  const pageWidthPresets: { value: PageWidthPreset; label: string; title: string }[] = [
    { value: '74ch', label: 'Readable', title: 'Readable width (74ch)' },
    { value: '96ch', label: 'Wide', title: 'Wide width (96ch)' },
    { value: '100%', label: 'Full', title: 'Full width (100%)' },
  ]
  const defaultEditorPreferences: EditorPreferences = { autosave: false, auto_reload: true, reload_notice: true }
  const settingsTabKey = '__acornwiki_settings__'
  const imageExtensions = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.avif']
  const codeExtensions = ['.json', '.yaml', '.yml', '.toml', '.py', '.ts', '.tsx', '.js', '.jsx', '.css', '.html', '.sh', '.sql']

  let ready = $state(false)
  let message = $state('Waiting for backend...')
  let workspaces = $state<string[]>([])
  let workspacesLoaded = $state(false)
  let workspaceMessage = $state('')
  let blockedExtensions = $state('')
  let blockedMessage = $state('')
  let editorPreferences = $state<EditorPreferences>(defaultEditorPreferences)
  let editorPreferencesLoaded = $state(false)
  let editorPreferenceSaving = $state<Partial<Record<keyof EditorPreferences, boolean>>>({})
  let settingsMessage = $state('')
  let loadingWorkspace = $state(false)
  let selectedWorkspace = $state<string | null>(null)
  let workspaceId = $state<string | null>(null)
  let appearance = $state<AppearanceState>(defaultAppearance)
  let sessionSurface = $state<SurfaceMode | null>(null)
  let sessionPageWidth = $state<PageWidthPreset | null>(null)
  let effectiveSurface = $derived(sessionSurface ?? appearance.surface_mode)
  let effectivePageWidth = $derived(sessionPageWidth ?? appearance.page_width)
  let viewMenuOpen = $state(false)
  let appearanceSaving = $state(false)
  let settingsOpen = $state(false)
  let filePanelOpen = $state(true)
  let outlineOpen = $state(true)
  let outlineFilter = $state('')
  let tabOutlines = $state<Record<string, FlatOutlineHeading[]>>({})
  let expandedOutlineIds = $state<string[]>([])
  let lastOutlineSignature = ''
  let workspacePicker: HTMLDetailsElement | undefined = $state()
  let noteTabs = $state<NoteTab[]>([])
  let activeTabKey = $state<string | null>(null)
  let settingsTabOpen = $state(false)
  let tabStatuses = $state<Record<string, EditorStatus>>({})
  let editors: Record<string, NoteEditor | undefined> = {}
  let bulkClose = $state<{ paths: string[]; error: string; busy: boolean; cancelable: boolean } | null>(null)
  let bulkCloseChoice: ((choice: 'save' | 'discard' | 'cancel') => void) | undefined
  let bulkCancelRequested = false
  let tabMutationQueue: Promise<void> = Promise.resolve()
  let tabsLocked = $state(false)
  let closeRequestActive = false
  let selectedNote = $derived(noteTabs.find((tab) => tab.key === activeTabKey)?.path ?? null)
  let workspaceName = $derived(selectedWorkspace ? (selectedWorkspace.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? selectedWorkspace) : '')
  let navHistory = $state<string[]>([])
  let navIndex = $state(-1)
  let canGoBack = $derived(navIndex > 0)
  let canGoForward = $derived(navIndex >= 0 && navIndex < navHistory.length - 1)
  let settingsTabActive = $derived(activeTabKey === settingsTabKey)
  let openTabs = $derived(noteTabs.length > 0 || settingsTabOpen)
  let activeOutline = $derived(activeTabKey && activeTabKey !== settingsTabKey ? (tabOutlines[activeTabKey] ?? []) : [])
  let outlineTree = $derived(buildOutlineTree(activeOutline))
  let filterIsActive = $derived(Boolean(outlineFilter.trim()))
  let filteredOutline = $derived(filterOutline(outlineTree, outlineFilter.trim().toLowerCase()))
  let expandableOutlineIds = $derived(collectExpandableIds(outlineTree))
  let allOutlineExpanded = $derived(expandableOutlineIds.length > 0 && expandableOutlineIds.every((id) => expandedOutlineIds.includes(id)))
  let showRightPanel = $derived(Boolean(selectedNote) && outlineOpen)
  let latestRevision = -1
  let sortMode = $state<SortMode>('alphabetic')
  let directories = $state.raw<Record<string, DirectorySnapshot>>({})
  let expandedFolders = $state<string[]>([])
  let creationFolder = $state('')
  let creationFolderInput = $state('.')
  let folderSettingsMessage = $state('')
  let treeQuery = $state('')
  let searchResults = $state<{ path: string; is_directory: boolean }[]>([])
  let searchStatus = $state('')
  let searchToken = 0
  let searchTimer: ReturnType<typeof setTimeout> | undefined
  let creating = $state(false)
  let moving = $state(false)
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
    document.documentElement.dataset.surface = effectiveSurface
    document.documentElement.style.setProperty('--page-width', effectivePageWidth)
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
      if (detail?.key === 'file_tree_revision') { void syncTree(); scheduleNoteChecks() }
      if (detail?.key === 'note_revision') scheduleNoteChecks()
      if (detail?.key === 'close_request') void closeWindow()
    }
    async function closeWindow() {
      if (moving || closeRequestActive || tabsLocked) return
      closeRequestActive = true
      try {
        const closed = await serializeTabAction(async () => await closeAllTabsInMutation())
        if (closed) await window.pywebview?.api?.finish_close()
      } finally { closeRequestActive = false }
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
    function onFocus() { void refreshTree(null); scheduleNoteChecks() }
    function onKeydown(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return
      const instance = activeTabKey && activeTabKey !== settingsTabKey ? editors[activeTabKey] : undefined
      if (!instance) return
      event.preventDefault()
      if (tabsLocked) return
      void instance.save()
    }
    function beforeUnload(event: BeforeUnloadEvent) {
      if (!noteTabs.some((tab) => editors[tab.key]?.hasUnsavedWork())) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('pywebviewready', updateBridgeStatus)
    window.addEventListener('focus', onFocus)
    window.addEventListener('keydown', onKeydown)
    window.addEventListener('beforeunload', beforeUnload)
    updateBridgeStatus()
    return () => {
      window.removeEventListener('pywebviewready', updateBridgeStatus)
      window.removeEventListener('focus', onFocus)
      window.removeEventListener('keydown', onKeydown)
      window.removeEventListener('beforeunload', beforeUnload)
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
      editorPreferences = settings.editor ?? defaultEditorPreferences
      editorPreferencesLoaded = true
      workspacesLoaded = true
    }
    catch (error) { workspaceMessage = 'Could not load workspaces.'; console.error(error) }
  }

  function serializeTabAction<T>(action: () => Promise<T>): Promise<T> {
    const pending = tabMutationQueue.then(action, action)
    tabMutationQueue = pending.then(() => undefined, () => undefined)
    return pending
  }

  function notePathKey(path: string): string {
    const normalized = path.replace(/\\/g, '/').replace(/\/{2,}/g, '/').replace(/^(?:\.\/)+/, '')
    const windows = /^win/i.test(navigator.platform || '') || /windows/i.test(navigator.userAgent)
    return windows ? normalized.toLowerCase() : normalized
  }

  async function updateOpenNotes(tabs: NoteTab[], id = workspaceId): Promise<boolean> {
    const api = window.pywebview?.api
    if (!api || !id || !api.set_open_notes) return true
    try {
      await api.set_open_notes(id, tabs.map((tab) => tab.path))
      return true
    } catch (error) {
      workspaceMessage = 'Could not update the open note list.'
      console.error(error)
      return false
    }
  }

  $effect(() => {
    const signature = `${selectedNote ?? ''}\n${activeOutline.map((heading) => `${heading.id}:${heading.level}`).join('\n')}`
    if (signature === lastOutlineSignature) return
    lastOutlineSignature = signature
    expandedOutlineIds = collectExpandableIds(outlineTree)
  })

  function buildOutlineTree(headings: FlatOutlineHeading[]): OutlineHeading[] {
    const roots: OutlineHeading[] = []
    const parents: OutlineHeading[] = []
    for (const heading of headings) {
      const node: OutlineHeading = { ...heading, children: [] }
      while (parents.length && parents[parents.length - 1].level >= node.level) parents.pop()
      const parent = parents[parents.length - 1]
      if (parent) parent.children.push(node)
      else roots.push(node)
      parents.push(node)
    }
    return roots
  }

  function filterOutline(nodes: OutlineHeading[], query: string): OutlineHeading[] {
    if (!query) return nodes
    return nodes.flatMap((node) => {
      const children = filterOutline(node.children, query)
      return node.label.toLowerCase().includes(query) || children.length ? [{ ...node, children }] : []
    })
  }

  function collectExpandableIds(nodes: OutlineHeading[]): string[] {
    const ids: string[] = []
    for (const node of nodes) {
      if (node.children.length) {
        ids.push(node.id, ...collectExpandableIds(node.children))
      }
    }
    return ids
  }

  function updateTabOutline(key: string, headings: FlatOutlineHeading[]) {
    tabOutlines = { ...tabOutlines, [key]: headings }
  }

  function toggleOutlinePanel() {
    outlineOpen = !outlineOpen
  }

  function toggleOutlineNode(id: string) {
    expandedOutlineIds = expandedOutlineIds.includes(id)
      ? expandedOutlineIds.filter((item) => item !== id)
      : [...expandedOutlineIds, id]
  }

  function toggleAllOutline() {
    expandedOutlineIds = allOutlineExpanded ? [] : [...expandableOutlineIds]
  }

  function jumpToHeading(event: MouseEvent, id: string) {
    event.preventDefault()
    if (!activeTabKey || activeTabKey === settingsTabKey) return
    editors[activeTabKey]?.jumpToHeading(id)
  }

  function updateTabStatus(key: string, status: EditorStatus) {
    tabStatuses = { ...tabStatuses, [key]: status }
  }

  async function checkRegisteredNotes() {
    await tick()
    await Promise.allSettled(noteTabs.map(async (tab) => {
      const instance = editors[tab.key]
      if (!instance) return
      await instance.waitForLoad()
      await instance.checkExternalNow()
    }))
  }

  function scheduleNoteChecks() {
    for (const tab of noteTabs) editors[tab.key]?.scheduleExternalCheck()
  }

  function recordNavigation(path: string) {
    if (navIndex >= 0 && navHistory[navIndex] === path) return
    navHistory = [...navHistory.slice(0, navIndex + 1), path]
    navIndex = navHistory.length - 1
  }

  async function openNote(path: string, fragment?: string, options?: { newTab?: boolean; fromHistory?: boolean }) {
    const requestedWorkspaceId = workspaceId
    const newTab = Boolean(options?.newTab)
    const fromHistory = Boolean(options?.fromHistory)
    return serializeTabAction(async () => {
      if (!requestedWorkspaceId || requestedWorkspaceId !== workspaceId || tabsLocked) return
      const key = notePathKey(path)
      const existing = noteTabs.find((tab) => tab.key === key)
      if (existing) {
        activeTabKey = existing.key
        if (!fromHistory) recordNavigation(existing.path)
        if (fragment) {
          await tick()
          await editors[existing.key]?.navigateToFragment(fragment)
        }
        return
      }
      const currentIndex = !newTab && activeTabKey && activeTabKey !== settingsTabKey
        ? noteTabs.findIndex((tab) => tab.key === activeTabKey)
        : -1
      const currentTab = currentIndex >= 0 ? noteTabs[currentIndex] : undefined
      const currentEditor = currentTab ? editors[currentTab.key] : undefined
      const currentStatus = currentTab ? (currentEditor?.closeStatus() ?? tabStatuses[currentTab.key]) : undefined
      const canReplace = Boolean(
        currentTab &&
        !currentEditor?.hasUnsavedWork() &&
        !currentStatus?.dirty &&
        !currentStatus?.saving &&
        !currentStatus?.conflict,
      )
      const next = canReplace && currentTab
        ? noteTabs.map((tab, index) => (index === currentIndex ? { key, path } : tab))
        : [...noteTabs, { key, path }]
      if (!(await updateOpenNotes(next))) return
      if (canReplace && currentTab) {
        const nextStatuses = { ...tabStatuses }
        delete nextStatuses[currentTab.key]
        tabStatuses = nextStatuses
        const nextOutlines = { ...tabOutlines }
        delete nextOutlines[currentTab.key]
        tabOutlines = nextOutlines
      }
      noteTabs = next
      activeTabKey = key
      if (!fromHistory) recordNavigation(path)
      await checkRegisteredNotes()
      if (fragment) await editors[key]?.navigateToFragment(fragment)
    })
  }

  function activateNote(key: string) {
    if (tabsLocked) return
    const tab = noteTabs.find((item) => item.key === key)
    if (!tab) return
    activeTabKey = key
    recordNavigation(tab.path)
  }

  function navigateBack() {
    if (!canGoBack || tabsLocked) return
    navIndex -= 1
    const target = navHistory[navIndex]
    if (target) void openNote(target, undefined, { fromHistory: true })
  }

  function navigateForward() {
    if (!canGoForward || tabsLocked) return
    navIndex += 1
    const target = navHistory[navIndex]
    if (target) void openNote(target, undefined, { fromHistory: true })
  }

  function chooseBulkClose(choice: 'save' | 'discard' | 'cancel') {
    if (choice === 'cancel' && bulkClose && !bulkClose.cancelable) return
    if (bulkClose?.busy && choice !== 'cancel') return
    const resolve = bulkCloseChoice
    bulkCloseChoice = undefined
    if (choice === 'cancel' && !resolve) bulkCancelRequested = true
    resolve?.(choice)
  }

  async function closeAllTabsInMutation(): Promise<boolean> {
    const id = workspaceId
    if (!id) return true
    if (noteTabs.length === 0) return await updateOpenNotes([], id)
    tabsLocked = true
    bulkCancelRequested = false
    const inFlight = noteTabs.filter((tab) => editors[tab.key]?.closeStatus().saving)
    bulkClose = inFlight.length ? { paths: [], error: '', busy: true, cancelable: true } : null
    try {
      await Promise.all(inFlight.map((tab) => editors[tab.key]?.waitForSave()))
      if (bulkCancelRequested) return false
      await tick()
      const dirtyTabs = noteTabs.filter((tab) => {
        const status = editors[tab.key]?.closeStatus() ?? tabStatuses[tab.key]
        return status?.dirty || status?.saving
      })
      if (dirtyTabs.length) {
        bulkClose = { paths: dirtyTabs.map((tab) => tab.path), error: '', busy: false, cancelable: true }
        let choice = await new Promise<'save' | 'discard' | 'cancel'>((resolve) => { bulkCloseChoice = resolve })
        while (choice !== 'cancel') {
          bulkClose = { paths: dirtyTabs.map((tab) => tab.path), error: '', busy: true, cancelable: true }
          if (choice === 'save') {
            const results = await Promise.all(noteTabs.map(async (tab) => {
              const instance = editors[tab.key]
              const status = instance?.closeStatus() ?? tabStatuses[tab.key]
              if (!instance || (!status?.dirty && !status?.saving)) return true
              return instance.save()
            }))
            if (bulkCancelRequested) return false
            await tick()
            if (bulkCancelRequested) return false
            const unresolved = noteTabs.filter((tab) => {
              const status = editors[tab.key]?.closeStatus() ?? tabStatuses[tab.key]
              return status?.dirty || status?.saving
            })
            if (results.every(Boolean) && unresolved.length === 0) break
            bulkClose = {
              paths: unresolved.length ? unresolved.map((tab) => tab.path) : dirtyTabs.map((tab) => tab.path),
              error: 'Some notes could not be saved. Resolve their conflicts or discard all changes to close.',
              busy: false,
              cancelable: true,
            }
            choice = await new Promise<'save' | 'discard' | 'cancel'>((resolve) => { bulkCloseChoice = resolve })
            continue
          }
          await Promise.all(noteTabs.map((tab) => editors[tab.key]?.discardForClose()))
          if (bulkCancelRequested) return false
          break
        }
        if (choice === 'cancel') return false
      } else bulkClose = null
      if (bulkClose) bulkClose = { ...bulkClose, busy: true, cancelable: false }
      if (!(await updateOpenNotes([], id))) {
        bulkClose = { paths: noteTabs.map((tab) => tab.path), error: 'The open note list could not be cleared. Notes are still open.', busy: false, cancelable: true }
        return false
      }
      noteTabs = []
      tabStatuses = {}
      tabOutlines = {}
      activeTabKey = settingsTabOpen ? settingsTabKey : null
      return true
    } finally {
      bulkCloseChoice = undefined
      bulkCancelRequested = false
      bulkClose = null
      tabsLocked = false
    }
  }

  async function closeNoteTab(key: string) {
    const requestedWorkspaceId = workspaceId
    return serializeTabAction(async () => {
      if (tabsLocked || requestedWorkspaceId !== workspaceId) return
      const tab = noteTabs.find((item) => item.key === key)
      const instance = editors[key]
      if (!tab || !instance) return
      tabsLocked = true
      const previousActiveKey = activeTabKey
      const previousIndex = noteTabs.findIndex((item) => item.key === key)
      activeTabKey = key
      await tick()
      try {
        if (!(await instance.prepareClose())) return
        const next = noteTabs.filter((item) => item.key !== key)
        if (!(await updateOpenNotes(next))) { instance.resumeAfterFailedClose(); return }
        noteTabs = next
        const nextStatuses = { ...tabStatuses }
        delete nextStatuses[key]
        tabStatuses = nextStatuses
        const nextOutlines = { ...tabOutlines }
        delete nextOutlines[key]
        tabOutlines = nextOutlines
        activeTabKey = previousActiveKey === key
          ? (next[Math.min(previousIndex, next.length - 1)]?.key ?? (settingsTabOpen ? settingsTabKey : null))
          : (previousActiveKey && (next.some((item) => item.key === previousActiveKey) || previousActiveKey === settingsTabKey) ? previousActiveKey : (next[Math.min(previousIndex, next.length - 1)]?.key ?? null))
        await checkRegisteredNotes()
      } finally { tabsLocked = false }
    })
  }

  function openSettingsTab() {
    if (tabsLocked) return
    settingsTabOpen = true
    activeTabKey = settingsTabKey
    settingsOpen = false
  }

  function closeSettingsTab() {
    if (tabsLocked) return
    settingsTabOpen = false
    if (activeTabKey === settingsTabKey) activeTabKey = noteTabs[0]?.key ?? null
  }

  async function setEditorPreference(key: keyof EditorPreferences, value: boolean) {
    const api = window.pywebview?.api
    if (!api || editorPreferenceSaving[key]) return
    editorPreferenceSaving = { ...editorPreferenceSaving, [key]: true }
    settingsMessage = ''
    try {
      await api.set_editor_preference(key, value)
      editorPreferences = { ...editorPreferences, [key]: value }
    }
    catch (error) {
      settingsMessage = 'Could not save editor settings.'
      console.error(error)
    } finally { editorPreferenceSaving = { ...editorPreferenceSaving, [key]: false } }
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
    return serializeTabAction(async () => {
      const api = window.pywebview?.api
      if (!api || appearanceSaving) return
      if (!(await closeAllTabsInMutation())) return
      if (workspacePicker) workspacePicker.open = false
      loadingWorkspace = true
      workspaceMessage = ''
      selectedWorkspace = null
      workspaceId = null
      navHistory = []
      navIndex = -1
      appearance = { ...defaultAppearance, file_icons: { set: 'minimal', extensions: {} } }
      latestRevision = -1
      directories = {}
      expandedFolders = []
      creationFolder = ''
      creationFolderInput = '.'
      treeQuery = ''
      searchToken++
      scrollTop = 0
      if (viewport) viewport.scrollTop = 0
      sortMode = 'alphabetic'
      try {
        const preferences = await api.get_workspace_settings(path)
        const snapshot = await api.open_workspace(path)
        workspaceId = snapshot.workspace_id
        selectedWorkspace = path
        automaticLinkUpdate = preferences.automatic_link_update !== false
        creationFolder = !preferences.new_notes_folder || preferences.new_notes_folder === '.' ? '' : preferences.new_notes_folder
        creationFolderInput = preferences.new_notes_folder || '.'
        appearance = normalizeAppearance(preferences.appearance)
        applySnapshot(snapshot)
        await syncTree()
      } catch (error) {
        workspaceMessage = `Could not open workspace: ${path}. Check the folder and its settings.`
        console.error(error)
      } finally { loadingWorkspace = false }
    })
  }
  function toggleFilePanel() {
    filePanelOpen = !filePanelOpen
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
    const rawWidth = typeof value.page_width === 'string' ? value.page_width : defaultAppearance.page_width
    const widthMatch = /^(\d+(?:\.\d+)?)(ch|rem|px|vw|%)$/.exec(rawWidth)
    const pageWidth = widthMatch && Number(widthMatch[1]) > 0 ? rawWidth : defaultAppearance.page_width
    return {
      theme: value.theme === 'warm-paper' ? 'warm-paper' : 'warm-charcoal',
      surface_mode: value.surface_mode === 'seamless' ? 'seamless' : 'framed',
      page_width: pageWidth,
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
    const requestedWorkspaceId = workspaceId
    return serializeTabAction(async () => {
      const api = window.pywebview?.api
      const id = requestedWorkspaceId
      if (!api || !id || id !== workspaceId || moving) return
      const destination = window.prompt('Move or rename to (workspace-relative path):', source)
      if (destination === null || destination === source) return
      moving = true
      workspaceMessage = ''
      try {
        if (!(await closeAllTabsInMutation())) return
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
        await syncTree()
        workspaceMessage = result.failures.length
          ? `Moved, but some notes could not be updated: ${result.failures.map(item => `${item.path}: ${item.error}`).join('; ')}`
          : `Moved. Updated links in ${result.updated.length} notes.`
      } catch (error) {
        workspaceMessage = `Could not complete the move: ${String(error)}`
        console.error(error)
      } finally { moving = false }
    })
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
  async function saveCreationFolder() {
    const id = workspaceId
    if (!id) return
    try {
      const folder = creationFolderInput.trim() || '.'
      await window.pywebview?.api?.set_new_items_folder(id, folder)
      if (id !== workspaceId) return
      creationFolder = folder === '.' ? '' : folder
      creationFolderInput = folder
      folderSettingsMessage = 'Default folder saved.'
    } catch (error) { folderSettingsMessage = 'Choose an existing folder inside the workspace.'; console.error(error) }
  }
  function searchFiles() {
    clearTimeout(searchTimer)
    const token = ++searchToken
    const id = workspaceId
    const query = treeQuery.trim()
    searchResults = []
    searchStatus = query ? 'Searching...' : ''
    if (!id || !query) return
    searchTimer = setTimeout(async () => {
      try {
        const result = await window.pywebview?.api?.search_workspace(id, query)
        if (!result || token !== searchToken || id !== workspaceId) return
        searchResults = result.items
        searchStatus = result.error ? 'Some folders could not be searched.' : result.truncated ? 'Showing the first 500 results.' : result.items.length ? '' : 'No matches.'
      } catch (error) { if (token === searchToken) searchStatus = 'Search failed.'; console.error(error) }
    }, 250)
  }
  async function openSearchResult(path: string, isDirectory: boolean, newTab = false) {
    if (!isDirectory) {
      if (path.toLowerCase().endsWith('.md')) await openNote(path, undefined, { newTab })
      else await openTreeFile(path)
      return
    }
    const id = workspaceId
    const api = window.pywebview?.api
    if (!id || !api) return
    try {
      const parts = path.split('/')
      for (let i = 1; i <= parts.length; i++) {
        const folder = parts.slice(0, i).join('/')
        if (!expandedFolders.includes(folder)) {
          applySnapshot(await api.set_directory_visible(id, folder, true))
          if (id !== workspaceId) return
          expandedFolders = [...expandedFolders, folder]
        }
      }
      treeQuery = ''
      searchFiles()
    } catch (error) { searchStatus = 'Could not open the folder.'; console.error(error) }
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
      <button class="menu-item" disabled title="This menu is not available yet">File</button>
      <button class="menu-item" disabled title="This menu is not available yet">Edit</button>
      <details class="view-menu" bind:open={viewMenuOpen}>
        <summary class="menu-item">View</summary>
        <div class="view-menu-content" role="group" aria-label="Session view options">
          <strong>Document surface</strong>
          <button aria-pressed={effectiveSurface === 'framed'} onclick={() => { sessionSurface = 'framed'; viewMenuOpen = false }}>Framed</button>
          <button aria-pressed={effectiveSurface === 'seamless'} onclick={() => { sessionSurface = 'seamless'; viewMenuOpen = false }}>Seamless</button>
          <strong class="view-menu-divider">Page width</strong>
          {#each pageWidthPresets as preset (preset.value)}
            <button aria-pressed={effectivePageWidth === preset.value} title={preset.title} onclick={() => { sessionPageWidth = preset.value; viewMenuOpen = false }}>{preset.label}</button>
          {/each}
          <button class="view-menu-reset" onclick={() => { sessionSurface = null; sessionPageWidth = null; viewMenuOpen = false }}>Use workspace default</button>
        </div>
      </details>
      <button class="menu-item" disabled title="This menu is not available yet">Navigate</button>
      <button class="menu-item" disabled title="This menu is not available yet">Help</button>
    </div>
  </header>

  <div class="workspace-layout" class:files-hidden={!filePanelOpen} class:outline-open={showRightPanel}>
    <nav class="activity-bar" aria-label="Application tools">
      <button class="activity-button" class:active={filePanelOpen} onclick={toggleFilePanel} aria-label="Files" aria-pressed={filePanelOpen} title="Files"><Icon name="folder" /></button>
      <button class="activity-button" disabled aria-label="Graph view" title="Graph view is not available yet"><Icon name="network" /></button>
      <button class="activity-button" disabled aria-label="Command palette" title="Command palette is not available yet"><Icon name="terminal" /></button>
      <div class="activity-spacer"></div>
      <details bind:open={settingsOpen} class="settings-menu">
        <summary class="activity-button" aria-label="Settings" title="Settings"><Icon name="settings" /></summary>
        <div class="settings-content">
          <strong>Quick settings</strong>
          <button class="text-button quick-settings-open" onclick={openSettingsTab}>Open Settings</button>
          <label class="quick-setting"><input type="checkbox" checked={editorPreferences.autosave} disabled={!editorPreferencesLoaded || editorPreferenceSaving.autosave} onchange={(event) => setEditorPreference('autosave', (event.currentTarget as HTMLInputElement).checked)} /> Autosave</label>
          <label class="quick-setting"><input type="checkbox" checked={editorPreferences.auto_reload} disabled={!editorPreferencesLoaded || editorPreferenceSaving.auto_reload} onchange={(event) => setEditorPreference('auto_reload', (event.currentTarget as HTMLInputElement).checked)} /> Auto-reload unchanged notes</label>
        </div>
      </details>
    </nav>

    {#if filePanelOpen}
      <aside class="file-tree" aria-label="Workspace file tree" inert={moving}>
        <div class="tree-heading">
          <h2>Files</h2>
          <div class="tree-actions">
            <label class="sort-control" title="Sort files"><Icon name="sort" /><select aria-label="Sort files" value={sortMode} onchange={changeSortMode} disabled={!workspaceId}><option value="alphabetic">Alphabetical</option><option value="modified">Modified</option></select></label>
            <button class="icon-button" onclick={() => refreshTree(null)} disabled={!workspaceId} aria-label="Refresh file tree" title="Refresh file tree"><Icon name="refresh" /></button>
            <button class="icon-button" disabled={!workspaceId || creating} onclick={() => createEntry('note')} aria-label="New note" title="New note"><Icon name="file-plus" /></button>
            <button class="icon-button" disabled={!workspaceId || creating} onclick={() => createEntry('folder')} aria-label="New folder" title="New folder"><Icon name="folder-plus" /></button>
          </div>
        </div>
        {#if workspaceId}
          <input class="file-search" type="search" aria-label="Search files" placeholder="Search files..." bind:value={treeQuery} oninput={(event) => { treeQuery = event.currentTarget.value; searchFiles() }} />
          {#if treeQuery.trim()}
            <div class="tree-viewport search-results">
              {#if searchStatus}<p class="tree-status-message" role="status">{searchStatus}</p>{/if}
              {#each searchResults as result (result.path)}
                <button
                  class="search-result"
                  title={result.path}
                  onclick={(event) => openSearchResult(result.path, result.is_directory, event.ctrlKey || event.metaKey)}
                  onmousedown={(event) => { if (event.button === 1 && !result.is_directory && result.path.toLowerCase().endsWith('.md')) event.preventDefault() }}
                  onauxclick={(event) => { if (event.button === 1 && !result.is_directory && result.path.toLowerCase().endsWith('.md')) { event.preventDefault(); void openNote(result.path, undefined, { newTab: true }) } }}
                ><Icon name={result.is_directory ? 'folder' : fileIconFor(result.path)} /><span>{result.path}</span></button>
              {/each}
            </div>
          {:else}
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
                        <button
                          class="tree-file tree-note"
                          class:selected={notePathKey(row.path) === activeTabKey}
                          aria-current={notePathKey(row.path) === activeTabKey ? 'true' : undefined}
                          title={row.item.name}
                          onclick={(event) => openNote(row.path, undefined, { newTab: event.ctrlKey || event.metaKey })}
                          onmousedown={(event) => { if (event.button === 1) event.preventDefault() }}
                          onauxclick={(event) => { if (event.button === 1) { event.preventDefault(); void openNote(row.path, undefined, { newTab: true }) } }}
                          onkeydown={handleTreeKeydown}
                        >
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
          {/if}
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

    <section class="document-host" aria-label="Open documents">
      {#if openTabs}
        <div class="document-tabs">
          <div class="document-tabs-list" role="tablist" aria-label="Open tabs">
            {#each noteTabs as tab (tab.key)}
              {@const tabName = tab.path.split(/[\\/]/).pop() ?? tab.path}
              {@const status = tabStatuses[tab.key]}
              <div class="document-tab" class:active={activeTabKey === tab.key}>
                <button
                  class="document-tab-select"
                  role="tab"
                  aria-selected={activeTabKey === tab.key}
                  title={tab.path}
                  disabled={tabsLocked}
                  onclick={() => activateNote(tab.key)}
                  onmousedown={(event) => { if (event.button === 1) event.preventDefault() }}
                  onauxclick={(event) => { if (event.button === 1 && !tabsLocked) { event.preventDefault(); void closeNoteTab(tab.key) } }}
                >
                  <span class="document-tab-title">{tabName}</span>
                  {#if status?.conflict}
                    <span class="tab-dirty-indicator conflict" title={status.dirty ? 'Unsaved changes and external conflict' : 'File changed externally'} aria-label={status.dirty ? 'Unsaved changes and external conflict' : 'External conflict'}>●</span>
                  {:else if status?.dirty}
                    <span class="tab-dirty-indicator" title="Unsaved changes" aria-label="Unsaved changes">●</span>
                  {/if}
                </button>
                <button class="document-tab-close" aria-label={`Close ${tabName}`} title={`Close ${tab.path}`} disabled={tabsLocked} onclick={() => closeNoteTab(tab.key)}><span aria-hidden="true">×</span></button>
              </div>
            {/each}
            {#if settingsTabOpen}
              <div class="document-tab settings-document-tab" class:active={settingsTabActive}>
                <button
                  class="document-tab-select"
                  role="tab"
                  aria-selected={settingsTabActive}
                  disabled={tabsLocked}
                  onclick={openSettingsTab}
                  onmousedown={(event) => { if (event.button === 1) event.preventDefault() }}
                  onauxclick={(event) => { if (event.button === 1 && !tabsLocked) { event.preventDefault(); closeSettingsTab() } }}
                >Settings</button>
                <button class="document-tab-close" aria-label="Close Settings" title="Close Settings" disabled={tabsLocked} onclick={closeSettingsTab}><span aria-hidden="true">×</span></button>
              </div>
            {/if}
          </div>
          {#if selectedNote}
            <div class="document-tabs-actions">
              <button class="icon-button outline-toggle-btn" onclick={toggleOutlinePanel} aria-label="Toggle contents panel" aria-pressed={outlineOpen} title="Toggle contents panel"><Icon name="panel-right" /></button>
            </div>
          {/if}
        </div>
        <div class="document-host-body" inert={Boolean(bulkClose)}>
          {#each noteTabs as tab (tab.key)}
            <NoteEditor
              bind:this={editors[tab.key]}
              tabKey={tab.key}
              notePath={tab.path}
              active={activeTabKey === tab.key}
              freezeEditors={tabsLocked}
              workspaceId={workspaceId ?? ''}
              {workspaceName}
              {editorPreferences}
              {canGoBack}
              {canGoForward}
              onNavigateBack={navigateBack}
              onNavigateForward={navigateForward}
              {workspaceMessage}
              onOpenNote={openNote}
              onStatusChange={updateTabStatus}
              onOutlineChange={updateTabOutline}
            />
          {/each}
          {#if settingsTabOpen}
            <section class="settings-tab" class:inactive={!settingsTabActive} aria-label="Settings" aria-hidden={!settingsTabActive} inert={!settingsTabActive}>
              <header class="settings-tab-heading"><h1>Settings</h1><p>Application and workspace preferences</p></header>
              <div class="settings-tab-scroll">
                {#if settingsMessage}<p class="settings-message" role="alert">{settingsMessage}</p>{/if}
                <section class="settings-section">
                  <h2>Editor</h2>
                  <label><input type="checkbox" checked={editorPreferences.autosave} disabled={!editorPreferencesLoaded || editorPreferenceSaving.autosave} onchange={(event) => setEditorPreference('autosave', (event.currentTarget as HTMLInputElement).checked)} /> Save changes automatically</label>
                  <label><input type="checkbox" checked={editorPreferences.auto_reload} disabled={!editorPreferencesLoaded || editorPreferenceSaving.auto_reload} onchange={(event) => setEditorPreference('auto_reload', (event.currentTarget as HTMLInputElement).checked)} /> Reload notes when the disk version changes and there are no local edits</label>
                  <label><input type="checkbox" checked={editorPreferences.reload_notice} disabled={!editorPreferencesLoaded || editorPreferenceSaving.reload_notice} onchange={(event) => setEditorPreference('reload_notice', (event.currentTarget as HTMLInputElement).checked)} /> Show a notice after reloading a changed note</label>
                </section>
                <section class="settings-section">
                  <h2>Appearance</h2>
                  <div class="settings-appearance-row"><span>Theme</span><div class="appearance-group" role="group" aria-label="Theme">
                    <button class:active={appearance.theme === 'warm-charcoal'} aria-pressed={appearance.theme === 'warm-charcoal'} disabled={!workspaceId || appearanceSaving} onclick={() => setAppearance({ theme: 'warm-charcoal' })}>Warm Charcoal</button>
                    <button class:active={appearance.theme === 'warm-paper'} aria-pressed={appearance.theme === 'warm-paper'} disabled={!workspaceId || appearanceSaving} onclick={() => setAppearance({ theme: 'warm-paper' })}>Warm Paper</button>
                  </div></div>
                  <div class="settings-appearance-row"><span>Default document surface</span><div class="appearance-group surface-group" role="group" aria-label="Default document surface">
                    <button class:active={appearance.surface_mode === 'framed'} aria-pressed={appearance.surface_mode === 'framed'} disabled={!workspaceId || appearanceSaving} onclick={() => setAppearance({ surface_mode: 'framed' })}>Framed</button>
                    <button class:active={appearance.surface_mode === 'seamless'} aria-pressed={appearance.surface_mode === 'seamless'} disabled={!workspaceId || appearanceSaving} onclick={() => setAppearance({ surface_mode: 'seamless' })}>Seamless</button>
                  </div></div>
                  <div class="settings-appearance-row"><span>Default page width</span><div class="appearance-group width-group" role="group" aria-label="Default page width">
                    {#each pageWidthPresets as preset (preset.value)}
                      <button class:active={appearance.page_width === preset.value} aria-pressed={appearance.page_width === preset.value} disabled={!workspaceId || appearanceSaving} title={preset.title} onclick={() => setAppearance({ page_width: preset.value })}>{preset.label}</button>
                    {/each}
                  </div></div>
                </section>
                <section class="settings-section">
                  <h2>Workspace files</h2>
                  <p>Default folder for new notes and folders, relative to the workspace. Use . for the workspace root.</p>
                  <label>New items folder <input aria-label="New items folder" type="text" bind:value={creationFolderInput} disabled={!workspaceId} /></label>
                  <button class="text-button" onclick={saveCreationFolder} disabled={!workspaceId}>Save folder</button>
                  {#if folderSettingsMessage}<p role="status" class="settings-message">{folderSettingsMessage}</p>{/if}
                </section>
                <section class="settings-section">
                  <h2>File access</h2>
                  <p>Extensions listed here stay visible in the file tree but cannot be opened directly.</p>
                  <label class="settings-blocked-label">Blocked extensions <textarea bind:value={blockedExtensions} rows="4" placeholder=".exe, .bat"></textarea></label>
                  <button class="text-button" onclick={saveBlockedExtensions}>Save extensions</button>
                  {#if blockedMessage}<p role="status" class="settings-message">{blockedMessage}</p>{/if}
                </section>
                <section class="settings-section">
                  <h2>Connection</h2>
                  <div class="settings-connection-row">
                    <p class="connection-status" aria-live="polite"><span class="connection-dot" class:connected={ready}></span>{message}</p>
                    <button class="text-button" onclick={ping} disabled={!ready}>Check connection</button>
                  </div>
                </section>
              </div>
            </section>
          {/if}
        </div>
      {:else if workspaceId}
        <section class="empty-state"><h2>No note selected</h2><p>Choose a Markdown file from the workspace tree.</p>{#if workspaceMessage}<p class="workspace-message" role="alert">{workspaceMessage}</p>{/if}</section>
      {:else if selectedWorkspace}
        <section class="empty-state"><h2>No note selected</h2><p>Choose a workspace to see its files.</p>{#if workspaceMessage}<p class="workspace-message" role="alert">{workspaceMessage}</p>{/if}</section>
      {:else}
        <section class="empty-state" aria-live="polite">
          {#if workspaceMessage}<p class="workspace-message" role="alert">{workspaceMessage}</p>{/if}
          <h2>Select a workspace</h2><p>Choose a workspace from the file panel.</p>
        </section>
      {/if}
    </section>

    {#if showRightPanel}
      <aside class="note-outline" aria-label="Contents">
        <div class="outline-heading">
          <h2 class="outline-title">Contents</h2>
          <button class="outline-collapse-all" aria-label={filterIsActive || allOutlineExpanded ? 'Collapse all headings' : 'Expand all headings'} title={filterIsActive ? 'Clear the filter to change heading expansion' : allOutlineExpanded ? 'Collapse all headings' : 'Expand all headings'} aria-expanded={filterIsActive || allOutlineExpanded} disabled={expandableOutlineIds.length === 0 || filterIsActive} onclick={toggleAllOutline}>{filterIsActive || allOutlineExpanded ? '−' : '+'}</button>
        </div>
        <input class="outline-filter" type="search" aria-label="Filter headings" placeholder="Filter headings..." bind:value={outlineFilter} />
        {#if activeOutline.length === 0}
          <p class="outline-empty">No headings in this note.</p>
        {:else if filteredOutline.length === 0}
          <p class="outline-empty">No headings match this filter.</p>
        {:else}
          <nav class="outline-nav" aria-label="Note headings">
            <ul>
              {@render renderHeadings(filteredOutline, 0, filterIsActive)}
            </ul>
          </nav>
        {/if}
      </aside>
    {/if}
  </div>
  <footer class="status-bar">
    <span>{selectedWorkspace ?? 'No workspace selected'}</span>
    <span>{selectedNote ?? 'No note open'} · {appearance.theme === 'warm-paper' ? 'Warm Paper' : 'Warm Charcoal'} · {effectiveSurface === 'seamless' ? 'Seamless' : 'Framed'}</span>
  </footer>
  {#if bulkClose}
    <div class="bulk-close-backdrop">
      <div class="bulk-close-dialog" role="alertdialog" aria-modal="true" aria-labelledby="bulk-close-title" aria-describedby="bulk-close-description">
        <h2 id="bulk-close-title">Close all open notes?</h2>
        <p id="bulk-close-description">Choose what to do with unsaved edits before the tabs close.</p>
        {#if bulkClose.paths.length}
          <ul class="bulk-close-list">{#each bulkClose.paths as path}<li>{path}</li>{/each}</ul>
        {:else if bulkClose.busy}
          <p class="bulk-close-wait">Finishing a save already in progress…</p>
        {/if}
        {#if bulkClose.error}<p class="bulk-close-error" role="alert">{bulkClose.error}</p>{/if}
        {#if !bulkClose.cancelable}<p class="bulk-close-wait" aria-live="polite">Closing note tabs…</p>
        {:else if bulkClose.busy && bulkClose.paths.length}<p class="bulk-close-wait" aria-live="polite">Saving open notes…</p>{/if}
        <div class="bulk-close-actions">
          <button class="text-button" disabled={!bulkClose.cancelable} onclick={() => chooseBulkClose('cancel')}>Cancel</button>
          <button class="text-button" disabled={bulkClose.busy || !bulkClose.paths.length} onclick={() => chooseBulkClose('discard')}>Discard all</button>
          <button class="primary-button" disabled={bulkClose.busy || !bulkClose.paths.length} onclick={() => chooseBulkClose('save')}>Save all</button>
        </div>
      </div>
    </div>
  {/if}
</main>

{#snippet renderHeadings(nodes: OutlineHeading[], depth: number, filterIsActive: boolean)}
  {#each nodes as heading (heading.id)}
    {@const hasChildren = heading.children.length > 0}
    {@const expanded = filterIsActive || expandedOutlineIds.includes(heading.id)}
    <li class="outline-row" style={`padding-left: ${depth * 14}px`}>
      {#if hasChildren}
        <button class="outline-caret" aria-label={expanded ? `Collapse ${heading.label}` : `Expand ${heading.label}`} aria-expanded={expanded} disabled={filterIsActive} onclick={() => toggleOutlineNode(heading.id)}>{expanded ? '▾' : '▸'}</button>
      {:else}
        <span class="outline-caret-spacer" aria-hidden="true"></span>
      {/if}
      <a class="outline-link outline-level-{heading.level}" href={`#${heading.id}`} onclick={(event) => jumpToHeading(event, heading.id)} title={heading.label}>{heading.label}</a>
    </li>
    {#if hasChildren && expanded}
      {@render renderHeadings(heading.children, depth + 1, filterIsActive)}
    {/if}
  {/each}
{/snippet}
