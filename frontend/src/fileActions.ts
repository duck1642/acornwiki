import type { TextFileReadResult } from './sharedTypes'

const KNOWN_EXTERNAL_EXTENSIONS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.jxl', '.bmp', '.ico', '.tif', '.tiff', '.avif', '.heic', '.heif', '.psd',
  '.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.opus', '.aiff', '.wma',
  '.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv', '.m4v', '.mpeg', '.mpg',
  '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp', '.epub', '.djvu', '.djv', '.mobi', '.azw', '.azw3',
  '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.zst', '.iso', '.dmg',
  '.exe', '.dll', '.msi', '.so', '.dylib', '.bin', '.class', '.jar', '.pyc', '.pyo', '.wasm', '.o', '.obj', '.lib', '.a',
  '.ttf', '.otf', '.woff', '.woff2',
  '.db', '.sqlite', '.sqlite3', '.lnk',
])

export function isMarkdownPath(path: string): boolean {
  return path.toLowerCase().endsWith('.md')
}

export function isKnownExternalFile(path: string): boolean {
  const name = path.replace(/\\/g, '/').split('/').pop() ?? ''
  const dot = name.lastIndexOf('.')
  if (dot <= 0) return false
  return KNOWN_EXTERNAL_EXTENSIONS.has(name.slice(dot).toLowerCase())
}

export function formatUnopenableFileMessage(
  path: string,
  result: Extract<TextFileReadResult, { ok: false }>,
): string {
  const name = path.replace(/\\/g, '/').split('/').pop() ?? path
  if (result.reason === 'too_large') {
    const sizeMb = (result.size_bytes / (1024 * 1024)).toFixed(1)
    const maxMb = (result.max_bytes / (1024 * 1024)).toFixed(0)
    return `"${name}" (${sizeMb} MB) exceeds the ${maxMb} MB text editor limit.`
  }
  if (result.reason === 'binary') {
    return `"${name}" appears to contain binary data and cannot be opened in the text editor.`
  }
  return `"${name}" is not valid UTF-8 text (it may be binary or use an unsupported encoding).`
}

/** Open a workspace file with the OS default app, or offer to show a blocked file in the file manager. */
export async function openWorkspaceFile(workspaceId: string, path: string): Promise<void> {
  const api = window.pywebview?.api
  if (!api) throw new Error('Backend unavailable')
  const opened = await api.open_workspace_file(workspaceId, path)
  if (!opened && window.confirm(`This file type is blocked from opening: ${path}\n\nShow it in the file manager?`)) {
    await api.reveal_workspace_file(workspaceId, path)
  }
}
