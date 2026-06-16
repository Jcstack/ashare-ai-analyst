import { test, expect } from '@playwright/test';
import { mockAllApis } from './fixtures/api-mocks';

test.describe('Predictions', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
  });

  test('prediction page loads', async ({ page }) => {
    await page.goto('/predictions');
    await expect(page.getByText('AI 预测分析')).toBeVisible();
    // Empty state should show when no stock is selected
    await expect(page.getByText(/选择股票开始/)).toBeVisible();
  });

  test('can select stock for prediction', async ({ page }) => {
    await page.goto('/predictions');
    // The watchlist select dropdown should be available ("从自选选择")
    const selectTrigger = page.getByRole('combobox')
      .or(page.locator('[role="combobox"]'))
      .or(page.getByText('选择一只股票...'));
    await expect(selectTrigger.first()).toBeVisible({ timeout: 5000 });
    await selectTrigger.first().click();
    // Watchlist items should appear in the dropdown
    const option = page.getByText('平安银行 (000001)')
      .or(page.getByRole('option', { name: /平安银行/ }));
    await expect(option.first()).toBeVisible({ timeout: 5000 });
    await option.first().click();
    // After selecting, the "开始分析" button should be enabled
    const analyzeBtn = page.getByRole('button', { name: /开始分析/ });
    await expect(analyzeBtn).toBeEnabled();
  });

  test('prediction result displays after submit', async ({ page }) => {
    await page.goto('/predictions');
    // Select a stock from the dropdown
    const selectTrigger = page.getByRole('combobox')
      .or(page.locator('[role="combobox"]'))
      .or(page.getByText('选择一只股票...'));
    await selectTrigger.first().click();
    const option = page.getByText('平安银行 (000001)')
      .or(page.getByRole('option', { name: /平安银行/ }));
    await option.first().click();

    // Click the analyze button
    const analyzeBtn = page.getByRole('button', { name: /开始分析/ });
    await analyzeBtn.click();

    // Wait for mock API response to render (loading → result)
    // Mock prediction includes trend: "bullish" and reasoning: ["趋势向好", "均线金叉"]
    const result = page.getByText(/趋势向好/)
      .or(page.getByText(/bullish|看多|偏多/))
      .or(page.getByText(/均线金叉/))
      .or(page.getByText(/MACD转正/));
    await expect(result.first()).toBeVisible({ timeout: 10000 });
  });

  test('loading state shows during prediction', async ({ page }) => {
    // Use a delayed route to observe loading state
    await page.route('**/api/v1/predict/*/enhanced', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await route.fulfill({
        json: {
          symbol: '000001',
          trend: 'bullish',
          signal: 'buy',
          confidence: 0.75,
          risk_level: 'medium',
          reasoning: ['趋势向好'],
          key_factors: ['MACD转正'],
          risk_warnings: ['大盘调整风险'],
          target_price_range: { low: 10.5, high: 11.8 },
        },
      });
    });

    await page.goto('/predictions');
    // Select a stock
    const selectTrigger = page.getByRole('combobox')
      .or(page.locator('[role="combobox"]'))
      .or(page.getByText('选择一只股票...'));
    await selectTrigger.first().click();
    const option = page.getByText('平安银行 (000001)')
      .or(page.getByRole('option', { name: /平安银行/ }));
    await option.first().click();

    // Click analyze
    const analyzeBtn = page.getByRole('button', { name: /开始分析/ });
    await analyzeBtn.click();

    // Loading state should show (animated steps or spinner)
    const loadingIndicator = page.getByText(/分析中|获取市场数据|计算技术指标|AI.*推理|生成分析报告/)
      .or(page.locator('.animate-spin'));
    await expect(loadingIndicator.first()).toBeVisible({ timeout: 3000 });
  });
});
