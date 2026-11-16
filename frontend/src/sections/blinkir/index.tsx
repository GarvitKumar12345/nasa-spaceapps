import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../../state/app'
import { downloadText } from '../evidence/helpers'
import './blinkir.css'

type Preset = { id: string; name: string; category: string; ra: number; dec: number; fov_deg: number }
type Sample = { wavelength_um: number; value: number; background_value: number; detector: number }
type Scene = { origin: 'simulated'; preset: Preset; images: number[][][]; epochs: string[]; spectrum: Sample[]; limitations: string[]; quality: string; generator: string }
type Mode = 'compare' | 'blink' | 'difference'

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(`/api/blinkir/${path}`, { signal })
  if (!r.ok) { const data = await r.json().catch(() => ({})) as { detail?: string }; throw new Error(data.detail ?? `Request failed (${r.status})`) }
  return r.json() as Promise<T>
}

function Pixels({ image, difference, label, zoom, point, onPick }: { image: number[][]; difference?: boolean; label: string; zoom: number; point: [number, number]; onPick: (p: [number, number]) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = canvas.current, ctx = c?.getContext('2d')
    if (!c || !ctx) return
    const off = document.createElement('canvas'); off.width = off.height = 64
    const oc = off.getContext('2d')!; const pixels = oc.createImageData(64, 64)
    for (let y = 0; y < 64; y++) for (let x = 0; x < 64; x++) {
      const value = image[y]![x]!, a = Math.min(1, Math.asinh(Math.abs(value) * 3) / Math.asinh(15)), i = (y * 64 + x) * 4
      const rgb = difference ? (value >= 0 ? [a * 255, a * 172, a * 92] : [a * 92, a * 190, a * 255]) : [a * 192, a * 225, a * 255]
      for (let k = 0; k < 3; k++) pixels.data[i + k] = rgb[k]!
      pixels.data[i + 3] = 255
    }
    oc.putImageData(pixels, 0, 0); ctx.imageSmoothingEnabled = false
    const span = 64 / zoom
    ctx.drawImage(off, 32 - span / 2, 32 - span / 2, span, span, 0, 0, c.width, c.height)
    const x = ((point[0] + .5 - 32) * zoom / 64 + .5) * c.width, y = ((point[1] + .5 - 32) * zoom / 64 + .5) * c.height
    ctx.strokeStyle = '#f6d085'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(x, y, 9, 0, 2 * Math.PI); ctx.stroke()
    ctx.strokeStyle = '#ffffff28'; ctx.beginPath(); ctx.moveTo(c.width / 2, 0); ctx.lineTo(c.width / 2, c.height); ctx.moveTo(0, c.height / 2); ctx.lineTo(c.width, c.height / 2); ctx.stroke()
  }, [image, zoom, point, difference])
  return <figure className="bi-frame"><div className="bi-frame-label">{label}</div><canvas ref={canvas} width={512} height={512} role="img" aria-label={`${label}; select a simulated pixel. Arrow keys move selection.`} tabIndex={0}
    onKeyDown={e => { const delta: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }; const d = delta[e.key]; if (d) { e.preventDefault(); onPick([Math.max(0, Math.min(63, point[0] + d[0])), Math.max(0, Math.min(63, point[1] + d[1]))]) } }}
    onClick={e => { const r = e.currentTarget.getBoundingClientRect(); onPick([Math.max(0, Math.min(63, Math.floor(32 + ((e.clientX - r.left) / r.width - .5) * 64 / zoom))), Math.max(0, Math.min(63, Math.floor(32 + ((e.clientY - r.top) / r.height - .5) * 64 / zoom)))]) }} />
    <figcaption>64 × 64 synthetic pixels · arbitrary intensity</figcaption></figure>
}

export function BlinkIR() {
  const active = useAppStore(s => s.section === 'blinkir')
  const [presets, setPresets] = useState<Preset[]>([]), [target, setTarget] = useState('WISE_0855'), [scene, setScene] = useState<Scene | null>(null)
  const [error, setError] = useState(''), [query, setQuery] = useState(''), [notice, setNotice] = useState(''), [loading, setLoading] = useState(false)
  const [reload, setReload] = useState(0)
  const [mode, setMode] = useState<Mode>('compare'), [epoch, setEpoch] = useState(0), [playing, setPlaying] = useState(false), [speed, setSpeed] = useState(700)
  const [zoom, setZoom] = useState(1), [detector, setDetector] = useState(1), [point, setPoint] = useState<[number, number]>([32, 32]), [model, setModel] = useState<'value' | 'background_value'>('value'), [sample, setSample] = useState(0), [notes, setNotes] = useState('')
  useEffect(() => { if (!active) return; const c = new AbortController(); request<{ presets: Preset[] }>('presets', c.signal).then(r => setPresets(r.presets)).catch(e => { if (!c.signal.aborted) setError(String(e)) }); return () => c.abort() }, [active])
  useEffect(() => {
    setPlaying(false)
    if (!active) return
    const c = new AbortController(); setLoading(true); setError(''); setScene(null)
    request<Scene>(`simulation/${encodeURIComponent(target)}`, c.signal).then(r => { setScene(r); setEpoch(0); setPoint([32, 32]); setZoom(1) }).catch(e => { if (!c.signal.aborted) setError(String(e)) }).finally(() => { if (!c.signal.aborted) setLoading(false) })
    return () => c.abort()
  }, [target, active, reload])
  useEffect(() => { if (!playing || !active || mode !== 'blink') return; const id = setInterval(() => setEpoch(p => 1 - p), speed); return () => clearInterval(id) }, [playing, active, mode, speed])
  const difference = useMemo(() => scene?.images[1]!.map((row, y) => row.map((v, x) => v - scene.images[0]![y]![x]!)) ?? [], [scene])
  const choose = (id: string) => { setTarget(id); setNotice(''); setPlaying(false) }
  const search = () => {
    const coords = query.split(',').map(Number)
    const p = presets.find(p => p.name.toLowerCase().includes(query.trim().toLowerCase()) || p.id.toLowerCase() === query.toLowerCase() || (coords.length === 2 && Math.abs(p.ra - coords[0]!) < .001 && Math.abs(p.dec - coords[1]!) < .001))
    if (!query.trim() || !p) setNotice('No supplied preset matches. Arbitrary name/coordinate archive lookup is unavailable.'); else choose(p.id)
  }
  const exportLesson = async () => {
    try { const r = await fetch('/api/blinkir/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ preset: target, x: point[0], y: point[1], detector, notes }) }); if (!r.ok) throw new Error(`Export failed (${r.status})`); downloadText('blinkir-simulation-lesson.json', await r.text(), 'application/json') } catch(e) { setNotice(String(e)) }
  }
  const max = scene ? Math.max(...scene.spectrum.map(p => p[model])) * 1.1 : 1
  const at = scene?.spectrum[sample]
  return <div className="page bi-page" data-testid="blinkir-page">
    <header className="bi-intro"><div><div className="eyebrow">SkyShift Explore / infrared learning studio</div><h1>BlinkIR<span>See change. Read light.</span></h1><p>Compare synthetic skies and explore the ideas behind infrared astronomy.</p></div><span className="bi-badge">Synthetic simulation</span></header>
    <div className="bi-layout">
      <aside className="bi-panel bi-mission"><div className="eyebrow">01 / Mission control</div><h2>Choose a story</h2>
        <form onSubmit={e => { e.preventDefault(); search() }}><label htmlFor="bi-search">Search supplied presets or RA, Dec</label><div className="bi-search"><input id="bi-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="WISE 0855 or 133.795129, -7.245147" /><button className="btn btn-sm">Find</button></div></form>
        <div className="bi-presets" aria-label="Guided presets">{presets.map((p, i) => <button key={p.id} className={`bi-preset ${target === p.id ? 'bi-selected' : ''}`} aria-pressed={target === p.id} onClick={() => choose(p.id)}><span className="bi-number">0{i + 1}</span><span><strong>{p.name.split(' (')[0]}</strong><small>{['Motion in a cold sky', 'A fast-moving neighbour', 'Two brown dwarfs', 'A changing young star', 'A pulsing red giant'][i]}</small></span></button>)}</div>
        {scene && <><dl className="bi-metadata"><dt>Supplied target coordinates</dt><dd>{scene.preset.ra.toFixed(6)}°, {scene.preset.dec.toFixed(6)}°</dd><dt>Display field (simulation)</dt><dd>{(scene.preset.fov_deg * 60 / zoom).toFixed(2)} arcmin</dd><dt>Image identity</dt><dd>Synthetic broadband toy scene</dd></dl><label>Display zoom <input aria-label="Display zoom" type="range" min="1" max="3" step=".25" value={zoom} onChange={e => setZoom(Number(e.target.value))} /></label></>}
        <div className="bi-real"><strong>Looking for observed evidence?</strong><p>SkyShift Discover contains recorded SPHEREx images and the van Maanen 2 motion study.</p><a href="#/observatory">Open Observatory →</a><button className="btn btn-sm" onClick={() => request('observations').catch(e => setNotice(String(e)))}>Check BlinkIR observed capability</button></div>
      </aside>
      <section className="bi-panel bi-time"><div className="bi-panel-head"><div><div className="eyebrow">02 / Infrared time machine</div><h2>{scene?.preset.name.split(' (')[0] ?? 'Loading scene'}</h2></div><span className="bi-live-dot">SIMULATED</span></div>
        <div className="bi-mode" role="group" aria-label="Comparison mode">{(['compare', 'blink', 'difference'] as Mode[]).map(m => <button className="btn btn-sm" aria-pressed={mode === m} key={m} onClick={() => { setMode(m); setPlaying(false) }}>{m === 'compare' ? 'Side by side' : m === 'blink' ? 'Blink epochs' : 'Difference B − A'}</button>)}</div>
        {loading && <p role="status">Loading synthetic scene…</p>}{error && <div className="bi-alert" role="alert">{error}<button className="btn btn-sm" onClick={() => setReload(n => n + 1)}>Retry</button></div>}
        {scene && <><div className={`bi-images ${mode === 'compare' ? 'bi-two' : ''}`} data-testid="bi-images">
          {mode === 'compare' ? scene.images.map((image, i) => <Pixels key={i} image={image} label={scene.epochs[i]!} zoom={zoom} point={point} onPick={setPoint} />) : <Pixels image={mode === 'difference' ? difference : scene.images[epoch]!} difference={mode === 'difference'} label={mode === 'difference' ? 'Synthetic difference · B − A' : scene.epochs[epoch]!} zoom={zoom} point={point} onPick={setPoint} />}
        </div><div className="bi-playback"><label>Shown epoch <select aria-label="Shown epoch" value={epoch} onChange={e => setEpoch(Number(e.target.value))}><option value={0}>Simulated A</option><option value={1}>Simulated B</option></select></label><button className="btn" disabled={mode !== 'blink'} aria-pressed={playing} onClick={() => setPlaying(p => !p)}>{playing ? 'Pause blinking' : 'Play blinking'}</button><label>Interval <select aria-label="Blink interval" value={speed} onChange={e => setSpeed(Number(e.target.value))}><option value={350}>0.35 s</option><option value={700}>0.7 s</option><option value={1200}>1.2 s</option></select></label></div>
          <p className="bi-caption">{mode === 'difference' ? 'Orange: brighter in B. Blue: brighter in A. This subtraction is a simulation preview, without PSF matching or scientific calibration.' : 'These are generated scenes with illustrative motion or variability. Epoch A and B have no observed dates.'} Same display stretch in both epochs.</p>
          <div className="bi-quality"><div><span className="eyebrow">Pixel inspector · simulation</span><p data-testid="bi-pixel">x {point[0]}, y {point[1]} · A {scene.images[0]![point[1]]![point[0]]!.toFixed(4)} · B {scene.images[1]![point[1]]![point[0]]!.toFixed(4)}</p></div><span>Archive flags: not applicable</span></div>
          <details><summary>Quality and provenance</summary><p>{scene.generator}</p><p>{scene.quality}</p><ul>{scene.limitations.map(l => <li key={l}>{l}</li>)}</ul></details></>}
      </section>
      <aside className="bi-panel bi-spectrum"><div className="eyebrow">03 / Citizen spectrometer</div><h2>The shape of light</h2><span className="bi-badge">Illustrative model spectrum</span><p className="bi-caption">102 model samples in arbitrary units. These are not measured channels or an extraction from your selected pixel.</p>
        <label>Detector wavelength context <select aria-label="Detector wavelength context" value={detector} onChange={e => setDetector(Number(e.target.value))}>{['0.75–1.09','1.10–1.62','1.63–2.41','2.42–3.82','3.83–4.41','4.42–5.00'].map((r,i) => <option key={r} value={i+1}>D{i+1} · {r} µm</option>)}</select></label>
        <label>Model curve <select aria-label="Model curve" value={model} onChange={e => setModel(e.target.value as typeof model)}><option value="value">Preset target model</option><option value="background_value">Background star model</option></select></label>
        {scene && <><svg className="bi-graph" viewBox="0 0 360 250" role="img" aria-label="Illustrative infrared model spectrum" data-testid="bi-spectrum" onMouseMove={e => { const r=e.currentTarget.getBoundingClientRect(); setSample(Math.max(0,Math.min(101,Math.round(((e.clientX-r.left)/r.width*360-36)/306*101)))) }}>
          <text x="36" y="15" fill="var(--muted)" fontSize="10">arbitrary model intensity</text>{[0,.5,1].map(f => <g key={f}><line x1="36" x2="342" y1={208-176*f} y2={208-176*f} stroke="var(--line)"/><text x="3" y={212-176*f} fontSize="10" fill="var(--muted)">{(max*f).toFixed(1)}</text></g>)}
          {[{x:3.02,l:'H₂O ref.'},{x:3.32,l:'CH₄ ref.'}].map((m,i) => <g key={m.l}><line x1={36+(m.x-.76)/4.22*306} x2={36+(m.x-.76)/4.22*306} y1="30" y2="208" stroke="var(--amber)" strokeDasharray="3 4"/><text x={36+(m.x-.76)/4.22*306} y={22+i*14} fontSize="9" fill="var(--amber)">{m.l}</text></g>)}
          <polyline points={scene.spectrum.map(p => `${36+(p.wavelength_um-.76)/4.22*306},${208-p[model]/max*176}`).join(' ')} fill="none" stroke="var(--teal)" strokeWidth="2" />
          {scene.spectrum.filter(p=>p.detector===detector).map(p=><circle key={p.wavelength_um} cx={36+(p.wavelength_um-.76)/4.22*306} cy={208-p[model]/max*176} r="2.5" fill="var(--text)"/>)}
          {[1,2,3,4,5].map(x=><text key={x} x={36+(x-.76)/4.22*306} y="226" fontSize="10" fill="var(--muted)">{x}</text>)}<text x="140" y="246" fontSize="11" fill="var(--muted)">Wavelength (µm)</text>
        </svg><label>Inspect model sample <input aria-label="Inspect model sample" type="range" min="0" max="101" value={sample} onChange={e=>setSample(Number(e.target.value))}/></label><p className="bi-sample" aria-live="polite">{at?.wavelength_um.toFixed(3)} µm · {at?.[model].toFixed(3)} arbitrary units</p></>}
        <p className="bi-caption">Reference markers alone identify no molecule, atmosphere or planet. Wavelength ranges are context; the toy images do not model the detector response.</p>
        <label>Learning notes<textarea value={notes} maxLength={2000} onChange={e=>setNotes(e.target.value)} placeholder="What changes between these scenes?" /></label><button className="btn" disabled={!scene} onClick={()=>void exportLesson()} data-testid="bi-export">Export simulation lesson</button><p className="bi-caption">Kept separate from scientific Evidence Notebook records.</p>
      </aside>
    </div>{notice && <div className="bi-alert" role="alert">{notice}</div>}
  </div>
}
