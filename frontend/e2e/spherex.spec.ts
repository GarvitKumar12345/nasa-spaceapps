import { expect, test, type Page } from '@playwright/test'

const DS = 'spherex-dr1-barnard'
const FIRST = `${DS}:2025W35_2A_0474_4:D1`

async function requireCache(page: Page) {
  const list = (await (await page.request.get('/api/datasets')).json()) as { id: string; availability: string }[]
  const d = list.find((x) => x.id === DS)
  test.skip(!d || d.availability !== 'ready', 'SPHEREx cutouts not in the local cache: cd backend && uv run python -m skyshift.providers.spherex.fetch --from-manifest')
}

async function openSpherex(page: Page) {
  await page.goto('/#/observatory')
  await expect(page.getByTestId('sky-explore')).toBeVisible({ timeout: 90_000 }) // synthetic default first
  await page.getByTestId('dataset-select').selectOption(DS)
  await expect(page.getByTestId('observed-banner')).toBeVisible({ timeout: 90_000 })
}

test.describe('[browser] SPHEREx DR1 real-image viewer', () => {
  test.beforeEach(async ({ page }) => requireCache(page))

  test('observed frames show date, local wavelength, flags, checks and provenance; no sources requested', async ({ page }) => {
    const sourceCalls: string[] = []
    const pixelCalls: { url: string; dtype: string | null; origin: string | null }[] = []
    page.on('request', (r) => r.url().includes(`/api/datasets/${DS}/sources`) && sourceCalls.push(r.url()))
    page.on('response', (r) => {
      const url = decodeURIComponent(r.url())
      if (url.includes(`/api/datasets/${DS}/frames/`)) pixelCalls.push({ url, dtype: r.headers()['x-skyshift-dtype'] ?? null, origin: r.headers()['x-skyshift-origin'] ?? null })
    })
    await openSpherex(page)
    await expect(page.getByText('Observed data').first()).toBeVisible()
    const insp = page.getByTestId('obs-inspector')
    await expect(insp.getByTestId('obs-date')).toContainText('2025-08-30 22:47:30')
    await expect(insp.getByTestId('obs-wavelength')).toContainText('0.9038 µm')
    await expect(insp.getByTestId('obs-wavelength')).toContainText('bandwidth 0.0230 µm')
    await expect(page.getByTestId('obs-flags').locator('[data-flag="SUR_ERROR"]')).toHaveClass(/flag-photometry_mask/)
    await expect(page.getByTestId('obs-flags').locator('[data-flag="SOURCE"]')).toHaveClass(/flag-informational/)
    await expect(page.getByTestId('obs-checks')).toContainText(/\d+ checks passed/)
    await expect(page.getByTestId('obs-checks')).not.toContainText('failed')
    const prov = page.getByTestId('obs-provenance')
    await expect(prov).toContainText('spherex_dr1')
    await expect(prov).toContainText('l2b-v27-2026-231')
    await expect(prov).toContainText('pipeline 7.0.5')
    await expect(page.getByTestId('sky-explore-caption')).toContainText('archive-WCS display, not registered')
    await expect(page.getByTestId('query-marker')).toBeVisible()
    await expect.poll(() => pixelCalls.some((c) => c.url.includes(':display/pixels?plane=mask') && c.dtype === 'uint32')).toBe(true)
    await expect.poll(() => pixelCalls.some((c) => c.url.includes(':display/pixels?plane=image') && c.dtype === 'float32')).toBe(true)
    expect(sourceCalls).toEqual([])
  })

  test('blink runs only inside a wavelength-compatible group; the single-frame group explains why not', async ({ page }) => {
    await openSpherex(page)
    await expect(page.getByTestId('group-select')).toHaveValue('D1-g1')
    const blink = page.getByTestId('blink')
    await expect(blink).toBeEnabled()
    await blink.click()
    await expect(page.getByTestId('sky-explore-caption')).toContainText('2026-03-11', { timeout: 10_000 }) // epoch B of the group
    await blink.click()
    await expect(blink).toHaveAttribute('aria-pressed', 'false')

    await page.getByTestId('group-select').selectOption('D1-single1')
    await expect(blink).toBeDisabled()
    await expect(page.getByTestId('blink-reason')).toContainText('Single observation')
    await expect(page.getByTestId('obs-wavelength')).toContainText('0.8830 µm') // same detector, different local wavelength
    await page.locator('body').press('b')
    await expect(blink).toHaveAttribute('aria-pressed', 'false')
  })

  test('Analyze: compatibility, archive query and unavailable analyses; mode switch keeps the selection', async ({ page }) => {
    await openSpherex(page)
    await page.getByTestId('group-select').selectOption('D3-g2')
    const readout = await page.getByTestId('epoch-readout').textContent()
    await page.getByTestId('mode-switch').locator('[data-value="analyze"]').click()
    await expect(page.getByTestId('sky-a')).toBeVisible()
    await expect(page.getByTestId('sky-b')).toBeVisible()
    await expect(page.getByTestId('obs-table').locator('tbody tr')).toHaveCount(17)
    await page.getByTestId('compare-view').locator('[data-value="difference"]').click()
    await expect(page.getByTestId('difference-unavailable')).toContainText('Difference imaging is unavailable')
    await page.getByRole('tab', { name: 'Wavelength compatibility' }).click()
    await expect(page.getByTestId('compat-table').locator('tbody tr')).toHaveCount(7)
    await expect(page.getByTestId('compat-table').locator('[data-band="D1-single1"]')).toContainText('not allowed')
    await page.getByRole('tab', { name: 'Archive & provenance' }).click()
    await expect(page.getByTestId('archive-query-url')).toContainText('COLLECTION=spherex_dr1')
    await expect(page.getByTestId('archive-summary')).toContainText('239 discovered')
    await page.getByRole('tab', { name: 'Unavailable analyses' }).click()
    for (const cap of ['source_measurement', 'astrometric_fit', 'difference_imaging', 'registration']) {
      await expect(page.getByTestId('capabilities').locator(`[data-capability="${cap}"]`)).toContainText('unavailable')
    }
    await page.getByTestId('mode-switch').locator('[data-value="explore"]').click()
    await expect(page.getByTestId('group-select')).toHaveValue('D3-g2')
    await expect(page.getByTestId('epoch-readout')).toHaveText(readout ?? '')
  })

  test('a failed download stays explicit in the timeline and the table (nothing substituted)', async ({ page }) => {
    await page.route((url) => url.pathname === `/api/datasets/${DS}`, async (route) => {
      const response = await route.fetch()
      const ds = await response.json()
      const o = ds.observations.find((x: { id: string }) => x.id === FIRST)
      o.status = 'failed'
      o.status_reason = 'download/validation failed when fetched: HTTP 502 Proxy Error'
      ds.frames = ds.frames.filter((f: { observation_id: string }) => f.observation_id !== FIRST)
      o.frame_ids = []
      await route.fulfill({ response, json: ds })
    })
    const pixelUrls: string[] = []
    let recording = false
    page.on('request', (r) => recording && r.url().includes('/pixels') && pixelUrls.push(decodeURIComponent(r.url())))
    await page.goto('/#/observatory')
    await expect(page.getByTestId('sky-explore')).toBeVisible({ timeout: 90_000 })
    recording = true // only requests made for the SPHEREx view count
    await page.getByTestId('dataset-select').selectOption(DS)
    await expect(page.getByTestId('observed-banner')).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('observed-banner')).toContainText('1 selected observation(s) are not available')
    await expect(page.getByTestId('timeline').locator('.tl-gap').filter({ hasText: 'failed' })).toHaveCount(1)
    await expect(page.getByTestId('obs-inspector').getByTestId('obs-date')).not.toContainText('2025-08-30 22:47:30')
    await page.getByTestId('mode-switch').locator('[data-value="analyze"]').click()
    await expect(page.getByTestId('obs-table').locator(`[data-obs-id="${FIRST}"]`)).toContainText('failed')
    expect(pixelUrls.filter((u) => u.includes(FIRST))).toEqual([])
    expect(pixelUrls.length).toBeGreaterThan(0)
    expect(pixelUrls.every((u) => u.includes(`/api/datasets/${DS}/frames/`))).toBe(true)
  })

  test('an unavailable provider is reported, with a way back to the training data (no synthetic fallback)', async ({ page }) => {
    await page.route((url) => url.pathname === `/api/datasets/${DS}`, (route) =>
      route.fulfill({ status: 503, json: { detail: { code: 'provider_unavailable', message: 'spherex: load_dataset unavailable - no retrieval manifest', details: {} } } }),
    )
    await page.goto('/#/observatory')
    await expect(page.getByTestId('sky-explore')).toBeVisible({ timeout: 90_000 })
    await page.getByTestId('dataset-select').selectOption(DS)
    await expect(page.getByText('Dataset unavailable', { exact: true })).toBeVisible()
    await expect(page.getByText('no retrieval manifest')).toBeVisible()
    await expect(page.getByTestId('sky-explore')).toHaveCount(0)
    await page.getByTestId('open-other-dataset').click()
    await expect(page.getByTestId('sky-explore')).toBeVisible({ timeout: 90_000 })
    await expect(page.getByText('Simulated data').first()).toBeVisible()
  })

  test('phone-width layout has no horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 860 })
    await openSpherex(page)
    await expect(page.getByTestId('obs-inspector')).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })
})
