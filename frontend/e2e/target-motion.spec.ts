import { expect, test, type Page } from '@playwright/test'

const VM2 = 'spherex-dr1-vanmaanen2'

async function open(page: Page, ds: string) {
  await page.goto('/#/observatory')
  await expect(page.getByTestId('sky-explore')).toBeVisible({ timeout: 90_000 })
  await page.getByTestId('dataset-select').selectOption(ds)
  await expect(page.getByTestId('observed-banner')).toBeVisible({ timeout: 90_000 })
  await page.getByTestId('mode-switch').locator('[data-value="analyze"]').click()
}

test.describe('[browser] Target motion study (van Maanen 2, recorded)', () => {
  test.setTimeout(240_000)
  test.beforeEach(async ({ page }) => {
    const list = (await (await page.request.get('/api/datasets')).json()) as { id: string; availability: string }[]
    test.skip(!list.some((d) => d.id === VM2 && d.availability === 'ready'), 'van Maanen 2 cutouts not cached')
  })

  test('shows both seasons, measured vs predicted positions with uncertainties, statuses and the observation/model distinction', async ({ page }) => {
    await open(page, VM2)
    await page.getByRole('tab', { name: 'Target motion' }).click()
    const tab = page.getByTestId('target-motion-tab')
    await expect(tab).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('motion-verdict')).toContainText('Motion')
    await expect(page.getByTestId('motion-statement')).toContainText('Gaia-predicted displacement')
    await expect(page.getByTestId('motion-legend')).toContainText('SPHEREx measurement')
    await expect(page.getByTestId('motion-legend')).toContainText('Gaia DR3 prediction')
    await expect(page.getByTestId('motion-combined').locator('tbody tr')).not.toHaveCount(0)
    await expect(page.getByTestId('motion-pairs').locator('tr[data-role="excluded"]').first()).toContainText('not measured')
    await expect(page.getByTestId('motion-plot').locator('[data-approach="tied"]').first()).toBeVisible()
    await expect(page.getByTestId('motion-two-seasons').locator('canvas')).toHaveCount(2, { timeout: 60_000 })
    await expect(page.getByTestId('motion-frames').locator('tbody tr')).toHaveCount(13)
    await expect(page.getByTestId('study-integrity')).toContainText('verified')
    await expect(tab.locator('.motion-metrics')).toContainText('5.8σ')
    const d2 = page.getByTestId('motion-pairs').locator('tbody tr').filter({ hasText: 'D2 tied (primary)' })
    await expect(d2).toContainText('4.98σ')
    await expect(d2).toContainText('0.24, 0.27 · 0.06, 0.11')
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path:'../validation/results/study-desktop.png', fullPage:true })
    const downloadPromise = page.waitForEvent('download')
    await page.getByTestId('motion-export').click()
    expect((await downloadPromise).suggestedFilename()).toContain('evidence.zip')
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const text = (await tab.textContent())?.toLowerCase() ?? ''
    for (const w of ['discovered', 'new object', 'transient candidate']) expect(text).not.toContain(w)
  })

  test('fields without a recorded study offer no target-motion tab', async ({ page }) => {
    await open(page, 'spherex-dr1-barnard')
    await expect(page.getByRole('tab', { name: 'Alignment' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Target motion' })).toHaveCount(0)
  })
})
