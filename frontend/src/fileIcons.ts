// Classify file extensions once, so tree and search results use the same icon.
export const fileIconIds = ['file', 'file-text', 'markdown', 'image', 'pdf', 'code', 'code-file', 'spreadsheet', 'document', 'presentation', 'book', 'config', 'archive', 'audio', 'video'] as const
export type FileIconId = typeof fileIconIds[number]
export function isFileIconId(value: string): value is FileIconId { return (fileIconIds as readonly string[]).includes(value) }

const extensions: Record<string, FileIconId> = {}
function register(icon: FileIconId, values: string) {
  for (const extension of values.split(' ')) extensions[`.${extension}`] = icon
}
register('markdown', 'md markdown')
register('file-text', 'txt log')
register('image', 'png jpg jpeg webp gif svg avif jxl bmp ico tif tiff heic heif')
register('audio', 'mp3 wav flac ogg opus m4a aac aiff wma')
register('video', 'mp4 mkv webm mov avi m4v mpeg mpg wmv')
register('archive', 'zip 7z rar tar gz bz2 xz zst tgz')
register('spreadsheet', 'csv tsv xls xlsx ods')
register('document', 'doc docx odt rtf')
register('presentation', 'ppt pptx odp')
register('pdf', 'pdf')
register('book', 'epub djvu djv mobi azw azw3')
register('config', 'json jsonl yaml yml toml ini cfg conf xml')
register('code-file', 'py pyw c h cpp cxx cc hpp hxx js jsx ts tsx rs go java kt swift css scss html htm sh ps1 sql')

export function fileIconFor(name: string, overrides: Record<string, string> = {}): FileIconId {
  const dot = name.lastIndexOf('.')
  const extension = dot >= 0 ? name.slice(dot).toLowerCase() : ''
  const override = Object.entries(overrides).find(([key]) => key.toLowerCase() === extension)?.[1]
  return override && isFileIconId(override) ? override : extensions[extension] ?? 'file'
}
