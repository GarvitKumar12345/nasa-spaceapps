/* Display formatting. Never used as input to calculations. */

export const DASH = '—'

export function isNum(x: unknown): x is number {
  return typeof x === 'number' && Number.isFinite(x)
}

export function fmt(x: number | null | undefined, digits = 3): string {
  return isNum(x) ? x.toFixed(digits) : DASH
}

export function fmtSigned(x: number | null | undefined, digits = 3): string {
  if (!isNum(x)) return DASH
  const s = x.toFixed(digits)
  return x >= 0 && !s.startsWith('-') ? `+${s}` : s
}

export function fmtInt(x: number | null | undefined): string {
  return isNum(x) ? Math.round(x).toLocaleString('en-US') : DASH
}

/** Decimal places that show `sigma` to two significant figures. */
export function decimalsForSigma(sigma: number): number {
  if (!isNum(sigma) || sigma <= 0) return 2
  const d = 1 - Math.floor(Math.log10(sigma))
  return Math.max(0, Math.min(8, d))
}

/** "640.2 ± 1.3" with the value rounded to the precision of its uncertainty. */
export function fmtPm(value: number | null | undefined, sigma: number | null | undefined, unit = ''): string {
  if (!isNum(value)) return DASH
  const suffix = unit ? ` ${unit}` : ''
  if (!isNum(sigma)) return `${value.toPrecision(6)}${suffix}`
  const d = decimalsForSigma(sigma)
  return `${value.toFixed(d)} ± ${sigma.toFixed(d)}${suffix}`
}

export function fmtRaHms(raDeg: number | null | undefined, secDecimals = 3): string {
  if (!isNum(raDeg)) return DASH
  let totalSec = (((raDeg % 360) + 360) % 360) / 15 * 3600
  totalSec = Number(totalSec.toFixed(secDecimals))
  if (totalSec >= 86400) totalSec -= 86400
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec - h * 3600) / 60)
  const s = totalSec - h * 3600 - m * 60
  return `${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m ${s.toFixed(secDecimals).padStart(secDecimals + 3, '0')}s`
}

export function fmtDecDms(decDeg: number | null | undefined, secDecimals = 2): string {
  if (!isNum(decDeg)) return DASH
  const sign = decDeg < 0 ? '−' : '+'
  let totalSec = Number((Math.abs(decDeg) * 3600).toFixed(secDecimals))
  const d = Math.floor(totalSec / 3600)
  totalSec -= d * 3600
  const m = Math.floor(totalSec / 60)
  const s = totalSec - m * 60
  return `${sign}${String(d).padStart(2, '0')}° ${String(m).padStart(2, '0')}′ ${s.toFixed(secDecimals).padStart(secDecimals + 3, '0')}″`
}

/** "2025-01-08 03:11:30 UTC" from an ISO string (assumed UTC). */
export function fmtUtc(iso: string | null | undefined, withSeconds = true): string {
  if (!iso) return DASH
  const [date, time = ''] = iso.split('T')
  const t = time.replace('Z', '').split('.')[0]
  return `${date} ${withSeconds ? t : t.slice(0, 5)} UTC`
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH
  return iso.split('T')[0]
}

export const MJD_J2000 = 51544.5
export function mjdTdbToJyear(mjdTdb: number): number {
  return 2000 + (mjdTdb - MJD_J2000) / 365.25
}
export function jyearToMjdTdb(jyear: number): number {
  return MJD_J2000 + (jyear - 2000) * 365.25
}

/** Rough calendar date (display only) for a Julian year. */
export function jyearToDateLabel(jyear: number): string {
  const ms = Date.UTC(2000, 0, 1, 12) + (jyear - 2000) * 365.25 * 86400_000
  return new Date(ms).toISOString().slice(0, 10)
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function titleCase(s: string): string {
  return s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}
