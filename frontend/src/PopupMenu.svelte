<script lang="ts">
  import { onMount, type Snippet } from 'svelte'

  let { children, class: className = '', label }: { children: Snippet; class?: string; label?: string } = $props()
  let surface: HTMLDivElement

  onMount(() => {
    const details = surface.closest('details')
    if (!details) return
    function closeOutside(event: PointerEvent) {
      if (details?.open && !details.contains(event.target as Node)) details.open = false
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || !details?.open) return
      details.open = false
      details.querySelector('summary')?.focus()
      event.stopPropagation()
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  })
</script>

<div bind:this={surface} class={`popup-menu ${className}`} role={label ? 'group' : undefined} aria-label={label}>
  {@render children()}
</div>
