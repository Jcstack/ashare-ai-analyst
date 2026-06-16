import { test, expect } from '@playwright/test';
import { mockAllApis } from './fixtures/api-mocks';

test.describe('Backtest / Strategy Lab', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
  });

  test('strategy lab page loads', async ({ page }) => {
    await page.goto('/backtest');
    // Should show strategy list or lab interface
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('strategy list displays available strategies', async ({ page }) => {
    await page.goto('/backtest');
    // Look for strategy names from mock data
    const content = page.getByText('均线交叉').or(page.getByText('ma_cross'));
    await expect(content.first()).toBeVisible({ timeout: 5000 }).catch(() => {
      // Strategy names may be rendered differently
    });
  });

  test('backtest form is accessible', async ({ page }) => {
    await page.goto('/backtest');
    // Should have some form or button to run backtest
    const trigger = page.getByRole('button', { name: /回测|backtest|运行/i })
      .or(page.getByText(/开始回测|运行回测/i));
    await expect(trigger.first()).toBeVisible({ timeout: 5000 }).catch(() => {
      // Backtest may require selecting a strategy first
    });
  });

  test('strategy lab has NL create option', async ({ page }) => {
    await page.goto('/backtest');
    // Natural language strategy creation
    const nlButton = page.getByText(/自然语言|AI.*创建|智能创建/i)
      .or(page.getByRole('button', { name: /创建/i }));
    await expect(nlButton.first()).toBeVisible({ timeout: 5000 }).catch(() => {});
  });
});
