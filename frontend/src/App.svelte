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
  type TreeApi = {
    ping: () => Promise<string>
    get_settings: () => Promise<{ workspaces: string[] }>
    get_workspace_settings: (path: string) => Promise<Record<string, unknown>>
    open_workspace: (path: string) => Promise<TreeSnapshot>
    get_tree: (id: string) => Promise<TreeSnapshot>
    set_directory_visible: (id: string, path: string, visible: boolean) => Promise<TreeSnapshot>
    set_tree_sort: (id: string, sort: SortMode) => Promise<TreeSnapshot>
    refresh_tree: (id: string, path: string | null) => Promise<TreeSnapshot>
  }
  declare global {
    interface Window {
      pywebview?: { api?: TreeApi; state: EventTarget }
    }
  }
</script>

<script lang="ts">
  import { onMount } from 'svelte'

  let ready = $state(false)
  let message = $state('Köprü bekleniyor...')
  let workspaces = $state<string[]>([])
  let workspacesLoaded = $state(false)
  let workspaceMessage = $state('')
  let loadingWorkspace = $state(false)
  let selectedWorkspace = $state<string | null>(null)
  let workspaceId = $state<string | null>(null)
  let latestRevision = -1
  let sortMode = $state<SortMode>('alphabetic')
  let directories = $state<Record<string, DirectorySnapshot>>({})
  let expandedFolders = $state<string[]>([])
  let watcherError = $state<string | null>(null)
  let visibleTree = $derived(buildVisibleTree())
  let rootDirectory = $derived(directories[''])

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
      if (detail?.key === 'file_tree_revision') void syncTree()
    }
    function updateBridgeStatus() {
      const webview = window.pywebview
      if (!ready && webview?.api && webview.state) {
        subscribedState = webview.state
        subscribedState.addEventListener('change', handleStateChange)
        ready = true
        message = 'Köprü hazır.'
        void loadWorkspaces()
        void syncTree()
      }
    }
    function onFocus() { void refreshTree(null) }
    window.addEventListener('pywebviewready', updateBridgeStatus)
    window.addEventListener('focus', onFocus)
    updateBridgeStatus()
    return () => {
      window.removeEventListener('pywebviewready', updateBridgeStatus)
      window.removeEventListener('focus', onFocus)
      subscribedState?.removeEventListener('change', handleStateChange)
    }
  })

  async function ping() {
    try { message = await window.pywebview?.api?.ping() ?? message }
    catch (error) { message = 'Backend ile bağlantı kurulamadı.'; console.error(error) }
  }
  async function loadWorkspaces() {
    const api = window.pywebview?.api
    if (!api) return
    try { workspaces = (await api.get_settings()).workspaces; workspacesLoaded = true }
    catch (error) { workspaceMessage = 'Workspace listesi yüklenemedi.'; console.error(error) }
  }
  async function selectWorkspace(path: string) {
    const api = window.pywebview?.api
    if (!api) return
    loadingWorkspace = true
    workspaceMessage = ''
    selectedWorkspace = null
    workspaceId = null
    latestRevision = -1
    directories = {}
    expandedFolders = []
    sortMode = 'alphabetic'
    try {
      await api.get_workspace_settings(path)
      const snapshot = await api.open_workspace(path)
      workspaceId = snapshot.workspace_id
      selectedWorkspace = path
      applySnapshot(snapshot)
      await syncTree()
    } catch (error) {
      workspaceMessage = `Workspace açılamadı: ${path}. Klasörü ve ayarlarını kontrol et.`
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
    try {
      for (const folder of affected) applySnapshot(await api.set_directory_visible(id, folder, !closing))
    } catch (error) { if (id === workspaceId) { workspaceMessage = 'Klasör güncellenemedi.'; console.error(error) } }
  }
  async function changeSortMode(event: Event) {
    const target = event.currentTarget
    const api = window.pywebview?.api
    const id = workspaceId
    if (!(target instanceof HTMLSelectElement) || !api || !id) return
    if (target.value !== 'alphabetic' && target.value !== 'modified') return
    sortMode = target.value
    try { applySnapshot(await api.set_tree_sort(id, sortMode)) }
    catch (error) { workspaceMessage = 'Sıralama değiştirilemedi.'; console.error(error) }
  }
  async function refreshTree(path: string | null) {
    const api = window.pywebview?.api
    const id = workspaceId
    if (!api || !id) return
    try { applySnapshot(await api.refresh_tree(id, path)) }
    catch (error) { if (id === workspaceId) { workspaceMessage = 'Ağaç yenilenemedi.'; console.error(error) } }
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
        if (dir?.error) rows.push({ kind: 'status', path, message: `Yenilenemedi: ${dir.error}`, depth: depth + 1, error: true })
        else if (!dir || dir.loading || dir.stale) rows.push({ kind: 'status', path, message: dir?.items ? 'Yenileniyor...' : 'Yükleniyor...', depth: depth + 1, error: false })
      }
    }
    addChildren('', 0)
    return rows
  }
</script>

<main class="app-shell">
  <h1>acornwiki</h1>
  <button onclick={ping} disabled={!ready}>Bağlantıyı dene</button>
  <p aria-live="polite">{message}</p>
  <h2>Workspace'ler</h2>
  {#if workspacesLoaded && workspaces.length === 0}<p>Kayıtlı workspace yok.</p>{/if}
  {#if workspaces.length > 0}
    <ul>{#each workspaces as workspace}<li><button onclick={() => selectWorkspace(workspace)} disabled={loadingWorkspace}>{workspace}</button></li>{/each}</ul>
  {/if}
  {#if selectedWorkspace}
    <p>Seçili workspace: <code>{selectedWorkspace}</code></p>
    <section class="file-tree" aria-label="Workspace dosya ağacı">
      <div class="tree-heading">
        <h2>Dosya ağacı</h2>
        <button onclick={() => refreshTree(null)}>Yenile</button>
        <label>Sıralama <select value={sortMode} onchange={changeSortMode}><option value="alphabetic">Alfabetik</option><option value="modified">Son değişiklik</option></select></label>
      </div>
      {#if watcherError}<p role="alert">Dosya izleyici: {watcherError}. Elle yenileyin.</p>{/if}
      {#if rootDirectory?.error}<p role="alert">{rootDirectory.error} <button onclick={() => refreshTree('')}>Tekrar dene</button></p>{/if}
      {#if rootDirectory?.loading}<p aria-live="polite">{rootDirectory.items ? 'Yenileniyor...' : 'Workspace kökü yükleniyor...'}</p>{/if}
      {#if rootDirectory?.items?.length === 0 && !rootDirectory.loading}<p>Bu workspace boş.</p>{/if}
      <ul class="tree-list">
        {#each visibleTree as row (row.kind === 'item' ? `item:${row.path}` : `status:${row.path}`)}
          <li>
            {#if row.kind === 'item'}
              <div class="tree-row" style={`padding-left: ${8 + row.depth * 20}px`}>
                {#if row.item.is_directory}
                  <button class="tree-folder" onclick={() => toggleFolder(row.path)} aria-expanded={expandedFolders.includes(row.path)}>
                    <span aria-hidden="true">{expandedFolders.includes(row.path) ? '▾' : '▸'}</span><span>{row.item.name}</span>
                  </button>
                {:else}<span class="tree-file">{row.item.name}</span>{/if}
              </div>
            {:else}
              <p class="tree-status" style={`padding-left: ${8 + row.depth * 20}px`}>
                {row.message} {#if row.error}<button onclick={() => refreshTree(row.path)}>Tekrar dene</button>{/if}
              </p>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}
  {#if workspaceMessage}<p role="alert">{workspaceMessage}</p>{/if}
</main>
