import { test, expect } from '@playwright/test';
import { mockAllApis } from './fixtures/api-mocks';

test.describe('Onboarding (F1)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    // Clear onboarding flag to simulate first-time user
    await page.addInitScript(() => {
      localStorage.removeItem('onboarding-completed');
      localStorage.removeItem('disclaimer-accepted');
    });
  });

  test('TC-F1-01: first-time user sees onboarding dialog', async ({ page }) => {
    await page.goto('/');
    // Should show onboarding dialog
    const dialog = page.getByRole('dialog').or(page.locator('[data-testid="onboarding-dialog"]'));
    await expect(dialog.first()).toBeVisible({ timeout: 5000 });
  });

  test('TC-F1-02: clicking start closes onboarding', async ({ page }) => {
    await page.goto('/');
    // Wait for onboarding dialog
    const startButton = page.getByRole('button', { name: /开始使用/i });
    await expect(startButton).toBeVisible({ timeout: 5000 });
    await startButton.click();
    // Dialog should close
    await expect(startButton).not.toBeVisible({ timeout: 3000 });
    // localStorage should be set
    const flag = await page.evaluate(() => localStorage.getItem('onboarding-completed'));
    expect(flag).toBe('true');
  });

  test('TC-F1-03: returning user does not see onboarding', async ({ page }) => {
    // Set flag before navigation
    await page.addInitScript(() => {
      localStorage.setItem('onboarding-completed', 'true');
      localStorage.setItem('disclaimer-accepted', 'true');
    });
    await page.goto('/');
    // Should NOT show onboarding
    const startButton = page.getByRole('button', { name: /开始使用/i });
    await expect(startButton).not.toBeVisible({ timeout: 3000 });
  });
});
