<script lang="ts">
  import Icon from './Icon.svelte'
  import PanelResizeHandle from './PanelResizeHandle.svelte'
  import type { FlatOutlineHeading } from './sharedTypes'

  type OutlineHeading = FlatOutlineHeading & { children: OutlineHeading[] }

  const loadingIndicatorDelay = 400

  let {
    open,
    noteKey,
    headings,
    width,
    onResize,
    onJump,
  }: {
    open: boolean
    noteKey: string | null
    headings: FlatOutlineHeading[] | undefined
    width: number
    onResize: (width: number) => void
    onJump: (id: string) => void
  } = $props()

  let filter = $state('')
  let expandedIds = $state<string[]>([])
  let lastSignature = ''
  let showLoading = $state(false)

  let loading = $derived(Boolean(noteKey) && headings === undefined)
  let items = $derived(headings ?? [])
  let tree = $derived(buildOutlineTree(items))
  let filterIsActive = $derived(Boolean(filter.trim()))
  let filtered = $derived(filterOutline(tree, filter.trim().toLowerCase()))
  let expandableIds = $derived(collectExpandableIds(tree))
  let allExpanded = $derived(expandableIds.length > 0 && expandableIds.every((id) => expandedIds.includes(id)))

  $effect(() => {
    const key = noteKey
    if (!loading || !key) { showLoading = false; return }
    showLoading = false
    const timer = setTimeout(() => { showLoading = true }, loadingIndicatorDelay)
    return () => clearTimeout(timer)
  })

  $effect(() => {
    const signature = `${noteKey ?? ''}\n${items.map((heading) => `${heading.id}:${heading.level}`).join('\n')}`
    if (signature === lastSignature) return
    lastSignature = signature
    expandedIds = collectExpandableIds(tree)
  })

  function buildOutlineTree(flat: FlatOutlineHeading[]): OutlineHeading[] {
    const roots: OutlineHeading[] = []
    const parents: OutlineHeading[] = []
    for (const heading of flat) {
      const node: OutlineHeading = { ...heading, children: [] }
      while (parents.length && parents[parents.length - 1].level >= node.level) parents.pop()
      const parent = parents[parents.length - 1]
      if (parent) parent.children.push(node)
      else roots.push(node)
      parents.push(node)
    }
    return roots
  }

  function filterOutline(nodes: OutlineHeading[], query: string): OutlineHeading[] {
    if (!query) return nodes
    return nodes.flatMap((node) => {
      const children = filterOutline(node.children, query)
      return node.label.toLowerCase().includes(query) || children.length ? [{ ...node, children }] : []
    })
  }

  function collectExpandableIds(nodes: OutlineHeading[]): string[] {
    const ids: string[] = []
    for (const node of nodes) {
      if (node.children.length) {
        ids.push(node.id, ...collectExpandableIds(node.children))
      }
    }
    return ids
  }

  function toggleNode(id: string) {
    expandedIds = expandedIds.includes(id)
      ? expandedIds.filter((item) => item !== id)
      : [...expandedIds, id]
  }

  function toggleAll() {
    expandedIds = allExpanded ? [] : [...expandableIds]
  }

  function handleJump(event: MouseEvent, id: string) {
    event.preventDefault()
    onJump(id)
  }
</script>

{#if open}
  <aside class="note-outline" aria-label="Contents">
    <PanelResizeHandle side="right" {width} onresize={onResize} />
    <div class="outline-heading">
      <h2 class="outline-title">Contents</h2>
      <button
        class="outline-collapse-all"
        aria-label={filterIsActive || allExpanded ? 'Collapse all headings' : 'Expand all headings'}
        title={filterIsActive ? 'Clear the filter to change heading expansion' : allExpanded ? 'Collapse all headings' : 'Expand all headings'}
        aria-expanded={filterIsActive || allExpanded}
        disabled={expandableIds.length === 0 || filterIsActive}
        onclick={toggleAll}
      ><Icon name={filterIsActive || allExpanded ? 'collapse' : 'expand'} size={16} /></button>
    </div>
    <input class="outline-filter" type="search" aria-label="Filter headings" placeholder="Filter headings..." bind:value={filter} />
    {#if loading}
      {#if showLoading}<p class="outline-empty" role="status">Loading headings...</p>{/if}
    {:else if items.length === 0}
      <p class="outline-empty">No headings in this note.</p>
    {:else if filtered.length === 0}
      <p class="outline-empty">No headings match this filter.</p>
    {:else}
      <nav class="outline-nav" aria-label="Note headings">
        <ul>
          {@render renderHeadings(filtered, 0, filterIsActive)}
        </ul>
      </nav>
    {/if}
  </aside>
{/if}

{#snippet renderHeadings(nodes: OutlineHeading[], depth: number, activeFilter: boolean)}
  {#each nodes as heading (heading.id)}
    {@const hasChildren = heading.children.length > 0}
    {@const expanded = activeFilter || expandedIds.includes(heading.id)}
    <li class="outline-row" style={`padding-left: ${2 + depth * 20}px`}>
      {#each Array(depth) as _, level}
        <span class="outline-indent-guide" aria-hidden="true" style={`left: ${10 + level * 20}px`}></span>
      {/each}
      {#if hasChildren}
        <button class="outline-caret" aria-label={expanded ? `Collapse ${heading.label}` : `Expand ${heading.label}`} aria-expanded={expanded} disabled={activeFilter} onclick={() => toggleNode(heading.id)}><Icon name={expanded ? 'chevron-down' : 'chevron-right'} /></button>
      {:else}
        <span class="outline-caret-spacer" aria-hidden="true"></span>
      {/if}
      <a class="outline-link outline-level-{heading.level}" href={`#${heading.id}`} onclick={(event) => handleJump(event, heading.id)} title={heading.label}>{heading.label}</a>
    </li>
    {#if hasChildren && expanded}
      {@render renderHeadings(heading.children, depth + 1, activeFilter)}
    {/if}
  {/each}
{/snippet}
