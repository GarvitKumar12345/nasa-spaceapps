import { expect, test, type Page } from '@playwright/test'

const sky = (page: Page, id = 'sky-explore') => page.getByTestId(id)

async function openObservatory(page: Page) {
  await page.goto('/#/observatory')
  await expect(sky(page)).toBeVisible({ timeout: 60_000 })
}

async function selectBySearch(page: Page, query: string) {
  await page.getByTestId('search-input').fill(query)
  await page.getByTestId('search-input').press('Enter')
  await expect(page.getByTestId('source-summary')).toContainText(query)
}

test.describe('[browser] Observatory', () => {
  test('loads the synthetic investigation with explicit origin labels and gaps', async ({ page }) => {
    await openObservatory(page)
    await expect(page.getByText('Simulated data').first()).toBeVisible()
    await expect(page.getByText('Simulated pixels').first()).toBeVisible()
    await expect(page.getByTestId('api-online')).toBeVisible()
    const timeline = page.getByTestId('timeline')
    await expect(timeline).toContainText('missing')
    await expect(timeline).toContainText('failed')
    await expect(page.getByTestId('epoch-readout')).toContainText('Epoch 1 of 9')
  })

  test('selects a source by search and by clicking it on the canvas', async ({ page }) => {
    await openObservatory(page)
    await selectBySearch(page, 'S003')
    const inspector = page.getByTestId('inspector')
    await expect(inspector).toContainText('Position σ')
    await expect(inspector).toContainText('mas')
    const marker = page.getByTestId('selected-marker').locator('circle').first()
    const box = await marker.boundingBox()
    expect(box).not.toBeNull()
    await sky(page).focus()
    await page.keyboard.press('Escape')
    await expect(page.getByText('No source selected')).toBeVisible()
    await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2)
    await expect(sky(page)).toHaveAttribute('data-selected', 'S003')
  })

  test('steps, plays and blinks only through real frames', async ({ page }) => {
    await openObservatory(page)
    const readout = page.getByTestId('epoch-readout')
    await page.getByTestId('step-forward').click()
    await expect(readout).toContainText('Epoch 2 of 9')
    // Stepping through every available epoch never lands on a missing or failed visit.
    const seen = new Set<string>()
    for (let i = 0; i < 9; i++) {
      seen.add((await readout.textContent()) ?? '')
      await page.getByTestId('step-forward').click()
    }
    expect([...seen].every((t) => /Epoch \d of 9/.test(t))).toBe(true)
    expect(seen.size).toBe(9)
    await page.getByTestId('blink').click()
    await expect(readout).toContainText(/^\s*B/, { timeout: 5_000 })
    await page.getByTestId('blink').click()
    await page.getByTestId('play').click()
    await expect(page.getByTestId('play')).toHaveAttribute('aria-pressed', 'true')
    await page.getByTestId('play').click()
    await expect(page.getByTestId('play')).toHaveAttribute('aria-pressed', 'false')
  })

  test('Explore <-> Analyze preserves dataset, band, epoch, source and view', async ({ page }) => {
    await openObservatory(page)
    await page.getByTestId('band-select').locator('[data-value="G2"]').click()
    await page.getByTestId('step-forward').click()
    await page.getByTestId('step-forward').click()
    await selectBySearch(page, 'S003')
    await page.getByTestId('zoom-in').click()
    await page.getByTestId('zoom-in').click()
    const before = {
      readout: await page.getByTestId('epoch-readout').textContent(),
      zoom: await sky(page).getAttribute('data-zoom'),
      cx: await sky(page).getAttribute('data-cx'),
      cy: await sky(page).getAttribute('data-cy'),
    }
    await page.getByTestId('mode-switch').locator('[data-value="analyze"]').click()
    await expect(page.getByTestId('sky-a')).toBeVisible()
    await expect(page.getByTestId('band-select').locator('[data-value="G2"]')).toHaveAttribute('aria-checked', 'true')
    await expect(page.getByTestId('sky-a')).toHaveAttribute('data-selected', 'S003')
    expect(await page.getByTestId('epoch-readout').textContent()).toBe(before.readout)
    expect(await page.getByTestId('sky-a').getAttribute('data-cx')).toBe(before.cx)
    expect(await page.getByTestId('sky-a').getAttribute('data-cy')).toBe(before.cy)
    await page.getByTestId('mode-switch').locator('[data-value="explore"]').click()
    await expect(sky(page)).toHaveAttribute('data-selected', 'S003')
    expect(await sky(page).getAttribute('data-zoom')).toBe(before.zoom)
    expect(await page.getByTestId('epoch-readout').textContent()).toBe(before.readout)
  })

  test('Analyze: fit, stale detection after changing inputs, plots and catalog', async ({ page }) => {
    await openObservatory(page)
    await selectBySearch(page, 'S003')
    await page.getByTestId('mode-switch').locator('[data-value="analyze"]').click()
    await expect(page.getByTestId('measurement-table')).toBeVisible()
    await page.getByRole('tab', { name: 'Motion fit' }).click()
    await page.getByTestId('run-fit').click()
    const result = page.getByTestId('fit-result')
    await expect(result).toBeVisible()
    await expect(result).toContainText('constrained')
    await expect(page.getByTestId('fit-parameters').locator('[data-param="parallax"]')).toContainText('estimated')
    await expect(page.getByTestId('fit-derived').locator('[data-derived="distance"]')).toContainText('pc')
    await page.getByRole('tab', { name: 'Measurements' }).click()
    await page.getByTestId('measurement-table').locator('tbody input[type="checkbox"]').first().uncheck()
    await expect(page.getByText('Fit is stale: inclusion changed')).toBeVisible()
    await page.getByRole('tab', { name: 'Motion fit' }).click()
    await expect(page.getByText('Stale fit.')).toBeVisible()
    await page.getByTestId('run-fit').click()
    await expect(page.getByText('Stale fit.')).toHaveCount(0)
    await page.getByRole('tab', { name: 'Plots & residuals' }).click()
    await expect(page.getByTestId('sky-track-plot')).toBeVisible()
    await page.getByRole('tab', { name: 'Catalog' }).click()
    await expect(page.getByTestId('association-table')).toContainText('matched')
  })

  test('difference preview shows its compatibility checks and display-only label', async ({ page }) => {
    await openObservatory(page)
    await page.getByTestId('mode-switch').locator('[data-value="analyze"]').click()
    await page.getByTestId('compare-view').locator('[data-value="difference"]').click()
    await expect(page.getByTestId('difference-checks')).toContainText('same band')
    await expect(page.getByTestId('sky-difference')).toContainText('Display-only')
  })

  test('shows an error state when the API is unreachable', async ({ page }) => {
    // Abort only backend calls (pathname /api/...), not Vite's /src/api/*.ts modules.
    await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.abort('connectionrefused'))
    await page.goto('/#/observatory')
    await expect(page.getByText('Cannot reach the SkyShift API')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId('api-offline')).toBeVisible()
  })

  test('name search is honestly unresolved; coordinates outside the field are flagged', async ({ page }) => {
    await openObservatory(page)
    await page.getByTestId('search-input').fill("Barnard's Star")
    await page.getByTestId('search-input').press('Enter')
    await expect(page.getByTestId('search-message')).toContainText('not available in this build')
    await page.getByTestId('search-input').fill('10 10')
    await page.getByTestId('search-input').press('Enter')
    await expect(page.getByTestId('search-message')).toContainText('Outside the loaded dataset field')
  })
})

test.describe('[browser] responsive layout', () => {
  test.use({ viewport: { width: 390, height: 844 } })
  for (const section of ['observatory', 'motion', 'evidence', 'methods']) {
    test(`${section}: usable at 390 px without horizontal page scroll`, async ({ page }) => {
      await page.goto(`/#/${section}`)
      await page.waitForTimeout(section === 'observatory' ? 4000 : 1500)
      if (section === 'observatory') await expect(sky(page)).toBeVisible({ timeout: 60_000 })
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow).toBeLessThanOrEqual(0)
    })
  }
})
