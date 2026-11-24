import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import {
  bracketMatching,
  foldGutter,
  foldKeymap,
  HighlightStyle,
  indentOnInput,
  LanguageDescription,
  syntaxHighlighting,
} from '@codemirror/language'
import { languages } from '@codemirror/language-data'
import { highlightSelectionMatches, search, searchKeymap } from '@codemirror/search'
import { EditorState, type Extension } from '@codemirror/state'
import {
  drawSelection,
  dropCursor,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  type KeyBinding,
} from '@codemirror/view'
import { tags } from '@lezer/highlight'
import { icons } from './icons'

export function createFoldMarker(open: boolean): HTMLElement {
  const wrapper = document.createElement('span')
  wrapper.className = `cm-fold-chevron${open ? ' open' : ''}`
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('width', '13')
  svg.setAttribute('height', '13')
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('fill', 'none')
  svg.setAttribute('stroke', 'currentColor')
  svg.setAttribute('stroke-width', '2.1')
  svg.setAttribute('stroke-linecap', 'round')
  svg.setAttribute('stroke-linejoin', 'round')
  svg.setAttribute('aria-hidden', 'true')
  // Static SVG paths from ./icons, never workspace data.
  svg.innerHTML = open ? icons['chevron-down'] : icons['chevron-right']
  wrapper.appendChild(svg)
  return wrapper
}

export const acornHighlightStyle = HighlightStyle.define([
  { tag: tags.heading1, color: 'var(--ink)', fontWeight: '700', fontSize: '1.58em', lineHeight: '1.35' },
  { tag: tags.heading2, color: 'var(--ink)', fontWeight: '700', fontSize: '1.3em', lineHeight: '1.4' },
  { tag: tags.heading3, color: 'var(--ink)', fontWeight: '650', fontSize: '1.14em', lineHeight: '1.45' },
  { tag: [tags.heading4, tags.heading5, tags.heading6, tags.heading], color: 'var(--ink-muted)', fontWeight: '650', fontSize: '1.04em' },
  { tag: tags.strong, color: 'var(--ink)', fontWeight: '700' },
  { tag: tags.emphasis, color: 'var(--ink)', fontStyle: 'italic' },
  { tag: tags.strikethrough, color: 'var(--ink-muted)', textDecoration: 'line-through' },
  { tag: tags.link, color: 'var(--link)', textDecoration: 'underline', textUnderlineOffset: '3px' },
  { tag: tags.url, color: 'color-mix(in srgb, var(--link) 82%, var(--ink-muted))' },
  { tag: tags.quote, color: 'var(--ink-muted)', fontStyle: 'italic' },
  { tag: tags.monospace, color: 'var(--accent)', fontFamily: 'var(--font-mono)' },
  { tag: [tags.processingInstruction, tags.punctuation, tags.meta, tags.contentSeparator, tags.brace, tags.squareBracket, tags.paren], color: 'var(--ink-faint)', fontWeight: '400' },
  { tag: [tags.list], color: 'var(--warn)' },
  { tag: [tags.keyword, tags.operator, tags.controlKeyword, tags.definitionKeyword, tags.moduleKeyword], color: 'var(--warn)' },
  { tag: [tags.typeName, tags.className, tags.namespace, tags.labelName], color: 'var(--link)' },
  { tag: [tags.string, tags.special(tags.string), tags.regexp], color: 'var(--accent)' },
  { tag: [tags.comment], color: 'var(--ink-faint)', fontStyle: 'italic' },
  { tag: [tags.number, tags.bool, tags.atom, tags.null], color: 'var(--link)' },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: 'var(--ink)', fontWeight: '600' },
  { tag: [tags.tagName], color: 'var(--warn)' },
  { tag: [tags.attributeName, tags.propertyName], color: 'var(--link)' },
  { tag: [tags.variableName, tags.attributeValue], color: 'var(--ink)' },
  { tag: [tags.invalid], color: 'var(--error)' },
])

export const acornEditorTheme = EditorView.theme({
  '&': {
    color: 'var(--ink)',
    backgroundColor: 'transparent',
    fontFamily: 'var(--font-mono)',
    fontSize: 'var(--font-size-mono, 14px)',
    fontWeight: 'var(--font-weight-mono, 400)',
    lineHeight: '1.7',
  },
  '&.cm-focused': {
    outline: 'none',
  },
  '.cm-scroller': {
    overflow: 'visible',
    fontFamily: 'inherit',
    fontWeight: 'inherit',
    lineHeight: 'inherit',
  },
  '.cm-content': {
    padding: '2px 0 96px',
    caretColor: 'var(--accent)',
  },
  '.cm-line': {
    padding: '1px 2px',
  },
  '.cm-cursor, .cm-dropCursor': {
    borderLeftColor: 'var(--accent)',
    borderLeftWidth: '2px',
  },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': {
    backgroundColor: 'var(--bg-selection)',
  },
  '.cm-activeLine': {
    backgroundColor: 'color-mix(in srgb, var(--ink) 3.5%, transparent)',
    borderRadius: '3px',
  },
  '.cm-gutters': {
    backgroundColor: 'var(--bg-paper)',
    color: 'var(--ink-faint)',
    borderRight: '0',
    marginRight: '6px',
  },
  '.cm-lineNumbers': {
    paddingRight: '8px',
    borderRight: '1px solid color-mix(in srgb, var(--border) 60%, transparent)',
  },
  '.cm-foldGutter': {
    width: '16px',
  },
  '.cm-foldGutter .cm-gutterElement': {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '0',
    color: 'var(--ink-faint)',
    cursor: 'pointer',
  },
  '.cm-fold-chevron': {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    opacity: '0.45',
  },
  '.cm-fold-chevron:not(.open)': {
    opacity: '0.85',
    color: 'var(--ink-muted)',
  },
  '.cm-foldGutter .cm-gutterElement:hover .cm-fold-chevron': {
    color: 'var(--ink)',
    opacity: '1',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'transparent',
    color: 'var(--ink-muted)',
  },
  '.cm-selectionMatch': {
    backgroundColor: 'color-mix(in srgb, var(--accent) 18%, transparent)',
    borderRadius: '2px',
  },
  '&.cm-focused .cm-matchingBracket, &.cm-focused .cm-nonmatchingBracket': {
    backgroundColor: 'color-mix(in srgb, var(--accent) 22%, transparent)',
    outline: '1px solid color-mix(in srgb, var(--accent) 45%, transparent)',
    borderRadius: '2px',
  },
  '.cm-foldPlaceholder': {
    backgroundColor: 'transparent',
    border: '0',
    color: 'var(--ink-faint)',
    fontSize: '0.8571rem',
    fontWeight: '400',
    letterSpacing: '0.08em',
    marginLeft: '6px',
    padding: '0 4px',
    borderRadius: '3px',
    verticalAlign: 'middle',
  },
  '.cm-foldPlaceholder:hover': {
    backgroundColor: 'var(--bg-hover)',
    color: 'var(--ink)',
  },
  '.cm-panels': {
    backgroundColor: 'var(--bg-panel)',
    color: 'var(--ink)',
    borderColor: 'var(--border)',
    borderRadius: '6px',
    marginBottom: '12px',
  },
  '.cm-panels.cm-panels-top': {
    borderBottom: '1px solid var(--border)',
  },
  '.cm-panels.cm-panels-bottom': {
    borderTop: '1px solid var(--border)',
  },
  '.cm-search': {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 10px',
    fontFamily: 'var(--font-ui)',
    fontSize: '0.8571rem',
  },
  '.cm-search input, .cm-search button': {
    fontFamily: 'var(--font-ui)',
    fontSize: '0.8214rem',
  },
  '.cm-search .cm-textfield': {
    padding: '4px 8px',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    backgroundColor: 'var(--bg-app)',
    color: 'var(--ink)',
  },
  '.cm-search .cm-button': {
    padding: '4px 9px',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    backgroundImage: 'none',
    backgroundColor: 'var(--bg-paper)',
    color: 'var(--ink)',
    cursor: 'pointer',
  },
  '.cm-search .cm-button:hover': {
    borderColor: 'var(--accent)',
    color: 'var(--accent)',
  },
  '.cm-search label': {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    color: 'var(--ink-muted)',
  },
  '.cm-search input[type="checkbox"]': {
    accentColor: 'var(--accent)',
  },
  '.cm-search [name="close"]': {
    marginLeft: 'auto',
    color: 'var(--ink-muted)',
    backgroundColor: 'transparent',
    border: '0',
    fontSize: '1.1429rem',
  },
})

export function lineNumbersExtension(enabled: boolean): Extension {
  return enabled ? [lineNumbers(), highlightActiveLineGutter()] : []
}

export function wordWrapExtension(enabled: boolean): Extension {
  return enabled ? EditorView.lineWrapping : []
}

const PLAIN_CODE_LANGUAGES = new Set(['text', 'plaintext', 'plain', 'txt', 'none', 'raw', 'log'])

export function resolveCodeLanguage(info: string): LanguageDescription | null {
  const token = info.trim().split(/\s+/)[0]
  if (!token) return null
  if (PLAIN_CODE_LANGUAGES.has(token.toLowerCase())) return null
  return LanguageDescription.matchLanguageName(languages, token, false)
    ?? (!token.includes('.') ? LanguageDescription.matchFilename(languages, `file.${token}`) : null)
}

export function resolveLanguageByFilename(filePath: string): LanguageDescription | null {
  const name = filePath.replace(/\\/g, '/').split('/').pop() ?? ''
  if (!name) return null
  // Match explicit filename patterns (e.g. CMakeLists.txt, Dockerfile, Makefile) before plain-text filters.
  const byFilename = languages.find((desc) => desc.filename?.test(name))
  if (byFilename) return byFilename
  const lower = name.toLowerCase()
  const dot = lower.lastIndexOf('.')
  if (dot > 0 && PLAIN_CODE_LANGUAGES.has(lower.slice(dot + 1))) return null
  return LanguageDescription.matchFilename(languages, name)
    ?? LanguageDescription.matchFilename(languages, lower)
}

export function isClickOnScrollbar(event: MouseEvent, container: HTMLElement): boolean {
  const rect = container.getBoundingClientRect()
  const onVertical = container.scrollHeight > container.clientHeight
    && event.clientX >= rect.left + container.clientWidth
  const onHorizontal = container.scrollWidth > container.clientWidth
    && event.clientY >= rect.top + container.clientHeight
  return onVertical || onHorizontal
}

export function createBaseEditorExtensions(
  extra: Extension[],
  extraKeymap: readonly KeyBinding[] = [],
): Extension[] {
  return [
    history(),
    drawSelection(),
    dropCursor(),
    EditorState.allowMultipleSelections.of(true),
    indentOnInput(),
    bracketMatching(),
    closeBrackets(),
    highlightActiveLine(),
    highlightSelectionMatches(),
    foldGutter({ markerDOM: createFoldMarker }),
    search({ top: true }),
    syntaxHighlighting(acornHighlightStyle),
    acornEditorTheme,
    keymap.of([
      indentWithTab,
      ...extraKeymap,
      ...closeBracketsKeymap,
      ...defaultKeymap,
      ...searchKeymap,
      ...historyKeymap,
      ...foldKeymap,
    ]),
    ...extra,
  ]
}

export function buildBreadcrumb(filePath: string | null, rootName: string): { prefix: string; file: string } {
  if (!filePath) return { prefix: '', file: '' }
  const parts = filePath.replace(/\\/g, '/').split('/').filter(Boolean)
  const file = parts.pop() ?? filePath
  const dirs = rootName ? [rootName, ...parts] : parts
  return {
    prefix: dirs.length ? `${dirs.join(' / ')} / ` : '',
    file,
  }
}
