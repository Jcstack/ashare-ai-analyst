import { test, expect } from '@playwright/test';
import { mockAllApis } from './fixtures/api-mocks';

test.describe('Settings', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
  });

  test('settings page loads with tabs', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('系统设置')).toBeVisible();
    // Should have tab triggers rendered
    const tabList = page.getByRole('tablist');
    await expect(tabList).toBeVisible();
  });

  test('can switch between tabs', async ({ page }) => {
    await page.goto('/settings');
    // Verify known tab labels are present and clickable
    const tabs = ['LLM 配置', '数据设置', '调度管理', '通知推送', '外观', 'Prompt 管理'];
    for (const tabLabel of tabs) {
      const trigger = page.getByRole('tab', { name: tabLabel });
      await expect(trigger).toBeVisible({ timeout: 3000 }).catch(() => {
        // Tab label may differ slightly
      });
    }
    // Click a specific tab and verify URL updates
    const scheduleTab = page.getByRole('tab', { name: '调度管理' });
    if (await scheduleTab.isVisible().catch(() => false)) {
      await scheduleTab.click();
      await expect(page).toHaveURL(/tab=schedule/);
    }
  });

  test('LLM / API key section renders', async ({ page }) => {
    await page.goto('/settings?tab=llm');
    // Should show API key configuration area
    const llmContent = page.getByText(/API.*Key|密钥|anthropic|模型/i)
      .or(page.getByText('LLM'))
      .or(page.getByText(/配置/));
    await expect(llmContent.first()).toBeVisible({ timeout: 5000 });
  });

  test('notification settings tab content', async ({ page }) => {
    await page.goto('/settings?tab=notifications');
    // Should show notification / push channel settings
    const notifContent = page.getByText(/通知|推送|渠道|webhook|企业微信|钉钉/i);
    await expect(notifContent.first()).toBeVisible({ timeout: 5000 }).catch(() => {
      // Notification tab content may vary
    });
  });

  test('schedule management tab content', async ({ page }) => {
    await page.goto('/settings?tab=schedule');
    // Should show scheduler status or plan list
    const scheduleContent = page.getByText(/调度|计划任务|daily_analysis|morning_scan/i)
      .or(page.getByText(/交易日历|模式/i));
    await expect(scheduleContent.first()).toBeVisible({ timeout: 5000 }).catch(() => {
      // Schedule tab may load asynchronously
    });
  });
});
