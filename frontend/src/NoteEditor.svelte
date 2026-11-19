<script lang="ts">
  import { onMount } from 'svelte'
  import { EditorState } from '@codemirror/state'
  import { EditorView, keymap } from '@codemirror/view'
  import { basicSetup } from 'codemirror'
  import { markdown } from '@codemirror/lang-markdown'
  import { marked } from 'marked'
  import DOMPurify from 'dompurify'

  let { workspaceId, selectedNote = $bindable(null) }: { workspaceId: string; selectedNote: string | null } = $props()
  let host: HTMLDivElement
  let view: EditorView
  let path = $state<string | null>(null)
  let text = $state('')
  let savedText = $state('')
  let version = $state('')
  let mode = $state<'source' | 'read'>('source')
  let autosave = $state(false)
  let autoReload = $state(true)
  let showReloadNotice = $state(true)
  let settingsLoaded = $state(false)
  let message = $state('')
  let error = $state('')
  let conflict = $state(false)
  let missing = $state(false)
  let diskVersion = $state('')
  let diskText = $state('')
  let saving = $state(false)
  let opening = false
  let prompt = $state(false)
  let chooseClose: ((choice: 'save' | 'discard' | 'cancel') => void) | undefined
  let operation = 0
  let externalTimer: ReturnType<typeof setTimeout> | undefined
  let saveTimer: ReturnType<typeof setTimeout> | undefined
  let savePromise: Promise<boolean> | undefined
  let dirty = $derived(text !== savedText)
  let rendered = $derived(mode === 'read' ? DOMPurify.sanitize(marked.parse(text, { async: false })) : '')

  function setDocument(content: string) {
    const lineSeparator = content.includes('\r\n') ? '\r\n' : '\n'
    view.setState(EditorState.create({ doc: content, extensions: [...extensions(), EditorState.lineSeparator.of(lineSeparator)] }))
    text = content
  }

  function extensions() {
    return [basicSetup, markdown(), EditorView.lineWrapping, keymap.of([{ key: 'Mod-s', run: () => { void save(); return true } }]), EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        text = update.state.sliceDoc()
        message = ''
        scheduleSave()
      }
    })]
  }

  onMount(() => {
    void loadPreferences()
    view = new EditorView({ state: EditorState.create({ extensions: extensions() }), parent: host })
    function beforeUnload(event: BeforeUnloadEvent) {
      if (text !== savedText || saving) { event.preventDefault(); event.returnValue = '' }
    }
    window.addEventListener('beforeunload', beforeUnload)
    function onKeydown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); void save() }
    }
    window.addEventListener('keydown', onKeydown)
    return () => {
      window.removeEventListener('beforeunload', beforeUnload)
      window.removeEventListener('keydown', onKeydown)
      clearTimeout(saveTimer)
      clearTimeout(externalTimer)
      view.destroy()
    }
  })

  async function loadPreferences() {
    try {
      const preferences = (await window.pywebview?.api?.get_settings())?.editor
      if (!preferences) throw new Error('Editor preferences unavailable')
      autosave = preferences.autosave
      autoReload = preferences.auto_reload
      showReloadNotice = preferences.reload_notice
      settingsLoaded = true
    } catch (reason) { error = 'Could not load editor settings.'; console.error(reason) }
  }

  function scheduleSave() {
    clearTimeout(saveTimer)
    if (autosave && path && !conflict) saveTimer = setTimeout(() => void save(), 1000)
  }

  export async function prepareClose(): Promise<boolean> {
    if (prompt || opening) return false
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

  export async function open(nextPath: string) {
    if (path === nextPath || opening || prompt) return
    if (!(await prepareClose())) return
    const api = window.pywebview?.api
    if (!api) return
    const token = ++operation
    const originalText = text
    opening = true
    error = ''
    try {
      const note = await api.read_note(workspaceId, nextPath)
      if (token !== operation) return
      if (text !== originalText) { error = 'The note changed while opening another file. Try again.'; return }
      clearTimeout(saveTimer)
      path = note.path
      selectedNote = note.path
      version = note.version
      savedText = note.content
      setDocument(note.content)
      conflict = false
      missing = false
      message = ''
      await api.set_active_note(workspaceId, note.path)
      scheduleExternalCheck()
    } catch (reason) { if (token === operation) { error = 'Could not open or watch the note.'; console.error(reason); scheduleSave() } }
    finally { opening = false }
  }

  async function save(expected = version): Promise<boolean> {
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

  async function checkExternal() {
    const api = window.pywebview?.api
    if (!path || !api) return
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
      if (!dirty && autoReload && !saving) {
        version = note.version
        savedText = note.content
        setDocument(note.content)
        conflict = false
        message = showReloadNotice ? 'File changed externally and was reloaded.' : ''
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

  async function setPreference(event: Event, key: 'autosave' | 'auto_reload' | 'reload_notice') {
    const checked = (event.currentTarget as HTMLInputElement).checked
    const target = event.currentTarget as HTMLInputElement
    target.disabled = true
    try {
      await window.pywebview?.api?.set_editor_preference(key, checked)
      if (key === 'autosave') { autosave = checked; scheduleSave() }
      if (key === 'auto_reload') autoReload = checked
      if (key === 'reload_notice') showReloadNotice = checked
    } catch (reason) { target.checked = !checked; error = 'Could not save editor settings.'; console.error(reason) }
    finally { target.disabled = false }
  }
</script>

<section class="note-panel" aria-label="Markdown editor">
  <div class="note-toolbar">
    <strong>{path ?? 'Select a Markdown file'}</strong>
    {#if path}<span>{dirty ? 'Unsaved' : 'Saved'}</span>
      <button onclick={() => mode = 'source'} aria-pressed={mode === 'source'}>Source</button>
      <button onclick={() => mode = 'read'} aria-pressed={mode === 'read'}>Read</button>
      <button onclick={() => save()} disabled={!dirty || saving || conflict}>Save</button>
    {/if}
  </div>
  <div class="note-settings">
    <label><input type="checkbox" checked={autosave} disabled={!settingsLoaded} onchange={(event) => setPreference(event, 'autosave')} /> Autosave</label>
    <label><input type="checkbox" checked={autoReload} disabled={!settingsLoaded} onchange={(event) => setPreference(event, 'auto_reload')} /> Auto-reload unchanged notes</label>
    <label><input type="checkbox" checked={showReloadNotice} disabled={!settingsLoaded} onchange={(event) => setPreference(event, 'reload_notice')} /> Show reload notification</label>
  </div>
  {#if message}<p role="status">{message}</p>{/if}
  {#if error}<p role="alert">{error}</p>{/if}
  {#if conflict}
    <div role="alert" class="note-conflict">
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
  <div class="note-content" hidden={!path || mode !== 'source'} bind:this={host}></div>
  {#if path && mode === 'read'}<article class="note-content note-read">{@html rendered}</article>{/if}
</section>
