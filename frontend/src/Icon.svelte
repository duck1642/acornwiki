<script lang="ts">
  type IconName = 'arrow-left' | 'arrow-right' | 'code' | 'file' | 'file-plus' | 'file-text' | 'folder' | 'folder-plus' | 'image' | 'markdown' | 'move' | 'network' | 'panel-right' | 'pdf' | 'refresh' | 'settings' | 'sort' | 'terminal'

  let { name, size = 16, class: className = '' }: {
    name: IconName
    size?: number
    class?: string
  } = $props()
</script>

<svg
  class={className}
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.8"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  focusable="false"
>
  {#if name === 'arrow-left'}
    <path d="M19 12H5" />
    <path d="m12 19-7-7 7-7" />
  {:else if name === 'arrow-right'}
    <path d="M5 12h14" />
    <path d="m12 5 7 7-7 7" />
  {:else if name === 'folder' || name === 'folder-plus'}
    <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
    {#if name === 'folder-plus'}
      <path d="M12 13h6" />
      <path d="M15 10v6" />
    {/if}
  {:else if name === 'image'}
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="9" cy="9" r="1.5" />
    <path d="m21 15-5-5L5 21" />
  {:else if name === 'code'}
    <path d="m8 9-3 3 3 3" />
    <path d="m16 9 3 3-3 3" />
    <path d="m13 7-2 10" />
  {:else if name === 'network'}
    <rect x="16" y="16" width="6" height="6" rx="1" />
    <rect x="2" y="16" width="6" height="6" rx="1" />
    <rect x="9" y="2" width="6" height="6" rx="1" />
    <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3" />
    <path d="M12 12V8" />
  {:else if name === 'terminal'}
    <path d="M12 19h8" />
    <path d="m4 17 6-6-6-6" />
  {:else if name === 'settings'}
    <path d="M9.67 4.14a2.34 2.34 0 0 1 4.66 0 2.34 2.34 0 0 0 3.32 1.91 2.34 2.34 0 0 1 2.33 4.04 2.34 2.34 0 0 0 0 3.83 2.34 2.34 0 0 1-2.33 4.03 2.34 2.34 0 0 0-3.32 1.92 2.34 2.34 0 0 1-4.66 0 2.34 2.34 0 0 0-3.32-1.92 2.34 2.34 0 0 1-2.33-4.03 2.34 2.34 0 0 0 0-3.83 2.34 2.34 0 0 1 2.33-4.04 2.34 2.34 0 0 0 3.32-1.91" />
    <circle cx="12" cy="12" r="3" />
  {:else if name === 'file' || name === 'file-text' || name === 'markdown' || name === 'file-plus' || name === 'pdf'}
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
    <path d="M14 2v6h6" />
    {#if name === 'file-text' || name === 'markdown'}
      <path d="M8 13h8" />
      <path d="M8 17h6" />
    {:else if name === 'pdf'}
      <path d="M8 13h8" />
      <path d="M8 17h5" />
    {:else if name === 'file-plus'}
      <path d="M12 18h4" />
      <path d="M14 16v4" />
    {/if}
  {:else if name === 'sort'}
    <path d="M3 6h12M3 11h8M3 16h4M19 4v14m-3-3 3 3 3-3" />
  {:else if name === 'panel-right'}
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="M15 3v18" />
  {:else if name === 'refresh'}
    <path d="M20 7v5h-5" />
    <path d="M4 17v-5h5" />
    <path d="M5.64 5.64A9 9 0 0 1 20 12" />
    <path d="M18.36 18.36A9 9 0 0 1 4 12" />
  {:else}
    <path d="M17 3l4 4-4 4" />
    <path d="M3 7h18" />
    <path d="M7 21l-4-4 4-4" />
    <path d="M21 17H3" />
  {/if}
</svg>
