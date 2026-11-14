<script module lang="ts">
  type SortMode = 'alphabetic' | 'modified'

  type FileTreeItem = {
    name: string
    is_directory: boolean
    modified_time: number
  }

  type TreeRow =
    | { kind: 'item'; path: string; item: FileTreeItem; depth: number }
    | { kind: 'status'; path: string; message: string; depth: number }

  declare global {
    interface Window {
      pywebview?: {
        api?: {
          ping: () => Promise<string>
          get_settings: () => Promise<{ workspaces: string[] }>
          get_workspace_settings: (path: string) => Promise<Record<string, unknown>>
          get_directory_items: (
            workspaceRoot: string,
            relativePath: string,
            sortMode: SortMode,
          ) => Promise<FileTreeItem[]>
        }
      }
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
  let workspaceSettings = $state<Record<string, unknown> | null>(null)

  let sortMode = $state<SortMode>('alphabetic')
  let treeItems = $state<Record<string, FileTreeItem[]>>({})
  let expandedFolders = $state<string[]>([])
  let loadingFolders = $state<string[]>([])
  let folderErrors = $state<Record<string, string>>({})
  let visibleTree = $derived(buildVisibleTree())

  onMount(() => {
    function updateBridgeStatus() {
      const api = window.pywebview?.api
      if (
        !ready &&
        typeof api?.ping === 'function' &&
        typeof api.get_settings === 'function' &&
        typeof api.get_workspace_settings === 'function' &&
        typeof api.get_directory_items === 'function'
      ) {
        ready = true
        message = 'Köprü hazır.'
        void loadWorkspaces()
      }
    }

    window.addEventListener('pywebviewready', updateBridgeStatus)
    updateBridgeStatus()

    return () => window.removeEventListener('pywebviewready', updateBridgeStatus)
  })

  async function ping() {
    const api = window.pywebview?.api
    if (!api) return

    try {
      message = await api.ping()
    } catch (error) {
      message = 'Backend ile bağlantı kurulamadı.'
      console.error(error)
    }
  }

  async function loadWorkspaces() {
    const api = window.pywebview?.api
    if (!api) return

    try {
      const settings = await api.get_settings()
      workspaces = settings.workspaces
      workspacesLoaded = true
    } catch (error) {
      workspaceMessage = 'Workspace listesi yüklenemedi.'
      console.error(error)
    }
  }

  async function selectWorkspace(path: string) {
    const api = window.pywebview?.api
    if (!api) return

    loadingWorkspace = true
    workspaceMessage = ''
    selectedWorkspace = null
    workspaceSettings = null
    treeItems = {}
    expandedFolders = []
    folderErrors = {}

    try {
      workspaceSettings = await api.get_workspace_settings(path)
      selectedWorkspace = path
      await loadDirectory('')
    } catch (error) {
      workspaceMessage = `Workspace açılamadı: ${path}. Klasörü ve ayarlarını kontrol et.`
      console.error(error)
    } finally {
      loadingWorkspace = false
    }
  }

  async function loadDirectory(relativePath: string) {
    const api = window.pywebview?.api
    if (!api || !selectedWorkspace) return

    loadingFolders = [...loadingFolders, relativePath]
    folderErrors = { ...folderErrors, [relativePath]: '' }

    try {
      const items = await api.get_directory_items(selectedWorkspace, relativePath, sortMode)
      treeItems = { ...treeItems, [relativePath]: items }
    } catch (error) {
      folderErrors = {
        ...folderErrors,
        [relativePath]: error instanceof Error ? error.message : String(error),
      }
      console.error(error)
    } finally {
      loadingFolders = loadingFolders.filter((path) => path !== relativePath)
    }
  }

  async function toggleFolder(relativePath: string) {
    if (expandedFolders.includes(relativePath)) {
      const descendantPrefix = `${relativePath}/`
      expandedFolders = expandedFolders.filter(
        (path) => path !== relativePath && !path.startsWith(descendantPrefix),
      )
      return
    }

    expandedFolders = [...expandedFolders, relativePath]
    await loadDirectory(relativePath)
  }

  async function changeSortMode(event: Event) {
    const target = event.currentTarget
    if (!(target instanceof HTMLSelectElement)) return

    const value = target.value
    if (value !== 'alphabetic' && value !== 'modified') return

    sortMode = value
    treeItems = {}
    expandedFolders = []
    folderErrors = {}
    if (selectedWorkspace) await loadDirectory('')
  }

  function buildVisibleTree(): TreeRow[] {
    const rows: TreeRow[] = []

    function addChildren(parentPath: string, depth: number) {
      for (const item of treeItems[parentPath] ?? []) {
        const itemPath = parentPath ? `${parentPath}/${item.name}` : item.name
        rows.push({ kind: 'item', path: itemPath, item, depth })

        if (!item.is_directory || !expandedFolders.includes(itemPath)) continue

        if (loadingFolders.includes(itemPath)) {
          rows.push({ kind: 'status', path: itemPath, message: 'Yükleniyor...', depth: depth + 1 })
        } else if (folderErrors[itemPath]) {
          rows.push({
            kind: 'status',
            path: itemPath,
            message: folderErrors[itemPath],
            depth: depth + 1,
          })
        } else {
          addChildren(itemPath, depth + 1)
        }
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
  {#if workspacesLoaded && workspaces.length === 0}
    <p>Kayıtlı workspace yok.</p>
  {:else if workspaces.length > 0}
    <ul>
      {#each workspaces as workspace}
        <li>
          <button
            onclick={() => selectWorkspace(workspace)}
            disabled={loadingWorkspace || loadingFolders.length > 0}
          >
            {workspace}
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  {#if selectedWorkspace && workspaceSettings}
    <p>Seçili workspace: <code>{selectedWorkspace}</code></p>
    <p>Workspace ayarları yüklendi.</p>

    <section class="file-tree" aria-label="Workspace dosya ağacı">
      <div class="tree-heading">
        <h2>Dosya ağacı</h2>
        <label>
          Sıralama
          <select
            value={sortMode}
            onchange={changeSortMode}
            disabled={loadingFolders.length > 0}
          >
            <option value="alphabetic">Alfabetik</option>
            <option value="modified">Son değişiklik</option>
          </select>
        </label>
      </div>

      {#if loadingFolders.includes('')}
        <p>Workspace kökü yükleniyor...</p>
      {:else if folderErrors['']}
        <p role="alert">{folderErrors['']}</p>
      {:else if (treeItems[''] ?? []).length === 0}
        <p>Bu workspace boş.</p>
      {:else}
        <ul class="tree-list">
          {#each visibleTree as row (row.kind === 'item' ? `item:${row.path}` : `status:${row.path}`)}
            <li>
              {#if row.kind === 'item'}
                <div class="tree-row" style={`padding-left: ${8 + row.depth * 20}px`}>
                  {#if row.item.is_directory}
                    <button
                      class="tree-folder"
                      onclick={() => toggleFolder(row.path)}
                      aria-expanded={expandedFolders.includes(row.path)}
                      disabled={loadingFolders.includes(row.path)}
                    >
                      <span aria-hidden="true">
                        {expandedFolders.includes(row.path) ? '▾' : '▸'}
                      </span>
                      <span>{row.item.name}</span>
                    </button>
                  {:else}
                    <span class="tree-file">{row.item.name}</span>
                  {/if}
                </div>
              {:else}
                <p class="tree-status" style={`padding-left: ${8 + row.depth * 20}px`}>
                  {row.message}
                </p>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  {/if}

  {#if workspaceMessage}
    <p role="alert">{workspaceMessage}</p>
  {/if}
</main>
