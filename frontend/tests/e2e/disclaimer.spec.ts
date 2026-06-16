import { test, expect } from '@playwright/test';
import { mockAllApis } from './fixtures/api-mocks';

test.describe('Risk Disclaimer (F4)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    // Clear disclaimer flag
    await page.addInitScript(() => {
      localStorage.removeItem('disclaimer-accepted');
      localStorage.setItem('onboarding-completed', 'true');
    });
  });

  test('TC-F4-01: first-time user sees disclaimer dialog', async ({ page }) => {
    await page.goto('/');
    // Should show disclaimer dialog
    const disclaimerText = page.getByText(/不构成.*投资建议|仅供.*参考|风险自担/);
    await expect(disclaimerText.first()).toBeVisible({ timeout: 5000 });
  });

  test('TC-F4-03: clicking accept closes disclaimer', async ({ page }) => {
    await page.goto('/');
    // Find and click the accept button
    const acceptButton = page.getByRole('button', { name: /我已了解|我知道了|确认|同意/i });
    await expect(acceptButton).toBeVisible({ timeout: 5000 });
    await acceptButton.click();
    // Should close
    await expect(acceptButton).not.toBeVisible({ timeout: 3000 });
    // localStorage flag should be set
    const flag = await page.evaluate(() => localStorage.getItem('disclaimer-accepted'));
    expect(flag).toBe('true');
  });

  test('TC-F4-05: returning user does not see disclaimer', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('disclaimer-accepted', 'true');
      localStorage.setItem('onboarding-completed', 'true');
    });
    await page.goto('/');
    // Should NOT show disclaimer
    const acceptButton = page.getByRole('button', { name: /我已了解|我知道了/i });
    await expect(acceptButton).not.toBeVisible({ timeout: 3000 });
  });

  test('TC-F4-04: AI diagnosis card shows risk disclaimer', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('disclaimer-accepted', 'true');
      localStorage.setItem('onboarding-completed', 'true');
    });
    await page.goto('/stock/000001');
    // Look for risk disclaimer text within the page
    const riskText = page.getByText(/仅供参考|不构成投资建议/);
    await expect(riskText.first()).toBeVisible({ timeout: 10000 });
  });
});
