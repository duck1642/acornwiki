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
  type TreeApi = {
    ping: () => Promise<string>
    get_settings: () => Promise<{ workspaces: string[]; blocked_extensions: string[]; editor: { autosave: boolean; auto_reload: boolean; reload_notice: boolean } }>
    set_editor_preference: (name: string, value: boolean) => Promise<void>
    get_workspace_settings: (path: string) => Promise<Record<string, unknown>>
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
  import NoteEditor from './NoteEditor.svelte'
  import { openWorkspaceFile } from './fileActions'
  import { planMoveLinks } from './markdownLinkPlan'

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
    if (editor && !(await editor.prepareClose())) return
    loadingWorkspace = true
    workspaceMessage = ''
    selectedWorkspace = null
    selectedNote = null
    workspaceId = null
    latestRevision = -1
    directories = {}
    expandedFolders = []
    creationFolder = ''
    scrollTop = 0
    if (viewport) viewport.scrollTop = 0
    sortMode = 'alphabetic'
    try {
      const preferences = await api.get_workspace_settings(path)
      automaticLinkUpdate = preferences.automatic_link_update !== false
      const snapshot = await api.open_workspace(path)
      workspaceId = snapshot.workspace_id
      selectedWorkspace = path
      applySnapshot(snapshot)
      await syncTree()
    } catch (error) {
      workspaceMessage = `Could not open workspace: ${path}. Check the folder and its settings.`
      console.error(error)
    } finally { loadingWorkspace = false }
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
    viewport.querySelector<HTMLButtonElement>(`[data-row-index="${next}"] button`)?.focus()
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
  <h1>acornwiki</h1>
  <button onclick={ping} disabled={!ready}>Test connection</button>
  <p aria-live="polite">{message}</p>
  <details>
    <summary>Blocked file extensions</summary>
    <p>Files with these extensions are shown in the tree but cannot be opened directly.</p>
    <label>Extensions <textarea bind:value={blockedExtensions} rows="3"></textarea></label>
    <button onclick={saveBlockedExtensions}>Save extensions</button>
    {#if blockedMessage}<p role="status">{blockedMessage}</p>{/if}
  </details>
  <h2>Workspaces</h2>
  {#if workspacesLoaded && workspaces.length === 0}<p>No saved workspaces.</p>{/if}
  {#if workspaces.length > 0}
    <ul class="workspace-list">{#each workspaces as workspace}<li><button onclick={() => selectWorkspace(workspace)} disabled={loadingWorkspace || moving}>{workspace}</button></li>{/each}</ul>
  {/if}
  {#if selectedWorkspace}
    <p>Selected workspace: <code>{selectedWorkspace}</code></p>
    <div class="workspace-layout">
    <section class="file-tree" aria-label="Workspace file tree" inert={moving}>
      <div class="tree-heading">
        <h2>File tree</h2>
        <button onclick={() => refreshTree(null)}>Refresh</button>
        <label>Sort <select value={sortMode} onchange={changeSortMode}><option value="alphabetic">Alphabetical</option><option value="modified">Modified</option></select></label>
      </div>
      <div class="tree-heading">
        <label>Destination <select bind:value={creationFolder}><option value="">Workspace root</option>{#each expandedFolders as folder}<option value={folder}>{folder}</option>{/each}</select></label>
        <button disabled={creating} onclick={() => createEntry('note')}>New note</button>
        <button disabled={creating} onclick={() => createEntry('folder')}>New folder</button>
      </div>
      {#if watcherError}<p role="alert">File watcher: {watcherError}. Refresh manually.</p>{/if}
      {#if rootDirectory?.error}<p role="alert">{rootDirectory.error} <button onclick={() => refreshTree('')}>Retry</button></p>{/if}
      {#if rootDirectory?.loading && (!rootDirectory.items || delayedRefreshes.includes(''))}<p aria-live="polite">{rootDirectory.items ? 'Refreshing...' : 'Loading workspace...'}</p>{/if}
      {#if rootDirectory?.items?.length === 0 && !rootDirectory.loading}<p>This workspace is empty.</p>{/if}
      <div class="tree-viewport" bind:this={viewport} bind:clientHeight={viewportHeight} tabindex="-1" aria-label="Scrollable file tree" onscroll={handleTreeScroll}>
        <ul class="tree-list">
          <li aria-hidden="true" style={`height: ${startRow * rowHeight}px`}></li>
          {#each renderedRows as row, index (row.kind === 'item' ? `item:${row.path}` : `status:${row.path}`)}
            <li class="tree-entry" data-row-index={startRow + index}>
              {#if row.kind === 'item'}
                <div class="tree-row" style={`padding-left: ${8 + row.depth * 20}px`}>
                  {#if row.item.is_directory}
                    <button class="tree-folder" onclick={() => toggleFolder(row.path)} onkeydown={handleTreeKeydown} aria-expanded={expandedFolders.includes(row.path)}>
                      <span aria-hidden="true">{expandedFolders.includes(row.path) ? '▾' : '▸'}</span><span title={row.item.name}>{row.item.name}</span>
                    </button>
                  {:else if row.path.toLowerCase().endsWith('.md')}
                    <button class="tree-file tree-note" class:selected={selectedNote === row.path} aria-current={selectedNote === row.path ? 'true' : undefined} title={row.item.name} onclick={() => editor?.open(row.path)} onkeydown={handleTreeKeydown}>{row.item.name}</button>
                  {:else}<button class="tree-file" title={row.item.name} onclick={() => openTreeFile(row.path)} onkeydown={handleTreeKeydown}>{row.item.name}</button>{/if}
                  <button aria-label={`Move or rename ${row.item.name}`} onclick={() => moveEntry(row.path)}>Move</button>
                </div>
              {:else}
                <div class="tree-status" style={`padding-left: ${8 + row.depth * 20}px`}>
                  <span title={row.message}>{row.message}</span> {#if row.error}<button onclick={() => refreshTree(row.path)} onkeydown={handleTreeKeydown}>Retry</button>{/if}
                </div>
              {/if}
            </li>
          {/each}
          <li aria-hidden="true" style={`height: ${(visibleTree.length - endRow) * rowHeight}px`}></li>
        </ul>
      </div>
    </section>
    {#if workspaceId && editorMounted}<NoteEditor bind:this={editor} bind:selectedNote {workspaceId} />{/if}
    </div>
  {/if}
  {#if workspaceMessage}<p role="alert">{workspaceMessage}</p>{/if}
</main>
