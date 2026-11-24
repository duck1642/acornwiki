<script lang="ts">
  import { onMount, tick, untrack } from 'svelte'
  import { Compartment, EditorState } from '@codemirror/state'
  import { EditorView } from '@codemirror/view'
  import { Marked } from 'marked'
  import DOMPurify from 'dompurify'
  import Icon from './Icon.svelte'
  import PopupMenu from './PopupMenu.svelte'
  import { buildBreadcrumb, isClickOnScrollbar, replaceEditorDocument, type DocumentLoadReason } from './editorCore'
  import { FileSession } from './fileSession.svelte'
  import {
    createMarkdownEditorExtensions,
    highlightCodeElement,
    lineNumbersExtension,
    wordWrapExtension,
  } from './markdownEditor'
  import { noteLineEndings, noteText } from './noteLineEndings'
  import type { EditorPreferences, EditorStatus, FlatOutlineHeading } from './sharedTypes'

  const markdownParser = new Marked()

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
    wordWrap = true,
    canGoBack = false,
    canGoForward = false,
    onNavigateBack,
    onNavigateForward,
    onOpenFile,
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
    wordWrap?: boolean
    canGoBack?: boolean
    canGoForward?: boolean
    onNavigateBack?: () => void
    onNavigateForward?: () => void
    onOpenFile: (path: string, fragment?: string, options?: { newTab?: boolean }) => void | Promise<void>
    onStatusChange: (key: string, status: EditorStatus) => void
    onOutlineChange?: (key: string, headings: FlatOutlineHeading[]) => void
  } = $props()

  let host: HTMLDivElement
  let panel: HTMLElement
  let view: EditorView
  const editableCompartment = new Compartment()
  const readOnlyCompartment = new Compartment()
  const lineNumbersCompartment = new Compartment()
  const wordWrapCompartment = new Compartment()

  let mode = $state<'source' | 'read'>('source')
  let outlineReady = $state(false)
  let mediaUrl = $state('')

  const session = new FileSession({
    entityLabel: 'note',
    initialPath: untrack(() => notePath),
    read: async (targetPath) => {
      const api = window.pywebview?.api
      if (!api) throw new Error('Backend unavailable')
      const note = await api.read_note(workspaceId, targetPath)
      return { ok: true, file: note }
    },
    save: async (targetPath, content, expectedVersion, hasBom) => {
      const api = window.pywebview?.api
      if (!api) throw new Error('Backend unavailable')
      return await api.save_note(workspaceId, targetPath, content, expectedVersion, hasBom)
    },
    getPreferences: () => editorPreferences,
    getFreezeEditors: () => freezeEditors,
    onDocumentLoaded: (content, reason) => {
      setDocument(content, reason)
    },
    onInitialLoadFinished: () => {
      outlineReady = true
    },
  })

  let rendered = $derived(renderMarkdown(session.text, session.path, mediaUrl))
  let outline = $derived(extractOutline(rendered))
  let breadcrumb = $derived(buildBreadcrumb(session.path, workspaceName))

  $effect(() => {
    const key = tabKey
    const status = { dirty: session.dirty, saving: session.saving, conflict: session.conflict }
    untrack(() => onStatusChange(key, status))
  })

  $effect(() => {
    const key = tabKey
    const headings = outline
    if (outlineReady) untrack(() => onOutlineChange?.(key, headings))
  })

  $effect(() => {
    session.syncAutosave()
  })

  $effect(() => {
    const readOnly = session.prompt || freezeEditors
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

  $effect(() => {
    const enabled = wordWrap
    const currentView = view
    if (!currentView) return
    currentView.dispatch({ effects: wordWrapCompartment.reconfigure(wordWrapExtension(enabled)) })
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
    if (!heading) return
    const positions: number[] = []
    // Use the same parser as Read so both modes agree on where a heading starts.
    // CodeMirror positions count normalized line breaks as one character.
    const tokens = markdownParser.lexer(view.state.doc.toString())
    let offset = 0
    for (const token of tokens) {
      if (token.type === 'heading') {
        const template = document.createElement('template')
        template.innerHTML = DOMPurify.sanitize(markdownParser.parser([token]))
        const parsed = template.content.querySelector('h1,h2,h3,h4,h5,h6')
        if (parsed?.textContent?.trim() === heading.label && Number(parsed.tagName.slice(1)) === heading.level) positions.push(offset)
      }
      offset += token.raw.length
    }
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
      const pre = copyButton.closest('.read-code-block')?.querySelector('pre')
      const code = pre?.querySelector('code')
      const textToCopy = code ? (code.textContent ?? '').replace(/\r?\n$/, '') : (pre?.textContent ?? '')
      try {
        await navigator.clipboard.writeText(textToCopy)
        copyButton.textContent = 'Copied'
        setTimeout(() => { if (copyButton.isConnected) copyButton.textContent = 'Copy' }, 1500)
      } catch (reason) { console.error(reason) }
      return
    }
    if (event.type === 'auxclick' && event.button !== 1) return
    const link = element.closest('a')
    if (!link || !session.path) return
    event.preventDefault()
    const newTab = event.button === 1 || event.ctrlKey || event.metaKey
    const href = link.getAttribute('href') ?? ''
    const api = window.pywebview?.api
    if (!api) return
    session.error = ''
    try {
      if (/^https?:\/\//i.test(href)) await api.open_external_link(href)
      else {
        const target = await api.resolve_note_link(workspaceId, session.path, href)
        if (session.isDisposed) return
        if (!target.path.toLowerCase().endsWith('.md') && target.fragment) {
          session.error = 'Opening a specific section of this file is not supported.'
          return
        }
        if (target.path !== session.path) await onOpenFile(target.path, target.fragment, { newTab })
        else if (target.fragment) await navigateToFragment(target.fragment)
      }
    } catch (reason) { session.error = 'Could not open the link.'; console.error(reason) }
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
    if (event.button !== 0 || mode !== 'source' || !session.path || !view || freezeEditors || session.prompt) return
    const target = event.target as HTMLElement | null
    if (!target) return
    const scroller = event.currentTarget as HTMLElement | null
    if (scroller && isClickOnScrollbar(event, scroller)) return
    if (target.closest('.cm-editor') || target.closest('button, a, input, summary')) return
    event.preventDefault()
    const end = view.state.doc.length
    view.dispatch({ selection: { anchor: end } })
    view.focus()
  }

  function setDocument(content: string, reason: DocumentLoadReason) {
    const outerScroller = panel?.querySelector<HTMLElement>('.note-scroll') ?? null
    replaceEditorDocument(view, content, extensions(content), reason, outerScroller)
  }

  function extensions(content = '') {
    return createMarkdownEditorExtensions([
      noteLineEndings(content),
      lineNumbersCompartment.of(lineNumbersExtension(showLineNumbers)),
      wordWrapCompartment.of(wordWrapExtension(wordWrap)),
      editableCompartment.of(EditorView.editable.of(!session.prompt && !freezeEditors)),
      readOnlyCompartment.of(EditorState.readOnly.of(session.prompt || freezeEditors)),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          session.onEditorTextChange(noteText(update.state))
        }
      }),
    ])
  }

  onMount(() => {
    void window.pywebview?.api?.media_url?.(workspaceId).then((url) => { mediaUrl = url }).catch(console.error)
    view = new EditorView({ state: EditorState.create({ extensions: extensions() }), parent: host })
    session.start()
    return () => {
      session.dispose()
      view.destroy()
    }
  })

  export function prepareClose(): Promise<boolean> { return session.prepareClose() }
  export function waitForLoad(): Promise<void> { return session.waitForLoad() }
  export function waitForSave(): Promise<boolean> { return session.waitForSave() }
  export function resumeAfterFailedClose() { session.resumeAfterFailedClose() }
  export function save(expected?: string): Promise<boolean> { return session.save(expected) }
  export function scheduleExternalCheck() { session.scheduleExternalCheck() }
  export function checkExternalNow(): Promise<void> { return session.checkExternalNow() }
  export function hasUnsavedWork(): boolean { return session.hasUnsavedWork() }
  export function closeStatus(): EditorStatus { return session.closeStatus() }
  export function discardForClose(): Promise<void> { return session.discardForClose() }
</script>

<section class="note-panel" class:inactive={!active} aria-label="Markdown editor" aria-hidden={!active} inert={!active} bind:this={panel} data-note-path={notePath}>
  <div class="note-toolbar">
    <div class="note-nav-buttons">
      <button class="icon-button note-nav-btn" onclick={() => onNavigateBack?.()} disabled={!canGoBack || freezeEditors} aria-label="Navigate back" title="Navigate back"><Icon name="arrow-left" size={14} /></button>
      <button class="icon-button note-nav-btn" onclick={() => onNavigateForward?.()} disabled={!canGoForward || freezeEditors} aria-label="Navigate forward" title="Navigate forward"><Icon name="arrow-right" size={14} /></button>
    </div>
    <div class="note-breadcrumb" title={session.path ?? ''}>
      {#if breadcrumb.prefix}<span class="note-breadcrumb-dir">{breadcrumb.prefix}</span>{/if}{#if breadcrumb.file}<span class="note-breadcrumb-file">{breadcrumb.file}</span>{/if}
    </div>
    {#if session.path}
      <button onclick={() => mode = 'source'} aria-pressed={mode === 'source'} aria-label="Source" title="Source"><Icon name="source-code" /></button>
      <button onclick={() => mode = 'read'} aria-pressed={mode === 'read'} aria-label="Read" title="Read"><Icon name="book-open" /></button>
      <button onclick={() => session.save()} disabled={!session.dirty || session.saving || session.conflict || freezeEditors || session.prompt} aria-label="Save" title="Save"><Icon name="save" /></button>
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
      {#if !session.path}
        <div class="note-empty-state">
          <h2>No note selected</h2>
          <p>Choose a Markdown file from the workspace tree.</p>
        </div>
      {/if}
      <div class="note-content" hidden={!session.path || mode !== 'source'} bind:this={host}></div>
      {#if session.path && mode === 'read'}<article class="note-content note-read" use:linkHandler={rendered}>{@html rendered}</article>{/if}
    </div>
  </div>
  {#if session.message || session.error || session.conflict || session.prompt}
    <div class="note-notices">
      {#if session.message && !session.conflict}<p role="status" class="status-notice">{session.message}</p>{/if}
      {#if session.error}<p role="alert" class="note-error">{session.error}</p>{/if}
      {#if session.conflict}
        <div role="alert" class="note-conflict">
          <span>{session.message || (session.missing ? 'The note is missing or cannot be read.' : 'The note changed outside acornwiki.')}</span>
          {#if !session.missing}
            <button disabled={session.saving || freezeEditors || session.prompt} onclick={() => session.loadDisk()}>Load disk version</button>
            {#if session.dirty}<button disabled={session.saving || freezeEditors || session.prompt} onclick={() => { if (window.confirm('Replace the disk version with the editor content?')) void session.save(session.diskVersion) }}>Overwrite with editor version</button>{/if}
          {/if}
          <button disabled={session.saving || freezeEditors || session.prompt} onclick={() => void session.checkExternal()}>Check again</button>
        </div>
      {/if}
      {#if session.prompt}
        <div role="alert" class="note-conflict">You have unsaved changes.
          <button onclick={() => session.resolveClose('save')}>Save</button>
          <button onclick={() => session.resolveClose('discard')}>Discard</button>
          <button onclick={() => session.resolveClose('cancel')}>Cancel</button>
        </div>
      {/if}
    </div>
  {/if}
</section>
