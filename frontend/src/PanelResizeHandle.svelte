<script lang="ts">
  let { side, width, onresize }: { side: 'left' | 'right'; width: number; onresize: (width: number) => void } = $props()
  let drag: { pointer: number; startX: number; startWidth: number } | null = null
  let dragging = $state(false)

  function start(event: PointerEvent) {
    if (event.button !== 0) return
    const handle = event.currentTarget as HTMLElement
    drag = { pointer: event.pointerId, startX: event.clientX, startWidth: width }
    dragging = true
    handle.setPointerCapture(event.pointerId)
    event.preventDefault()
  }

  function move(event: PointerEvent) {
    if (!drag || drag.pointer !== event.pointerId) return
    const offset = event.clientX - drag.startX
    const value = drag.startWidth + (side === 'left' ? offset : -offset)
    onresize(Math.round(Math.min(side === 'left' ? 400 : 360, Math.max(side === 'left' ? 180 : 160, value))))
  }

  function stop(event: PointerEvent) {
    if (drag?.pointer !== event.pointerId) return
    drag = null
    dragging = false
  }
</script>

<div class="panel-resize-handle" class:right-handle={side === 'right'} class:dragging role="separator" aria-orientation="vertical" aria-label={side === 'left' ? 'Resize files panel' : 'Resize contents panel'} onpointerdown={start} onpointermove={move} onpointerup={stop} onpointercancel={stop} onlostpointercapture={stop}></div>
