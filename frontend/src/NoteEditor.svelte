<script lang="ts">
  import { onMount, tick, untrack } from 'svelte'
  import { Compartment, EditorState } from '@codemirror/state'
  import { EditorView } from '@codemirror/view'
  import { basicSetup } from 'codemirror'
  import { markdown } from '@codemirror/lang-markdown'
  import { marked } from 'marked'
  import DOMPurify from 'dompurify'
  import { openWorkspaceFile } from './fileActions'

  type EditorPreferences = { autosave: boolean; auto_reload: boolean; reload_notice: boolean }
  type EditorStatus = { dirty: boolean; saving: boolean; conflict: boolean }
  let {
    workspaceId,
    tabKey,
    notePath,
    active,
    freezeEditors = false,
    editorPreferences,
    onOpenNote,
    onStatusChange,
    workspaceMessage = '',
  }: {
    workspaceId: string
    tabKey: string
    notePath: string
    active: boolean
    freezeEditors?: boolean
    editorPreferences: EditorPreferences
    onOpenNote: (path: string, fragment?: string) => void | Promise<void>
    onStatusChange: (key: string, status: EditorStatus) => void
    workspaceMessage?: string
  } = $props()
  let host: HTMLDivElement
  let panel: HTMLElement
  let view: EditorView
  const editableCompartment = new Compartment()
  const readOnlyCompartment = new Compartment()
  let path = $state<string | null>(null)
  let text = $state('')
  let savedText = $state('')
  let version = $state('')
  let mode = $state<'source' | 'read'>('source')
  let message = $state('')
  let error = $state('')
  let conflict = $state(false)
  let missing = $state(false)
  let diskVersion = $state('')
  let diskText = $state('')
  let saving = $state(false)
  let opening = false
  let disposed = false
  let loadingPromise: Promise<void> = Promise.resolve()
  let prompt = $state(false)
  let chooseClose: ((choice: 'save' | 'discard' | 'cancel') => void) | undefined
  let operation = 0
  let externalTimer: ReturnType<typeof setTimeout> | undefined
  let saveTimer: ReturnType<typeof setTimeout> | undefined
  let savePromise: Promise<boolean> | undefined
  let mediaUrl = $state('')
  let outlineFilter = $state('')
  let dirty = $derived(text !== savedText)
  let rendered = $derived(mode === 'read' ? renderMarkdown(text, path, mediaUrl) : '')
  let outline = $derived(extractOutline(rendered))
  let filterIsActive = $derived(Boolean(outlineFilter.trim()))

  type FlatOutlineHeading = { id: string; label: string; level: number }
  type OutlineHeading = FlatOutlineHeading & { children: OutlineHeading[] }

  let outlineOpen = $state(true)
  let expandedOutlineIds = $state<string[]>([])
  let outlineTree = $derived(buildOutlineTree(outline))
  let filteredOutline = $derived(filterOutline(outlineTree, outlineFilter.trim().toLowerCase()))
  let expandableOutlineIds = $derived(collectExpandableIds(outlineTree))
  let allOutlineExpanded = $derived(expandableOutlineIds.length > 0 && expandableOutlineIds.every((id) => expandedOutlineIds.includes(id)))

  $effect(() => {
    const key = tabKey
    const status = { dirty, saving, conflict }
    untrack(() => onStatusChange(key, status))
  })

  $effect(() => {
    const canAutoSave = editorPreferences.autosave && !prompt && !freezeEditors && !conflict && Boolean(path) && dirty
    if (!canAutoSave) clearTimeout(saveTimer)
    else scheduleSave()
  })

  $effect(() => {
    const readOnly = prompt || freezeEditors
    const currentView = view
    if (!currentView) return
    currentView.dispatch({ effects: [
      editableCompartment.reconfigure(EditorView.editable.of(!readOnly)),
      readOnlyCompartment.reconfigure(EditorState.readOnly.of(readOnly)),
    ] })
  })

  $effect(() => {
    if (mode !== 'read') return
    const signature = `${path ?? ''}\n${outline.map((heading) => `${heading.id}:${heading.level}`).join('\n')}`
    if (signature === lastOutlineSignature) return
    lastOutlineSignature = signature
    expandedOutlineIds = collectExpandableIds(outlineTree)
  })

  let lastOutlineSignature = ''

  function extractOutline(html: string): FlatOutlineHeading[] {
    if (!html) return []
    const template = document.createElement('template')
    template.innerHTML = html
    return Array.from(template.content.querySelectorAll<HTMLHeadingElement>('h1, h2, h3, h4, h5, h6'))
      .map((heading) => ({ id: heading.id, label: heading.textContent?.trim() ?? '', level: Number(heading.tagName.slice(1)) }))
      .filter((heading) => heading.id && heading.label)
  }

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

  function toggleOutlineNode(id: string) {
    expandedOutlineIds = expandedOutlineIds.includes(id)
      ? expandedOutlineIds.filter((item) => item !== id)
      : [...expandedOutlineIds, id]
  }

  function toggleAllOutline() {
    expandedOutlineIds = allOutlineExpanded ? [] : [...expandableOutlineIds]
  }

  function toggleOutlinePanel() {
    outlineOpen = !outlineOpen
  }

  function jumpToHeading(event: MouseEvent, id: string) {
    event.preventDefault()
    panel.querySelector('.note-read')?.querySelector(`#${CSS.escape(id)}`)?.scrollIntoView({ block: 'start' })
  }

  export async function navigateToFragment(fragment: string) {
    if (!fragment) return
    mode = 'read'
    await tick()
    panel.querySelector('.note-read')?.querySelector(`#${CSS.escape(fragment)}`)?.scrollIntoView({ block: 'start' })
  }

  function renderMarkdown(content: string, note: string | null, endpoint: string): string {
    const template = document.createElement('template')
    template.innerHTML = DOMPurify.sanitize(marked.parse(content, { async: false }))
    const headings = new Map<string, number>()
    const usedIds = new Set<string>()
    for (const heading of template.content.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
      const slug = (heading.textContent ?? '').trim().toLowerCase().replace(/[^\p{L}\p{N}_\-\s]/gu, '').replace(/\s/g, '-') || 'section'
      let count = headings.get(slug) ?? 0
      let id = count ? `${slug}-${count}` : slug
      while (usedIds.has(id)) {
        count += 1
        id = `${slug}-${count}`
      }
      usedIds.add(id)
      headings.set(slug, count + 1)
      heading.id = id
    }
    for (const image of template.content.querySelectorAll('img')) {
      const src = image.getAttribute('src') ?? ''
      if (/^https?:\/\//i.test(src)) continue
      if (!note || !endpoint || !src || /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(src)) {
        image.removeAttribute('src')
        continue
      }
      const params = new URLSearchParams({ workspace: workspaceId, note, src })
      image.setAttribute('src', `${endpoint}?${params}`)
    }
    return template.innerHTML
  }

  async function followLink(event: MouseEvent) {
    const element = event.target as Element
    const link = element.closest('a')
    if (!link || !path) return
    event.preventDefault()
    const href = link.getAttribute('href') ?? ''
    const api = window.pywebview?.api
    if (!api) return
    error = ''
    try {
      if (/^https?:\/\//i.test(href)) await api.open_external_link(href)
      else {
        const target = await api.resolve_note_link(workspaceId, path, href)
        if (disposed) return
        if (!target.path.toLowerCase().endsWith('.md')) {
          if (target.fragment) {
            error = 'Opening a specific section of this file is not supported.'
            return
          }
          await openWorkspaceFile(workspaceId, target.path)
          return
        }
        if (target.path !== path) await onOpenNote(target.path, target.fragment)
        else if (target.fragment) await navigateToFragment(target.fragment)
      }
    } catch (reason) { error = 'Could not open the link.'; console.error(reason) }
  }

  function linkHandler(node: HTMLElement) {
    node.addEventListener('click', followLink)
    return { destroy: () => node.removeEventListener('click', followLink) }
  }

  function setDocument(content: string) {
    const lineSeparator = content.includes('\r\n') ? '\r\n' : '\n'
    view.setState(EditorState.create({ doc: content, extensions: [...extensions(), EditorState.lineSeparator.of(lineSeparator)] }))
    text = content
  }

  function extensions() {
    return [basicSetup, markdown(), EditorView.lineWrapping, editableCompartment.of(EditorView.editable.of(!prompt && !freezeEditors)), readOnlyCompartment.of(EditorState.readOnly.of(prompt || freezeEditors)), EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        text = update.state.sliceDoc()
        message = ''
        scheduleSave()
      }
    })]
  }

  onMount(() => {
    void window.pywebview?.api?.media_url?.(workspaceId).then((url) => { mediaUrl = url }).catch(console.error)
    view = new EditorView({ state: EditorState.create({ extensions: extensions() }), parent: host })
    loadingPromise = loadNote()
    return () => {
      disposed = true
      operation += 1
      clearTimeout(saveTimer)
      clearTimeout(externalTimer)
      view.destroy()
    }
  })

  function scheduleSave() {
    clearTimeout(saveTimer)
    if (editorPreferences.autosave && !prompt && !freezeEditors && dirty && path && !conflict) {
      saveTimer = setTimeout(() => {
        if (!prompt && !freezeEditors) void save()
      }, 1000)
    }
  }

  export async function prepareClose(): Promise<boolean> {
    if (prompt) return false
    if (opening) {
      await loadingPromise
      if (disposed) return false
    }
    if (savePromise && !(await savePromise)) return false
    if (!dirty) return true
    prompt = true
    const choice = await new Promise<'save' | 'discard' | 'cancel'>((resolve) => { chooseClose = resolve })
    prompt = false
    chooseClose = undefined
    if (choice === 'cancel') return false
    if (choice === 'discard') { clearTimeout(saveTimer); return true }
    return await save() && text === savedText
  }

  export async function waitForLoad(): Promise<void> {
    await loadingPromise
  }

  export async function waitForSave(): Promise<boolean> {
    return savePromise ? await savePromise : true
  }

  export function resumeAfterFailedClose() {
    scheduleSave()
  }

  async function loadNote() {
    if (opening || disposed) return
    const api = window.pywebview?.api
    if (!api) return
    const token = ++operation
    opening = true
    error = ''
    try {
      const note = await api.read_note(workspaceId, notePath)
      if (token !== operation) return
      clearTimeout(saveTimer)
      path = note.path
      outlineFilter = ''
      version = note.version
      savedText = note.content
      setDocument(note.content)
      conflict = false
      missing = false
      message = ''
      scheduleExternalCheck()
    } catch (reason) { if (token === operation) { error = 'Could not open or watch the note.'; console.error(reason); scheduleSave() } }
    finally { opening = false }
  }

  export async function save(expected = version): Promise<boolean> {
    if (savePromise) return savePromise
    if (!path || !window.pywebview?.api || (conflict && expected === version)) return false
    const api = window.pywebview.api
    const currentPath = path
    const content = text
    const token = operation
    clearTimeout(saveTimer)
    saving = true
    error = ''
    savePromise = (async () => {
      try {
        const result = await api.save_note(workspaceId, currentPath, content, expected)
        if (token !== operation) return false
        version = result.version
        savedText = content
        conflict = false
        missing = false
        message = text === content ? 'Saved.' : ''
        if (text !== savedText) scheduleSave()
        return true
      } catch (reason) {
        if (disposed || token !== operation) return false
        console.error(reason)
        await checkExternal()
        if (!conflict) error = 'Could not save the note.'
        return false
      } finally { saving = false; savePromise = undefined }
    })()
    return savePromise
  }

  export function scheduleExternalCheck() {
    clearTimeout(externalTimer)
    externalTimer = setTimeout(() => void checkExternal(), 250)
  }

  export async function checkExternalNow() {
    clearTimeout(externalTimer)
    await checkExternal()
  }

  export function hasUnsavedWork(): boolean {
    return dirty || saving
  }

  export function closeStatus(): EditorStatus {
    return { dirty, saving, conflict }
  }

  export async function discardForClose(): Promise<void> {
    clearTimeout(saveTimer)
    if (savePromise) await savePromise
    clearTimeout(saveTimer)
  }

  async function checkExternal() {
    const api = window.pywebview?.api
    if (disposed || !path || !api) return
    const token = operation
    const checkedVersion = version
    try {
      const note = await api.read_note(workspaceId, path)
      if (token !== operation || checkedVersion !== version) return
      if (note.version === version) {
        const resolved = conflict
        conflict = false
        missing = false
        if (resolved) { message = ''; if (dirty) scheduleSave() }
        return
      }
      diskVersion = note.version
      diskText = note.content
      missing = false
      if (!dirty && editorPreferences.auto_reload && !saving) {
        version = note.version
        savedText = note.content
        setDocument(note.content)
        conflict = false
        message = editorPreferences.reload_notice ? 'File changed externally and was reloaded.' : ''
      } else {
        clearTimeout(saveTimer)
        conflict = true
        message = 'File changed externally. Your editor content was kept.'
      }
    } catch (reason) {
      if (token !== operation || checkedVersion !== version) return
      clearTimeout(saveTimer)
      conflict = true
      missing = true
      message = 'File cannot be read; it may have been moved or deleted. Your editor content was kept.'
      console.error(reason)
    }
  }

  function loadDisk() {
    if (dirty && !window.confirm('Discard unsaved changes and load the version on disk?')) return
    version = diskVersion
    savedText = diskText
    setDocument(diskText)
    conflict = false
    message = 'Loaded the version on disk.'
  }

</script>

<section class="note-panel" class:inactive={!active} aria-label="Markdown editor" aria-hidden={!active} inert={!active} bind:this={panel} data-note-path={notePath}>
  <div class="note-toolbar">
    <strong>{path ?? 'Select a Markdown file'}</strong>
    {#if path}<span>{dirty ? 'Unsaved' : 'Saved'}</span>
      <button onclick={() => mode = 'source'} aria-pressed={mode === 'source'}>Source</button>
      <button onclick={() => mode = 'read'} aria-pressed={mode === 'read'}>Read</button>
      <button onclick={() => save()} disabled={!dirty || saving || conflict || freezeEditors || prompt}>Save</button>
      {#if mode === 'read'}<button class="outline-toggle-btn" onclick={toggleOutlinePanel} aria-label="Toggle contents panel" aria-pressed={outlineOpen} title="Toggle contents panel">Contents</button>{/if}
    {/if}
  </div>
  <div class="note-body-layout">
    <div class="note-scroll">
      <div class="note-sheet">
        {#if !path}
          <div class="note-empty-state">
            <h2>No note selected</h2>
            <p>Choose a Markdown file from the workspace tree.</p>
          </div>
        {/if}
        <div class="note-content" hidden={!path || mode !== 'source'} bind:this={host}></div>
        {#if path && mode === 'read'}<article class="note-content note-read" use:linkHandler>{@html rendered}</article>{/if}
      </div>
    </div>
    {#if path && mode === 'read' && outlineOpen}
      <aside class="note-outline" aria-label="Contents">
        <div class="outline-heading">
          <h2 class="outline-title">Contents</h2>
          <button class="outline-collapse-all" aria-label={filterIsActive || allOutlineExpanded ? 'Collapse all headings' : 'Expand all headings'} title={filterIsActive ? 'Clear the filter to change heading expansion' : allOutlineExpanded ? 'Collapse all headings' : 'Expand all headings'} aria-expanded={filterIsActive || allOutlineExpanded} disabled={expandableOutlineIds.length === 0 || filterIsActive} onclick={toggleAllOutline}>{filterIsActive || allOutlineExpanded ? '−' : '+'}</button>
        </div>
        <input class="outline-filter" type="search" aria-label="Filter headings" placeholder="Filter headings..." bind:value={outlineFilter} />
        {#if outline.length === 0}
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
  {#if message || error || conflict || prompt || workspaceMessage}
    <div class="note-notices">
      {#if message && !conflict}<p role="status" class="status-notice">{message}</p>{/if}
      {#if error}<p role="alert" class="note-error">{error}</p>{/if}
      {#if workspaceMessage}<p role={workspaceMessage.startsWith('Could not') ? 'alert' : 'status'} class="workspace-message">{workspaceMessage}</p>{/if}
      {#if conflict}
        <div role="alert" class="note-conflict">
          <span>{message || (missing ? 'The note is missing or cannot be read.' : 'The note changed outside acornwiki.')}</span>
          {#if !missing}
            <button onclick={loadDisk}>Load disk version</button>
            {#if dirty}<button onclick={() => { if (window.confirm('Replace the disk version with the editor content?')) void save(diskVersion) }}>Overwrite with editor version</button>{/if}
          {/if}
          <button onclick={() => void checkExternal()}>Check again</button>
        </div>
      {/if}
      {#if prompt}
        <div role="alert" class="note-conflict">You have unsaved changes.
          <button onclick={() => chooseClose?.('save')}>Save</button>
          <button onclick={() => chooseClose?.('discard')}>Discard</button>
          <button onclick={() => chooseClose?.('cancel')}>Cancel</button>
        </div>
      {/if}
    </div>
  {/if}
</section>

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
