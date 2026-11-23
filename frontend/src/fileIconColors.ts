// Adjust each group hue against the actual file panel background, not a fixed theme name.
const hues: Record<string, number> = { pdf: 4, spreadsheet: 145, presentation: 27, book: 210, image: 42, video: 42, audio: 42, archive: 55, config: 190, 'code-file': 210, document: 210, code: 210 }
type RGB = [number, number, number]
function luminance(rgb: RGB): number {
  const channels = rgb.map((value) => { const c = value / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 })
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}
function color(hue: number, lightness: number): RGB {
  const l = lightness / 100, a = 0.6 * Math.min(l, 1 - l)
  const channel = (n: number) => { const k = (n + hue / 30) % 12; return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))) }
  return [channel(0), channel(8), channel(4)]
}
export function setFileIconColors(root: HTMLElement): void {
  const background = getComputedStyle(root).getPropertyValue('--bg-panel').trim()
  const probe = document.createElement('span')
  probe.style.color = background
  root.appendChild(probe)
  const match = getComputedStyle(probe).color.match(/^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/)
  probe.remove()
  if (!match) return
  const bg: RGB = [Number(match[1]), Number(match[2]), Number(match[3])]
  const bgLuminance = luminance(bg), preferred = bgLuminance < 0.3 ? 70 : 39
  for (const [name, hue] of Object.entries(hues)) {
    let best: RGB | undefined, distance = Infinity
    for (let lightness = 1; lightness <= 99; lightness++) {
      const rgb = color(hue, lightness), l = luminance(rgb)
      const contrast = (Math.max(l, bgLuminance) + 0.05) / (Math.min(l, bgLuminance) + 0.05)
      if (contrast >= 4.5 && Math.abs(lightness - preferred) < distance) { best = rgb; distance = Math.abs(lightness - preferred) }
    }
    if (best) root.style.setProperty(`--file-icon-${name}`, `rgb(${best.join(' ')})`)
  }
}
