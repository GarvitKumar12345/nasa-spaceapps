import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

async function fitS003(page: Page) {
  await page.goto('/#/observatory')
  await expect(page.getByTestId('sky-explore')).toBeVisible({ timeout: 60_000 })
  await page.getByTestId('search-input').fill('S003')
  await page.getByTestId('search-input').press('Enter')
  await expect(page.getByTestId('source-summary')).toContainText('S003')
  await page.getByTestId('mode-switch').locator('[data-value="analyze"]').click()
  await page.getByRole('tab', { name: 'Motion fit' }).click()
  await page.getByTestId('run-fit').click()
  await expect(page.getByTestId('fit-result')).toBeVisible()
}

test.describe('[browser] complete synthetic investigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/#/evidence')
    await page.evaluate(() => localStorage.removeItem('skyshift.notebook.v1'))
  })

  test('fit -> explain in Motion lab carries rotated fit values and gates the distance', async ({ page }) => {
    await fitS003(page)
    await page.getByTestId('analyze-explain').click()
    await expect(page).toHaveURL(/#\/motion/)
    const banner = page.getByTestId('ml-handoff')
    await expect(banner).toContainText('Parameters copied from Observatory fit S003')
    await expect(banner).toContainText('rotated by')
    await expect(banner).toContainText('1000 / parallax')
    await expect(page.getByTestId('nearby-sky-path')).toBeVisible()
    // Toggling an effect changes the computed path readout.
    const before = await page.getByTestId('ml-nearby-readouts').textContent()
    await page.getByTestId('ml-nearby-time').fill('1')
    await expect(page.getByTestId('ml-nearby-readouts')).not.toHaveText(before ?? '')
    await page.getByTestId('ml-experiment').locator('[data-value="orbit"]').click()
    await expect(page.getByTestId('orbit-plane')).toBeVisible()
    const period = await page.getByTestId('ml-orbit-readouts').locator('dd').first().textContent()
    await page.getByTestId('ml-e').fill('0.8')
    await expect(page.getByTestId('ml-orbit-readouts').locator('dd').first()).toHaveText(period ?? '') // period independent of e
  })

  test('save -> notebook persists across reload -> export JSON/CSV -> validate, reproduce, import', async ({ page }) => {
    await fitS003(page)
    await page.getByRole('tab', { name: 'Provenance & export' }).click()
    await page.getByTestId('analyze-save').click()
    // The same text is also announced in the sr-only live region; check the visible confirmation.
    await expect(page.getByRole('status').filter({ hasText: 'saved to the Evidence notebook' }).filter({ hasText: 'Open notebook' })).toBeVisible()
    await page.getByTestId('nav-evidence').click()
    await expect(page.getByTestId('ev-record-list')).toContainText('S003')
    await expect(page.getByTestId('ev-detail').getByTestId('ev-record-label').first()).toContainText(/synthetic training record/i)
    await page.reload()
    await expect(page.getByTestId('ev-record-list')).toContainText('S003')

    const [jsonDl] = await Promise.all([page.waitForEvent('download'), page.getByTestId('ev-export-json').click()])
    const jsonPath = await jsonDl.path()
    const record = JSON.parse(readFileSync(jsonPath, 'utf-8'))
    expect(record.schema_version).toBe('skyshift.evidence/1')
    expect(record.record_label).toBe('synthetic training record')
    expect(record.fit_status).toBe('current')
    expect(record.simulation.seed).toBe(20261114)
    expect(record.measurements.every((m: { origin: string }) => m.origin === 'derived_measurement')).toBe(true)
    expect(record.source.catalog_associations.length).toBeGreaterThan(0)

    const [csvDl] = await Promise.all([page.waitForEvent('download'), page.getByTestId('ev-export-csv').click()])
    const csv = readFileSync(await csvDl.path(), 'utf-8')
    expect(csv).toContain('# record_label: synthetic training record')
    expect(csv.split('\n').filter((l) => l.includes(',derived_measurement,')).length).toBe(record.measurements.length)

    await page.getByTestId('ev-validate').click()
    await expect(page.getByTestId('ev-validation-result')).toContainText(/valid/i)
    await page.getByTestId('ev-reproduce').click()
    await expect(page.getByTestId('ev-reproduction-result')).toContainText(/reproduced/i, { timeout: 60_000 })

    // Import a tampered copy: it is accepted but its fit is recomputed as stale.
    const tampered = { ...record, id: '11111111-2222-4333-8444-555555555555', title: 'tampered copy' }
    tampered.measurements = record.measurements.map((m: { ra_deg: number | null }, i: number) => (i === 0 && m.ra_deg != null ? { ...m, ra_deg: m.ra_deg + 1e-6 } : m))
    await page.getByTestId('ev-import-input').setInputFiles({ name: 'tampered.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(tampered)) })
    await expect(page.getByTestId('ev-import-result')).toContainText(/stale|imported/i)
    await expect(page.getByTestId('ev-record-list')).toContainText('tampered copy')
  })

  test('Methods shows real provider statuses and never claims unrun live checks', async ({ page }) => {
    // WISE / NEOSSat stay documented with live checks not run; SPHEREx and Gaia DR3 are implemented (their live checks come from the report).
    await page.goto('/#/methods')
    const providers = page.getByTestId('provider-table')
    await expect(providers.locator('[data-provider="spherex"]')).toContainText('implemented')
    await expect(providers.locator('[data-provider="gaia_dr3"]')).toContainText('implemented')
    await expect(providers.locator('[data-provider="wise"]')).toContainText('documented')
    await expect(page.getByTestId('live-group')).toContainText('not run')
    await expect(page.getByTestId('limitations')).toContainText('Target measurements on synthetic data only')
    await expect(page.getByTestId('limitations')).toContainText('Gaia DR3 overlays are model predictions')
    await expect(page.locator('[data-group="Archive product checks (SPHEREx DR1, Gaia DR3)"]')).toBeVisible()
  })

  test('corrupted notebook storage is reported, not silently discarded', async ({ page }) => {
    await page.goto('/#/evidence')
    await page.evaluate(() => localStorage.setItem('skyshift.notebook.v1', '{not json'))
    await page.reload()
    await expect(page.getByTestId('ev-load-error')).toBeVisible()
    await expect(page.getByTestId('ev-download-raw')).toBeEnabled()
  })
})
