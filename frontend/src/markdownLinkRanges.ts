import { commonmarkLanguage } from '@codemirror/lang-markdown'

export interface MarkdownLinkRange {
  from: number
  to: number
  target: string
}

/** Find source ranges of Markdown link and image targets, including reference definitions. */
export function markdownLinkRanges(source: string): MarkdownLinkRange[] {
  const ranges: MarkdownLinkRange[] = []
  // Lezer needs LF line endings; retain a map back to the original UTF-16 offsets.
  let normalized = ''
  const offsets = [0]
  for (let i = 0; i < source.length; i++) {
    if (source[i] === '\r') {
      if (source[i + 1] === '\n') i++
      normalized += '\n'
    } else normalized += source[i]
    offsets.push(i + 1)
  }
  const tree = commonmarkLanguage.parser.parse(normalized)
  tree.iterate({
    enter(node) {
      if (node.name !== 'URL') return
      const parent = node.node.parent?.name
      if (parent !== 'Link' && parent !== 'Image' && parent !== 'LinkReference') return
      const parentNode = node.node.parent
      const prefix = normalized.slice(0, parentNode?.from ?? node.from)
      if (/(?<![\p{L}\p{N}_])(?:https?:\/\/|www\.)[^\s<>]*$/iu.test(prefix)) throw new Error('Cannot safely update a link inside an automatic web address')
      const from = offsets[node.from], to = offsets[node.to]
      ranges.push({ from, to, target: source.slice(from, to) })
    },
  })
  return ranges
}
