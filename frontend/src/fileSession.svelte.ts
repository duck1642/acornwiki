import type { DocumentLoadReason } from './editorCore'
import type { EditorPreferences, EditorStatus, LoadedFileSnapshot } from './sharedTypes'

export type FileReadOutcome =
  | { ok: true; file: LoadedFileSnapshot }
  | { ok: false; reason: 'too_large' | 'binary' | 'unsupported_encoding'; sizeBytes: number; maxBytes: number }

export type FileSessionOptions = {
  initialPath: string
  read: (path: string) => Promise<FileReadOutcome>
  save: (path: string, content: string, expectedVersion: string, hasBom: boolean) => Promise<LoadedFileSnapshot>
  getPreferences: () => EditorPreferences
  getFreezeEditors: () => boolean
  onDocumentLoaded: (content: string, reason: DocumentLoadReason) => void
  onInitialLoadFinished?: () => void
  initialSnapshot?: LoadedFileSnapshot
  entityLabel?: 'note' | 'file'
}

export class FileSession {
  path = $state<string | null>(null)
  text = $state('')
  savedText = $state('')
  version = $state('')
  hasBom = $state(false)
  message = $state('')
  error = $state('')
  conflict = $state(false)
  missing = $state(false)
  diskVersion = $state('')
  diskText = $state('')
  diskHasBom = $state(false)
  saving = $state(false)
  prompt = $state(false)
  dirty = $derived(this.text !== this.savedText)

  private options: FileSessionOptions
  private opening = false
  private disposed = false
  private loadingPromise: Promise<void> = Promise.resolve()
  private chooseClose: ((choice: 'save' | 'discard' | 'cancel') => void) | undefined
  private operation = 0
  private externalTimer: ReturnType<typeof setTimeout> | undefined
  private saveTimer: ReturnType<typeof setTimeout> | undefined
  private savePromise: Promise<boolean> | undefined
  private externalCheckPromise: Promise<void> | undefined
  private externalCheckPending = false

  constructor(options: FileSessionOptions) {
    this.options = options
  }

  get isDisposed(): boolean {
    return this.disposed
  }

  start() {
    const initial = this.options.initialSnapshot
    this.options.initialSnapshot = undefined
    if (initial) {
      this.path = initial.path
      this.version = initial.version
      this.savedText = initial.content
      this.hasBom = Boolean(initial.has_bom)
      this.text = initial.content
      this.options.onDocumentLoaded(initial.content, 'initial')
      this.conflict = false
      this.missing = false
      this.message = ''
      this.options.onInitialLoadFinished?.()
      this.scheduleExternalCheck()
      this.loadingPromise = Promise.resolve()
      return
    }
    this.loadingPromise = this.load()
  }

  dispose() {
    this.disposed = true
    this.operation += 1
    clearTimeout(this.saveTimer)
    clearTimeout(this.externalTimer)
    const resolve = this.chooseClose
    this.chooseClose = undefined
    this.prompt = false
    resolve?.('cancel')
  }

  onEditorTextChange(nextText: string) {
    this.text = nextText
    this.message = ''
    this.scheduleSave()
  }

  syncAutosave() {
    const prefs = this.options.getPreferences()
    const canAutoSave = prefs.autosave
      && !this.prompt
      && !this.options.getFreezeEditors()
      && !this.conflict
      && Boolean(this.path)
      && this.dirty
    if (!canAutoSave) clearTimeout(this.saveTimer)
    else this.scheduleSave()
  }

  scheduleSave() {
    clearTimeout(this.saveTimer)
    const prefs = this.options.getPreferences()
    if (prefs.autosave && !this.prompt && !this.options.getFreezeEditors() && this.dirty && this.path && !this.conflict) {
      this.saveTimer = setTimeout(() => {
        if (!this.prompt && !this.options.getFreezeEditors()) void this.save()
      }, 1000)
    }
  }

  resolveClose(choice: 'save' | 'discard' | 'cancel') {
    this.chooseClose?.(choice)
  }

  async prepareClose(): Promise<boolean> {
    if (this.prompt) return false
    if (this.opening) {
      await this.loadingPromise
      if (this.disposed) return false
    }
    if (this.savePromise && !(await this.savePromise)) return false
    if (!this.dirty) return true
    this.prompt = true
    const choice = await new Promise<'save' | 'discard' | 'cancel'>((resolve) => { this.chooseClose = resolve })
    this.prompt = false
    this.chooseClose = undefined
    if (choice === 'cancel') return false
    if (choice === 'discard') { clearTimeout(this.saveTimer); return true }
    return await this.save() && this.text === this.savedText
  }

  async waitForLoad(): Promise<void> {
    await this.loadingPromise
  }

  async waitForSave(): Promise<boolean> {
    return this.savePromise ? await this.savePromise : true
  }

  resumeAfterFailedClose() {
    this.scheduleSave()
  }

  async load() {
    if (this.opening || this.disposed) return
    const label = this.options.entityLabel ?? 'note'
    const token = ++this.operation
    this.opening = true
    this.error = ''
    try {
      const outcome = await this.options.read(this.path ?? this.options.initialPath)
      if (token !== this.operation) return
      if (!outcome.ok) {
        if (outcome.reason === 'too_large') {
          const maxMb = (outcome.maxBytes / (1024 * 1024)).toFixed(0)
          this.error = `This file exceeds the ${maxMb} MB text editor size limit.`
        } else if (outcome.reason === 'binary') {
          this.error = 'This file appears to contain binary data and cannot be opened in the text editor.'
        } else {
          this.error = 'This file is not valid UTF-8 text (it may be binary or use an unsupported encoding).'
        }
        return
      }
      const file = outcome.file
      clearTimeout(this.saveTimer)
      this.path = file.path
      this.version = file.version
      this.savedText = file.content
      this.hasBom = Boolean(file.has_bom)
      this.text = file.content
      this.options.onDocumentLoaded(file.content, 'initial')
      this.conflict = false
      this.missing = false
      this.message = ''
      this.scheduleExternalCheck()
    } catch (reason) {
      if (token === this.operation) {
        this.error = `Could not open or watch the ${label}.`
        console.error(reason)
      }
    } finally {
      this.opening = false
      if (!this.disposed && token === this.operation) this.options.onInitialLoadFinished?.()
    }
  }

  async save(expected = this.version): Promise<boolean> {
    if (this.savePromise) return this.savePromise
    if (!this.path || (this.conflict && expected === this.version)) return false
    const label = this.options.entityLabel ?? 'note'
    const currentPath = this.path
    const content = this.text
    const bom = this.hasBom
    const token = this.operation
    clearTimeout(this.saveTimer)
    this.saving = true
    this.error = ''
    this.savePromise = (async () => {
      try {
        const result = await this.options.save(currentPath, content, expected, bom)
        if (token !== this.operation) return false
        this.version = result.version
        this.savedText = content
        this.hasBom = result.has_bom !== undefined ? Boolean(result.has_bom) : bom
        this.conflict = false
        this.missing = false
        this.message = ''
        if (this.text !== this.savedText) this.scheduleSave()
        return true
      } catch (reason) {
        if (this.disposed || token !== this.operation) return false
        console.error(reason)
        // Clear saving before checking external changes so clean files can still auto-reload.
        this.saving = false
        await this.checkExternal()
        if (!this.conflict) this.error = `Could not save the ${label}.`
        return false
      } finally {
        this.saving = false
        this.savePromise = undefined
      }
    })()
    return this.savePromise
  }

  scheduleExternalCheck() {
    clearTimeout(this.externalTimer)
    this.externalTimer = setTimeout(() => void this.checkExternal(), 250)
  }

  async checkExternalNow() {
    clearTimeout(this.externalTimer)
    await this.checkExternal()
  }

  hasUnsavedWork(): boolean {
    return this.dirty || this.saving
  }

  closeStatus(): EditorStatus {
    return { dirty: this.dirty, saving: this.saving, conflict: this.conflict }
  }

  async discardForClose(): Promise<void> {
    clearTimeout(this.saveTimer)
    if (this.savePromise) await this.savePromise
    clearTimeout(this.saveTimer)
  }

  async checkExternal() {
    this.externalCheckPending = true
    if (this.externalCheckPromise) return this.externalCheckPromise
    this.externalCheckPromise = (async () => {
      while (this.externalCheckPending && !this.disposed) {
        this.externalCheckPending = false
        await this.checkExternalOnce()
      }
    })()
    try { await this.externalCheckPromise }
    finally { this.externalCheckPromise = undefined }
  }

  private async checkExternalOnce() {
    if (this.disposed) return
    if (!this.path) { await this.load(); return }
    const token = this.operation
    const checkedVersion = this.version
    try {
      const outcome = await this.options.read(this.path ?? this.options.initialPath)
      if (token !== this.operation) return
      if (checkedVersion !== this.version) { this.externalCheckPending = true; return }
      if (!outcome.ok) {
        clearTimeout(this.saveTimer)
        this.conflict = true
        this.missing = true
        this.message = outcome.reason === 'too_large'
          ? 'File on disk exceeds the text editor size limit. Your editor content was kept.'
          : 'File on disk can no longer be read as UTF-8 text. Your editor content was kept.'
        return
      }
      const file = outcome.file
      if (file.version === this.version) {
        const resolved = this.conflict
        this.conflict = false
        this.missing = false
        if (resolved) { this.message = ''; if (this.dirty) this.scheduleSave() }
        return
      }
      this.diskVersion = file.version
      this.diskText = file.content
      this.diskHasBom = Boolean(file.has_bom)
      this.missing = false
      const prefs = this.options.getPreferences()
      if (!this.dirty && prefs.auto_reload && !this.saving) {
        this.version = file.version
        this.savedText = file.content
        this.hasBom = Boolean(file.has_bom)
        this.text = file.content
        this.options.onDocumentLoaded(file.content, 'reload')
        this.conflict = false
        this.message = prefs.reload_notice ? 'File changed externally and was reloaded.' : ''
      } else {
        clearTimeout(this.saveTimer)
        this.conflict = true
        this.message = 'File changed externally. Your editor content was kept.'
      }
    } catch (reason) {
      if (token !== this.operation) return
      if (checkedVersion !== this.version) { this.externalCheckPending = true; return }
      clearTimeout(this.saveTimer)
      this.conflict = true
      this.missing = true
      this.message = 'File cannot be read; it may have been moved or deleted. Your editor content was kept.'
      console.error(reason)
    }
  }

  loadDisk() {
    if (this.saving || this.prompt || this.options.getFreezeEditors()) return
    if (this.dirty && !window.confirm('Discard unsaved changes and load the version on disk?')) return
    if (this.saving || this.prompt || this.options.getFreezeEditors()) return
    this.operation += 1
    clearTimeout(this.saveTimer)
    this.version = this.diskVersion
    this.savedText = this.diskText
    this.hasBom = this.diskHasBom
    this.text = this.diskText
    this.options.onDocumentLoaded(this.diskText, 'reload')
    this.conflict = false
    this.message = 'Loaded the version on disk.'
  }
}
