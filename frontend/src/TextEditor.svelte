<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import type { LanguageSupport } from '@codemirror/language'
  import { Compartment, EditorState } from '@codemirror/state'
  import { EditorView } from '@codemirror/view'
  import Icon from './Icon.svelte'
  import PopupMenu from './PopupMenu.svelte'
  import {
    buildBreadcrumb,
    createBaseEditorExtensions,
    isClickOnScrollbar,
    lineNumbersExtension,
    replaceEditorDocument,
    resolveLanguageByFilename,
    wordWrapExtension,
    type DocumentLoadReason,
  } from './editorCore'
  import { FileSession } from './fileSession.svelte'
  import { noteLineEndings, noteText } from './noteLineEndings'
  import type { EditorPreferences, EditorStatus, LoadedFileSnapshot } from './sharedTypes'

  let {
    workspaceId,
    workspaceName = '',
    tabKey,
    filePath,
    takeInitialSnapshot,
    active,
    freezeEditors = false,
    editorPreferences,
    showLineNumbers = true,
    wordWrap = false,
    canGoBack = false,
    canGoForward = false,
    onNavigateBack,
    onNavigateForward,
    onStatusChange,
  }: {
    workspaceId: string
    workspaceName?: string
    tabKey: string
    filePath: string
    takeInitialSnapshot?: () => LoadedFileSnapshot | undefined
    active: boolean
    freezeEditors?: boolean
    editorPreferences: EditorPreferences
    showLineNumbers?: boolean
    wordWrap?: boolean
    canGoBack?: boolean
    canGoForward?: boolean
    onNavigateBack?: () => void
    onNavigateForward?: () => void
    onStatusChange: (key: string, status: EditorStatus) => void
  } = $props()

  let host: HTMLDivElement
  let view: EditorView
  const editableCompartment = new Compartment()
  const readOnlyCompartment = new Compartment()
  const lineNumbersCompartment = new Compartment()
  const wordWrapCompartment = new Compartment()
  const languageCompartment = new Compartment()

  let loadedLanguage: LanguageSupport | null = null
  const languageDesc = $derived(resolveLanguageByFilename(filePath))
  let languageLabel = $derived(languageDesc?.name ?? 'Plain text')

  const session = new FileSession({
    entityLabel: 'file',
    initialPath: untrack(() => filePath),
    initialSnapshot: untrack(() => takeInitialSnapshot?.()),
    read: async (targetPath) => {
      const api = window.pywebview?.api
      if (!api?.read_text_file) throw new Error('Backend unavailable')
      const result = await api.read_text_file(workspaceId, targetPath)
      if (!result.ok) {
        return {
          ok: false,
          reason: result.reason,
          sizeBytes: result.size_bytes,
          maxBytes: result.max_bytes,
        }
      }
      return {
        ok: true,
        file: {
          path: result.path,
          content: result.content,
          version: result.version,
          has_bom: result.has_bom,
        },
      }
    },
    save: async (targetPath, content, expectedVersion, hasBom) => {
      const api = window.pywebview?.api
      if (!api?.save_text_file) throw new Error('Backend unavailable')
      return await api.save_text_file(workspaceId, targetPath, content, expectedVersion, hasBom)
    },
    getPreferences: () => editorPreferences,
    getFreezeEditors: () => freezeEditors,
    onDocumentLoaded: (content, reason) => {
      setDocument(content, reason)
    },
  })

  let breadcrumb = $derived(buildBreadcrumb(session.path ?? filePath, workspaceName))

  $effect(() => {
    const key = tabKey
    const status = { dirty: session.dirty, saving: session.saving, conflict: session.conflict }
    untrack(() => onStatusChange(key, status))
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

  function setDocument(content: string, reason: DocumentLoadReason) {
    replaceEditorDocument(view, content, extensions(content), reason)
  }

  function extensions(content = '') {
    return createBaseEditorExtensions([
      noteLineEndings(content),
      languageCompartment.of(loadedLanguage ?? []),
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

  function handleHostMousedown(event: MouseEvent) {
    if (event.button !== 0 || !session.path || !view || freezeEditors || session.prompt) return
    const target = event.target as HTMLElement | null
    if (!target) return
    const scroller = target.closest<HTMLElement>('.cm-scroller')
    if (scroller && isClickOnScrollbar(event, scroller)) return
    if (target.closest('.cm-content') || target.closest('.cm-gutters') || target.closest('.cm-panels') || target.closest('button, a, input, summary')) return
    event.preventDefault()
    const end = view.state.doc.length
    view.dispatch({ selection: { anchor: end } })
    view.focus()
  }

  onMount(() => {
    view = new EditorView({ state: EditorState.create({ extensions: extensions() }), parent: host })
    session.start()
    const desc = resolveLanguageByFilename(filePath)
    if (desc) {
      void desc.load().then((support) => {
        if (session.isDisposed) return
        loadedLanguage = support
        view.dispatch({ effects: languageCompartment.reconfigure(support) })
      }).catch(console.error)
    }
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

<section class="note-panel text-editor-panel" class:inactive={!active} aria-label="Text editor" aria-hidden={!active} inert={!active} data-note-path={filePath} data-editor-kind="text">
  <div class="note-toolbar">
    <div class="note-nav-buttons">
      <button class="icon-button note-nav-btn" onclick={() => onNavigateBack?.()} disabled={!canGoBack || freezeEditors} aria-label="Navigate back" title="Navigate back"><Icon name="arrow-left" size={14} /></button>
      <button class="icon-button note-nav-btn" onclick={() => onNavigateForward?.()} disabled={!canGoForward || freezeEditors} aria-label="Navigate forward" title="Navigate forward"><Icon name="arrow-right" size={14} /></button>
    </div>
    <div class="note-breadcrumb" title={session.path ?? filePath}>
      {#if breadcrumb.prefix}<span class="note-breadcrumb-dir">{breadcrumb.prefix}</span>{/if}{#if breadcrumb.file}<span class="note-breadcrumb-file">{breadcrumb.file}</span>{/if}
    </div>
    {#if session.path}
      <span class="text-editor-lang">{languageLabel}</span>
      <button onclick={() => session.save()} disabled={!session.dirty || session.saving || session.conflict || freezeEditors || session.prompt} aria-label="Save" title="Save"><Icon name="save" /></button>
      <details class="note-more-menu">
        <summary aria-label="More file actions" title="More file actions"><Icon name="ellipsis" /></summary>
        <PopupMenu class="note-more-content">
          <button class="popup-menu-item" disabled title="Not available yet">Rename</button>
          <button class="popup-menu-item" disabled title="Not available yet">Copy</button>
        </PopupMenu>
      </details>
    {/if}
  </div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="text-editor-body" onmousedown={handleHostMousedown}>
    <div class="text-editor-host" hidden={!session.path} bind:this={host}></div>
  </div>
  {#if session.message || session.error || session.conflict || session.prompt}
    <div class="note-notices">
      {#if session.message && !session.conflict}<p role="status" class="status-notice">{session.message}</p>{/if}
      {#if session.error}<p role="alert" class="note-error">{session.error}</p>{/if}
      {#if session.conflict}
        <div role="alert" class="note-conflict">
          <span>{session.message || (session.missing ? 'The file is missing or cannot be read.' : 'The file changed outside acornwiki.')}</span>
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
