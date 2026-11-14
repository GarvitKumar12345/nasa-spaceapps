/* Cross-section actions started from the Observatory. */
import type { ViewState } from '../../api/types'
import { useAppStore } from '../../state/app'
import { useMotionStore } from '../../state/motion'
import { buildEvidenceRecord, useNotebookStore } from '../../state/notebook'
import { isFitStale, registeredFrameId, useObservatoryStore } from '../../state/observatory'

export async function saveCandidate(): Promise<{ ok: boolean; message: string }> {
  const announce = useAppStore.getState().announce
  let s = useObservatoryStore.getState()
  if (s.dataset.status !== 'ready' || s.sources.status !== 'ready' || !s.selectedSourceId) return { ok: false, message: 'Select a source first.' }
  if (s.measurements.status !== 'ready') return { ok: false, message: 'Measurements are still loading.' }
  const dataset = s.dataset.data
  // Simulated investigations keep their truth separately in the record (never mixed into measurements).
  if (dataset.origin === 'simulated' && s.truth.status !== 'ready') {
    await s.loadTruth()
    s = useObservatoryStore.getState()
  }
  // Catalog associations belong in the record even if the Catalog tab was never opened.
  if (s.associations.status !== 'ready') {
    await s.loadAssociations()
    s = useObservatoryStore.getState()
  }
  const source = s.sources.status === 'ready' ? s.sources.data.find((x) => x.id === s.selectedSourceId) : undefined
  if (!source || s.measurements.status !== 'ready') return { ok: false, message: 'Selected source is not available.' }
  const obsA = dataset.observations.find((o) => o.id === s.epochObsId)
  const obsB = dataset.observations.find((o) => o.id === s.compareObsId)
  const frameIds = [registeredFrameId(obsA), s.mode === 'analyze' ? registeredFrameId(obsB) : null].filter((v): v is string => !!v)
  const view: ViewState = {
    mode: s.mode,
    band_id: s.bandId,
    frame_id: registeredFrameId(obsA),
    compare_frame_id: registeredFrameId(obsB),
    center_x_px: s.view.cx,
    center_y_px: s.view.cy,
    zoom: s.view.zoom,
    fov_arcsec: dataset.field.fov_arcsec,
    stretch: { kind: s.display.stretch, p_low: s.display.pLow, p_high: s.display.pHigh },
  }
  try {
    const record = buildEvidenceRecord(
      {
        dataset,
        source,
        bandIds: dataset.bands.map((b) => b.id),
        frameIds,
        view,
        measurementSet: s.measurements.data,
        excludedIds: s.excludedIds,
        fit: s.fit.status === 'ready' ? s.fit.data : null,
        fitStale: isFitStale(s),
        associations: s.associations.status === 'ready' ? s.associations.data : null,
        truth: s.truth.status === 'ready' ? s.truth.data : null,
        title: `${source.label} — ${dataset.title}`,
      },
      new Date().toISOString(),
      crypto.randomUUID(),
    )
    useNotebookStore.getState().addRecord(record)
    const message = `${source.label} saved to the Evidence notebook as a ${record.record_label}.`
    announce(message)
    return { ok: true, message }
  } catch (e) {
    return { ok: false, message: e instanceof Error ? e.message : String(e) }
  }
}

export function canExplainMotion(): { ok: boolean; reason: string } {
  const s = useObservatoryStore.getState()
  if (s.fit.status !== 'ready') return { ok: false, reason: 'Run a motion fit in Analyze first; the Motion lab then uses the fitted values.' }
  if (s.fit.data.model === 'static') return { ok: false, reason: 'The current fit is a static model (no motion to explain).' }
  return { ok: true, reason: '' }
}

export function explainInMotionLab(): void {
  const s = useObservatoryStore.getState()
  const app = useAppStore.getState()
  if (s.fit.status === 'ready' && s.dataset.status === 'ready' && s.fit.data.model !== 'static') {
    const p = Object.fromEntries(s.fit.data.parameters.map((q) => [q.name, q]))
    const ref = s.fit.data.inputs.reference_position
    useMotionStore.getState().loadNearbyFromFit({
      eclipticNorthPaDeg: eclipticNorthPositionAngleDeg(ref.ra_deg, ref.dec_deg),
      pmra: p.pmra?.value ?? null,
      pmdec: p.pmdec?.value ?? null,
      parallax: p.parallax?.status === 'estimated' ? (p.parallax.value ?? null) : null,
      parallaxSigma: p.parallax?.status === 'estimated' ? (p.parallax.uncertainty ?? null) : null,
      eclipticLatDeg: s.dataset.data.field.ecliptic_lat_deg ?? null,
      label: s.selectedSourceId ?? 'source',
      fitId: s.fit.data.id,
    })
  }
  app.setSection('motion')
}

/** Position angle (deg, east of equatorial north) of the ecliptic north pole (J2000: RA 270 deg, Dec 66.5607 deg) seen from (ra, dec). */
export function eclipticNorthPositionAngleDeg(raDeg: number, decDeg: number): number {
  const d2r = Math.PI / 180
  const ap = 270 * d2r
  const dp = (90 - 23.4392911) * d2r
  const a = raDeg * d2r
  const d = decDeg * d2r
  return (Math.atan2(Math.sin(ap - a) * Math.cos(dp), Math.cos(d) * Math.sin(dp) - Math.sin(d) * Math.cos(dp) * Math.cos(ap - a)) / d2r)
}
