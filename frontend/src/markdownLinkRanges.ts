import { commonmarkLanguage } from '@codemirror/lang-markdown'

export interface MarkdownLinkRange {
  from: number
  to: number
  target: string
}

/** Find source ranges of Markdown link and image targets, including reference definitions. */
export function markdownLinkRanges(source: string): MarkdownLinkRange[] {
  const ranges: MarkdownLinkRange[] = []
  const tree = commonmarkLanguage.parser.parse(source)
  tree.iterate({
    enter(node) {
      if (node.name !== 'URL') return
      const parent = node.node.parent?.name
      if (parent !== 'Link' && parent !== 'Image' && parent !== 'LinkReference') return
      ranges.push({ from: node.from, to: node.to, target: source.slice(node.from, node.to) })
    },
  })
  return ranges
}
