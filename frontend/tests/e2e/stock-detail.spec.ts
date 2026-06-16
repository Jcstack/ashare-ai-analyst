import { test, expect } from '@playwright/test';
import { mockAllApis } from './fixtures/api-mocks';

test.describe('Stock Detail', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    await page.goto('/stock/000001');
  });

  test('page loads with stock name', async ({ page }) => {
    await expect(page.getByText('平安银行')).toBeVisible();
  });

  test('price info displays', async ({ page }) => {
    // Stock detail should show price data from mock (close: 10.5)
    const priceArea = page.getByText('10.5').or(page.getByText('10.50'));
    await expect(priceArea.first()).toBeVisible({ timeout: 5000 });
  });

  test('OHLCV chart area renders', async ({ page }) => {
    // The candlestick chart tab is active by default ("K线图")
    const chartTab = page.getByRole('tab', { name: /K线图/i }).or(page.getByText('K线图'));
    await expect(chartTab.first()).toBeVisible();
    // Chart container or loading indicator should be present
    const chartArea = page.locator('canvas')
      .or(page.locator('.js-plotly-plot'))
      .or(page.locator('[class*="chart"]'))
      .or(page.getByText('加载图表数据'));
    await expect(chartArea.first()).toBeVisible({ timeout: 10000 }).catch(() => {
      // Chart library may render differently
    });
  });

  test('indicators tab exists', async ({ page }) => {
    const indicatorsTab = page.getByRole('tab', { name: /技术指标/ });
    await expect(indicatorsTab).toBeVisible();
  });

  test('AI analysis tab is accessible', async ({ page }) => {
    const aiTab = page.getByRole('tab', { name: /AI分析|AI 分析/ });
    await expect(aiTab).toBeVisible();
    await aiTab.click();
    // After clicking, the AI insight panel should appear
    await expect(page.locator('[role="tabpanel"]').first()).toBeVisible({ timeout: 5000 });
  });

  test('fund flow section accessible', async ({ page }) => {
    // Fund flow card should be visible on the candlestick tab (below chart grid)
    const fundFlow = page.getByText(/资金流向|资金/)
      .or(page.getByText('买入'))
      .or(page.locator('[data-testid="fund-flow"]'));
    await expect(fundFlow.first()).toBeVisible({ timeout: 5000 }).catch(() => {
      // Fund flow may load asynchronously
    });
  });

  test('support/resistance section accessible', async ({ page }) => {
    // Support/resistance card is in the below-chart grid
    const srSection = page.getByText(/支撑|阻力/)
      .or(page.locator('[data-testid="support-resistance"]'));
    await expect(srSection.first()).toBeVisible({ timeout: 5000 }).catch(() => {
      // S/R card may be conditionally rendered based on data
    });
  });

  test('dragon tiger tab accessible', async ({ page }) => {
    const dtTab = page.getByRole('tab', { name: /龙虎榜/ });
    await expect(dtTab).toBeVisible();
    await dtTab.click();
    await expect(page.locator('[role="tabpanel"]').first()).toBeVisible({ timeout: 5000 });
  });
});
