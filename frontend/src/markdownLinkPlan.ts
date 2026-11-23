import { markdownLinkRanges, type MarkdownLinkRange } from './markdownLinkRanges'

/** Keep the exact source ranges alongside the targets sent to Python. */
export function collectMarkdownTargets(source: string): MarkdownLinkRange[] {
  return markdownLinkRanges(source)
}

/** Apply replacements returned in the same order as the collected targets. */
export function applyMarkdownTargetReplacements(
  source: string,
  ranges: readonly MarkdownLinkRange[],
  replacements: readonly (string | null)[],
): string {
  if (ranges.length !== replacements.length) throw new Error('Unexpected replacement count')

  const edits = ranges.map((range, index) => ({ ...range, replacement: replacements[index] }))
  edits.sort((a, b) => a.from - b.from || a.to - b.to)
  let previousEnd = 0
  for (const edit of edits) {
    if (!Number.isInteger(edit.from) || !Number.isInteger(edit.to) || edit.from < previousEnd || edit.to < edit.from || edit.to > source.length || source.slice(edit.from, edit.to) !== edit.target) {
      throw new Error('Invalid or stale Markdown target range')
    }
    if (edit.replacement !== null && typeof edit.replacement !== 'string') throw new Error('Invalid Markdown target replacement')
    previousEnd = edit.to
  }

  let result = source
  for (const edit of edits.reverse()) {
    if (edit.replacement !== null && edit.replacement !== edit.target) {
      result = result.slice(0, edit.from) + edit.replacement + result.slice(edit.to)
    }
  }
  return result
}

interface NoteSnapshot { path: string; content: string; version: string }
interface PlanBridge {
  list_plan_notes(workspaceId: string): Promise<string[]>
  read_plan_notes(workspaceId: string, paths: string[], start: number, maxBytes: number, maxNotes: number): Promise<{ notes: NoteSnapshot[]; next_index: number }>
  plan_link_targets_batch(workspaceId: string, source: string, destination: string, notes: { path: string; targets: string[] }[]): Promise<(string | null)[][]>
}

/** Prepare note rewrites without changing any workspace file. */
export async function planMoveLinks(
  api: PlanBridge, workspaceId: string, source: string, destination: string, signal?: AbortSignal,
): Promise<NoteSnapshot[]> {
  const paths = await api.list_plan_notes(workspaceId)
  signal?.throwIfAborted()
  const rewrites: NoteSnapshot[] = []
  let index = 0
  while (index < paths.length) {
    const batch = await api.read_plan_notes(workspaceId, paths, index, 2_000_000, 50)
    signal?.throwIfAborted()
    if (batch.next_index <= index || batch.next_index > paths.length || batch.notes.length !== batch.next_index - index) throw new Error('Invalid note batch')
    const candidates = batch.notes.map(note => ({ note, ranges: collectMarkdownTargets(note.content) })).filter(item => item.ranges.length)
    const replacements = candidates.length ? await api.plan_link_targets_batch(workspaceId, source, destination, candidates.map(({ note, ranges }) => ({ path: note.path, targets: ranges.map(range => range.target) }))) : []
    signal?.throwIfAborted()
    if (replacements.length !== candidates.length) throw new Error('Invalid target batch')
    for (const [position, { note, ranges }] of candidates.entries()) {
      const content = applyMarkdownTargetReplacements(note.content, ranges, replacements[position])
      if (content !== note.content) rewrites.push({ ...note, content })
    }
    index = batch.next_index
    await new Promise<void>(resolve => setTimeout(resolve, 0))
    signal?.throwIfAborted()
  }
  return rewrites
}
