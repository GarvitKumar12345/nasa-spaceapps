import { expect, test, type Page } from '@playwright/test'

const DS = 'spherex-dr1-barnard'
const BARNARD = '4472832130942575872'

async function requireCache(page: Page) {
  const list = (await (await page.request.get('/api/datasets')).json()) as { id: string; availability: string }[]
  const d = list.find((x) => x.id === DS)
  test.skip(!d || d.availability !== 'ready', 'SPHEREx cutouts not in the local cache: cd backend && uv run python -m skyshift.providers.spherex.fetch --from-manifest')
}

async function openSpherex(page: Page) {
  await page.goto('/#/observatory')
  await expect(page.getByTestId('sky-explore')).toBeVisible({ timeout: 90_000 })
  await page.getByTestId('dataset-select').selectOption(DS)
  await expect(page.getByTestId('observed-banner')).toBeVisible({ timeout: 90_000 })
}

test.describe('[browser] Gaia DR3 predictions and alignment diagnostics on SPHEREx frames', () => {
  test.setTimeout(300_000)
  test.beforeEach(async ({ page }) => requireCache(page))

  test('predictions are drawn as model markers; selecting one separates catalogue values, prediction and image measurement', async ({ page }) => {
    await openSpherex(page)
    await expect(page.getByTestId('sky-explore-gaia')).toContainText('Gaia DR3 predictions (model)', { timeout: 240_000 })
    await expect(page.getByTestId('gaia-legend')).toContainText('Gaia DR3 prediction (model, not a measurement)')
    await expect(page.locator('[data-testid="sky-explore"] [data-kind="saturated"]')).toHaveCount(1) // Barnard's Star at the field centre
    const used = page.locator('[data-testid="sky-explore"] [data-kind="used"] rect').first()
    await expect(used).toBeVisible()
    const box = await used.boundingBox()
    await page.mouse.click((box?.x ?? 0) + (box?.width ?? 0) / 2, (box?.y ?? 0) + (box?.height ?? 0) / 2)
    const panel = page.getByTestId('gaia-panel')
    await expect(panel).toBeVisible()
    const sid = await panel.getAttribute('data-source-id')
    expect(sid).toMatch(/^[1-9]\d{15,18}$/)
    await expect(panel.getByTestId('gaia-source-id')).toHaveText(sid ?? '')
    await expect(panel.getByTestId('gaia-catalog-values')).toContainText('5-parameter')
    await expect(panel).toContainText('epoch J2016 (TCB)')
    await expect(panel.getByTestId('gaia-prediction')).toContainText('2025-08-30 22:47:30')
    await expect(panel.getByTestId('gaia-prediction')).toContainText('Observer parallax applied')
    await expect(panel.getByTestId('gaia-measurement')).toContainText('used')
    await expect(panel.getByTestId('gaia-measurement')).toContainText('Measured − predicted')
    await expect(panel.getByTestId('gaia-limitations')).toContainText('archive WCS')
    await panel.getByTestId('gaia-close').click()
    await expect(page.getByTestId('gaia-panel')).toHaveCount(0)
  })

  test('the saturated central star is a prediction with its saturation reason, never a measurement', async ({ page }) => {
    await openSpherex(page)
    const detail = await (await page.request.get(`/api/datasets/${DS}/gaia/sources/${BARNARD}?frame_id=${encodeURIComponent(`${DS}:2025W35_2A_0474_4:D1:display`)}`)).text()
    expect(detail).toContain(`"source_id":"${BARNARD}"`)
    const sat = page.locator('[data-testid="sky-explore"] [data-kind="saturated"] rect').first()
    await expect(sat).toBeVisible({ timeout: 240_000 })
    const box = await sat.boundingBox()
    await page.mouse.click((box?.x ?? 0) + (box?.width ?? 0) / 2, (box?.y ?? 0) + (box?.height ?? 0) / 2)
    const panel = page.getByTestId('gaia-panel')
    await expect(panel.getByTestId('gaia-source-id')).toHaveText(BARNARD)
    await expect(panel.getByTestId('gaia-measurement')).toContainText('saturated in this frame')
    await expect(panel.getByTestId('gaia-prediction')).toContainText('-110.47 km/s (catalogued)')
  })

  test('Alignment tab reports residuals before correction, rejections and the convention test; no discovery language', async ({ page }) => {
    await openSpherex(page)
    await page.getByTestId('mode-switch').locator('[data-value="analyze"]').click()
    await page.getByRole('tab', { name: 'Alignment' }).click()
    const tab = page.getByTestId('alignment-tab')
    await expect(page.getByTestId('alignment-frames').locator('tbody tr')).toHaveCount(17, { timeout: 280_000 })
    await expect(page.getByTestId('convention-test')).toContainText('catalogue frame')
    await expect(tab).toContainText('Residuals before any correction')
    await expect(page.getByTestId('residual-plot')).toBeVisible()
    await expect(page.getByTestId('rejection-reasons').locator('[data-reason="neighbour_within_2px"]')).toBeVisible()
    await expect(page.getByTestId('translation-decision')).toContainText('not applied to any product')
    await expect(page.getByTestId('estimator-validation')).toContainText('Injection-recovery')
    await expect(page.getByTestId('alignment-pooled')).toContainText('references')
    await expect(page.getByTestId('alignment-pooled')).toContainText('two-dimensional RMS')
    await expect(page.getByTestId('alignment-reassessment')).toContainText('do not shrink with N')
    await expect(page.getByTestId('uncertainty-budget').locator('[data-kind="shared_per_frame"]')).toHaveCount(2)
    await expect(page.getByTestId('shared-systematics')).toContainText('do not average down with N')
    await expect(page.getByTestId('alignment-cache')).toContainText('cache key')
    await expect(tab).toContainText('partially resolved')
    const text = (await tab.textContent())?.toLowerCase() ?? ''
    for (const w of ['discovered', 'new object', 'transient candidate']) expect(text).not.toContain(w)
    await page.getByRole('tab', { name: 'Gaia DR3' }).click()
    await expect(page.getByTestId('gaia-adql')).toContainText('FROM gaiadr3.gaia_source WHERE')
    await expect(page.getByTestId('gaia-convention')).toContainText('fitted to Gaia DR3 positions propagated with proper motion')
    await expect(page.getByTestId('gaia-error-budget')).toContainText('absorbed by wcs')
    await expect(page.getByTestId('convention-aspects').locator('[data-status="undocumented_bounded"]').first()).toBeVisible()
    await expect(page.getByTestId('convention-aspects').locator('[data-status="documented_and_tested"]')).toHaveCount(1)
    await page.getByRole('tab', { name: 'Unavailable analyses' }).click()
    for (const cap of ['photometry', 'astrometric_fit', 'difference_imaging', 'source_measurement', 'registration']) {
      await expect(page.getByTestId('capabilities').locator(`[data-capability="${cap}"]`)).toContainText('unavailable')
    }
    for (const cap of ['catalog_overlay', 'alignment_diagnostics']) {
      await expect(page.getByTestId('capabilities').locator(`[data-capability="${cap}"]`)).toContainText('available')
    }
  })

  test('a failed overlay request is reported on the frame (no markers, nothing substituted)', async ({ page }) => {
    await page.route((url) => url.pathname === `/api/datasets/${DS}/gaia/overlay`, (route) =>
      route.fulfill({ status: 503, json: { detail: { code: 'provider_unavailable', message: 'gaia_dr3: load_recorded_field unavailable - no recorded Gaia DR3 response', details: {} } } }),
    )
    await openSpherex(page)
    await expect(page.getByTestId('sky-explore-caption')).toContainText('Gaia DR3 overlay unavailable', { timeout: 60_000 })
    await expect(page.locator('[data-testid="sky-explore"] .sky-gaia')).toHaveCount(0)
    await expect(page.getByTestId('obs-date')).toContainText('2025-08-30 22:47:30') // the archive image itself is still shown
  })
})
