<script lang="ts">
  import { onMount, tick, untrack } from 'svelte'
  import { Compartment, EditorState } from '@codemirror/state'
  import { EditorView } from '@codemirror/view'
  import { ensureSyntaxTree } from '@codemirror/language'
  import { Lexer, Marked } from 'marked'
  import DOMPurify from 'dompurify'
  import Icon from './Icon.svelte'
  import PopupMenu from './PopupMenu.svelte'
  import { openWorkspaceFile } from './fileActions'
  import { createMarkdownEditorExtensions, highlightCodeElement, lineNumbersExtension } from './markdownEditor'
  import type { EditorPreferences, EditorStatus, FlatOutlineHeading } from './sharedTypes'

  // Disable Setext headings so typing "-" under a line or list item never turns it into H2,
  // and Source/Read stay consistent (ATX "#" headings only).
  const markdownParser = new Marked({
    tokenizer: {
      lheading() {
        return undefined
      },
    },
  })

  function extractCodeLanguage(codeEl: Element | null): string {
    const className = codeEl?.getAttribute('class') ?? ''
    return className.match(/(?:^|\s)language-(\S+)/)?.[1] ?? ''
  }

  let {
    workspaceId,
    workspaceName = '',
    tabKey,
    notePath,
    active,
    freezeEditors = false,
    editorPreferences,
    showLineNumbers = false,
    canGoBack = false,
    canGoForward = false,
    onNavigateBack,
    onNavigateForward,
    onOpenNote,
    onStatusChange,
    onOutlineChange,
  }: {
    workspaceId: string
    workspaceName?: string
    tabKey: string
    notePath: string
    active: boolean
    freezeEditors?: boolean
    editorPreferences: EditorPreferences
    showLineNumbers?: boolean
    canGoBack?: boolean
    canGoForward?: boolean
    onNavigateBack?: () => void
    onNavigateForward?: () => void
    onOpenNote: (path: string, fragment?: string, options?: { newTab?: boolean }) => void | Promise<void>
    onStatusChange: (key: string, status: EditorStatus) => void
    onOutlineChange?: (key: string, headings: FlatOutlineHeading[]) => void
  } = $props()
  let host: HTMLDivElement
  let panel: HTMLElement
  let view: EditorView
  const editableCompartment = new Compartment()
  const readOnlyCompartment = new Compartment()
  const lineNumbersCompartment = new Compartment()
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
  let outlineReady = $state(false)
  let disposed = false
  let loadingPromise: Promise<void> = Promise.resolve()
  let prompt = $state(false)
  let chooseClose: ((choice: 'save' | 'discard' | 'cancel') => void) | undefined
  let operation = 0
  let externalTimer: ReturnType<typeof setTimeout> | undefined
  let saveTimer: ReturnType<typeof setTimeout> | undefined
  let savePromise: Promise<boolean> | undefined
  let externalCheckPromise: Promise<void> | undefined
  let externalCheckPending = false
  let mediaUrl = $state('')
  let dirty = $derived(text !== savedText)
  let rendered = $derived(renderMarkdown(text, path, mediaUrl))
  let outline = $derived(extractOutline(rendered))
  let breadcrumb = $derived(buildBreadcrumb(path, workspaceName))

  function buildBreadcrumb(note: string | null, rootName: string): { prefix: string; file: string } {
    if (!note) return { prefix: '', file: '' }
    const parts = note.replace(/\\/g, '/').split('/').filter(Boolean)
    const file = parts.pop() ?? note
    const dirs = rootName ? [rootName, ...parts] : parts
    return {
      prefix: dirs.length ? `${dirs.join(' / ')} / ` : '',
      file,
    }
  }

  $effect(() => {
    const key = tabKey
    const status = { dirty, saving, conflict }
    untrack(() => onStatusChange(key, status))
  })

  $effect(() => {
    const key = tabKey
    const headings = outline
    if (outlineReady) untrack(() => onOutlineChange?.(key, headings))
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
    const enabled = showLineNumbers
    const currentView = view
    if (!currentView) return
    currentView.dispatch({ effects: lineNumbersCompartment.reconfigure(lineNumbersExtension(enabled)) })
  })

  function extractOutline(html: string): FlatOutlineHeading[] {
    if (!html) return []
    const template = document.createElement('template')
    template.innerHTML = html
    return Array.from(template.content.querySelectorAll<HTMLHeadingElement>('h1, h2, h3, h4, h5, h6'))
      .filter((heading) => !heading.closest('li, blockquote'))
      .map((heading) => ({ id: heading.id, label: heading.textContent?.trim() ?? '', level: Number(heading.tagName.slice(1)) }))
      .filter((heading) => heading.id && heading.label)
  }

  export function jumpToHeading(id: string) {
    if (mode === 'read') {
      panel.querySelector('.note-read')?.querySelector(`#${CSS.escape(id)}`)?.scrollIntoView({ block: 'start' })
      return
    }
    const heading = outline.find((item) => item.id === id)
    const tree = ensureSyntaxTree(view.state, view.state.doc.length, 1000)
    if (!tree || !heading) return
    const positions: number[] = []
    const links = markdownParser.lexer(text).links
    tree.iterate({ enter(node) {
      if (node.name === 'Blockquote' || node.name === 'ListItem') return false
      if (!/^ATXHeading[1-6]$/.test(node.name)) return
      const lexer = new Lexer(markdownParser.defaults)
      lexer.tokens.links = links
      const html = markdownParser.parser(lexer.lex(view.state.sliceDoc(node.from, node.to)))
      const template = document.createElement('template')
      template.innerHTML = DOMPurify.sanitize(html)
      const parsed = template.content.querySelector('h1,h2,h3,h4,h5,h6')
      if (parsed?.textContent?.trim() === heading.label && Number(parsed.tagName.slice(1)) === heading.level) positions.push(node.from)
    } })
    const matches = outline.filter((item) => item.label === heading.label && item.level === heading.level)
    // Avoid jumping to the wrong heading if raw HTML produced an indistinguishable entry.
    if (matches.length !== positions.length) return
    const position = positions[matches.findIndex((item) => item.id === id)]
    if (position === undefined) return
    view.dispatch({ selection: { anchor: position }, effects: EditorView.scrollIntoView(position, { y: 'start' }) })
    view.focus()
  }

  export async function navigateToFragment(fragment: string) {
    if (!fragment) return
    mode = 'read'
    await tick()
    panel.querySelector('.note-read')?.querySelector(`#${CSS.escape(fragment)}`)?.scrollIntoView({ block: 'start' })
  }

  function renderMarkdown(content: string, note: string | null, endpoint: string): string {
    const template = document.createElement('template')
    template.innerHTML = DOMPurify.sanitize(markdownParser.parse(content, { async: false }))
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
    for (const pre of template.content.querySelectorAll('pre')) {
      const code = pre.querySelector('code')
      const lang = extractCodeLanguage(code)
      const wrapper = document.createElement('div')
      wrapper.className = 'read-code-block'
      const header = document.createElement('div')
      header.className = 'read-code-header'
      const label = document.createElement('span')
      label.className = 'read-code-lang'
      label.textContent = lang || 'code'
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'read-code-copy'
      button.textContent = 'Copy'
      header.append(label, button)
      pre.parentNode?.insertBefore(wrapper, pre)
      wrapper.append(header, pre)
    }
    return template.innerHTML
  }

  async function handleReadClick(event: MouseEvent) {
    const element = event.target as Element
    const copyButton = element.closest<HTMLButtonElement>('.read-code-copy')
    if (copyButton && event.type === 'click') {
      event.preventDefault()
      const textToCopy = (copyButton.closest('.read-code-block')?.querySelector('pre code')?.textContent ?? '').replace(/\r?\n$/, '')
      try {
        await navigator.clipboard.writeText(textToCopy)
        copyButton.textContent = 'Copied'
        setTimeout(() => { if (copyButton.isConnected) copyButton.textContent = 'Copy' }, 1500)
      } catch (reason) { console.error(reason) }
      return
    }
    if (event.type === 'auxclick' && event.button !== 1) return
    const link = element.closest('a')
    if (!link || !path) return
    event.preventDefault()
    const newTab = event.button === 1 || event.ctrlKey || event.metaKey
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
        if (target.path !== path) await onOpenNote(target.path, target.fragment, { newTab })
        else if (target.fragment) await navigateToFragment(target.fragment)
      }
    } catch (reason) { error = 'Could not open the link.'; console.error(reason) }
  }

  function linkMousedown(event: MouseEvent) {
    if (event.button === 1 && (event.target as Element).closest('a')) event.preventDefault()
  }

  function highlightReadCodeBlocks(node: HTMLElement) {
    for (const codeEl of node.querySelectorAll<HTMLElement>('.read-code-block pre code')) {
      const lang = extractCodeLanguage(codeEl)
      if (lang) void highlightCodeElement(codeEl, lang).catch(console.error)
    }
  }

  function linkHandler(node: HTMLElement, _html: string) {
    node.addEventListener('click', handleReadClick)
    node.addEventListener('auxclick', handleReadClick)
    node.addEventListener('mousedown', linkMousedown)
    highlightReadCodeBlocks(node)
    return {
      update() {
        highlightReadCodeBlocks(node)
      },
      destroy: () => {
        node.removeEventListener('click', handleReadClick)
        node.removeEventListener('auxclick', handleReadClick)
        node.removeEventListener('mousedown', linkMousedown)
      },
    }
  }

  function handleSheetMousedown(event: MouseEvent) {
    if (event.button !== 0 || mode !== 'source' || !path || !view) return
    const target = event.target as HTMLElement | null
    if (!target) return
    if (target.closest('.cm-editor') || target.closest('button, a, input, summary')) return
    event.preventDefault()
    const end = view.state.doc.length
    view.dispatch({ selection: { anchor: end } })
    view.focus()
  }

  function setDocument(content: string) {
    const lineSeparator = content.includes('\r\n') ? '\r\n' : '\n'
    view.setState(EditorState.create({ doc: content, extensions: [...extensions(), EditorState.lineSeparator.of(lineSeparator)] }))
    text = content
  }

  function extensions() {
    return createMarkdownEditorExtensions([
      lineNumbersCompartment.of(lineNumbersExtension(showLineNumbers)),
      editableCompartment.of(EditorView.editable.of(!prompt && !freezeEditors)),
      readOnlyCompartment.of(EditorState.readOnly.of(prompt || freezeEditors)),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          text = update.state.sliceDoc()
          message = ''
          scheduleSave()
        }
      }),
    ])
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
      version = note.version
      savedText = note.content
      setDocument(note.content)
      conflict = false
      missing = false
      message = ''
      scheduleExternalCheck()
    } catch (reason) { if (token === operation) { error = 'Could not open or watch the note.'; console.error(reason); scheduleSave() } }
    finally { opening = false; if (!disposed && token === operation) outlineReady = true }
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
        message = ''
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
    externalCheckPending = true
    if (externalCheckPromise) return externalCheckPromise
    externalCheckPromise = (async () => {
      while (externalCheckPending && !disposed) {
        externalCheckPending = false
        await checkExternalOnce()
      }
    })()
    try { await externalCheckPromise }
    finally { externalCheckPromise = undefined }
  }

  async function checkExternalOnce() {
    const api = window.pywebview?.api
    if (disposed || !api) return
    if (!path) { await loadNote(); return }
    const token = operation
    const checkedVersion = version
    try {
      const note = await api.read_note(workspaceId, path)
      if (token !== operation) return
      if (checkedVersion !== version) { externalCheckPending = true; return }
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
      if (token !== operation) return
      if (checkedVersion !== version) { externalCheckPending = true; return }
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
    <div class="note-nav-buttons">
      <button class="icon-button note-nav-btn" onclick={() => onNavigateBack?.()} disabled={!canGoBack || freezeEditors} aria-label="Navigate back" title="Navigate back"><Icon name="arrow-left" size={14} /></button>
      <button class="icon-button note-nav-btn" onclick={() => onNavigateForward?.()} disabled={!canGoForward || freezeEditors} aria-label="Navigate forward" title="Navigate forward"><Icon name="arrow-right" size={14} /></button>
    </div>
    <div class="note-breadcrumb" title={path ?? ''}>
      {#if breadcrumb.prefix}<span class="note-breadcrumb-dir">{breadcrumb.prefix}</span>{/if}{#if breadcrumb.file}<span class="note-breadcrumb-file">{breadcrumb.file}</span>{/if}
    </div>
    {#if path}
      <button onclick={() => mode = 'source'} aria-pressed={mode === 'source'} aria-label="Source" title="Source"><Icon name="source-code" /></button>
      <button onclick={() => mode = 'read'} aria-pressed={mode === 'read'} aria-label="Read" title="Read"><Icon name="book-open" /></button>
      <button onclick={() => save()} disabled={!dirty || saving || conflict || freezeEditors || prompt} aria-label="Save" title="Save"><Icon name="save" /></button>
      <details class="note-more-menu">
        <summary aria-label="More note actions" title="More note actions"><Icon name="ellipsis" /></summary>
        <PopupMenu class="note-more-content">
          <button class="popup-menu-item" disabled title="Not available yet">Rename</button>
          <button class="popup-menu-item" disabled title="Not available yet">Copy</button>
        </PopupMenu>
      </details>
    {/if}
  </div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="note-scroll" onmousedown={handleSheetMousedown}>
    <div class="note-sheet">
      {#if !path}
        <div class="note-empty-state">
          <h2>No note selected</h2>
          <p>Choose a Markdown file from the workspace tree.</p>
        </div>
      {/if}
      <div class="note-content" hidden={!path || mode !== 'source'} bind:this={host}></div>
      {#if path && mode === 'read'}<article class="note-content note-read" use:linkHandler={rendered}>{@html rendered}</article>{/if}
    </div>
  </div>
  {#if message || error || conflict || prompt}
    <div class="note-notices">
      {#if message && !conflict}<p role="status" class="status-notice">{message}</p>{/if}
      {#if error}<p role="alert" class="note-error">{error}</p>{/if}
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
