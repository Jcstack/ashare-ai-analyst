# E2E 测试文档

> 自动化端到端测试使用 Playwright，覆盖 v4.0 UX 重构的关键用户路径。

## 运行方式

```bash
# 前置：确保后端和前端依赖已安装
cd frontend

# 安装 Playwright 浏览器（首次需要）
npx playwright install chromium

# 运行所有 E2E 测试（会自动启动 Vite dev server）
npx playwright test

# 仅运行新增的 UX 重构测试
npx playwright test onboarding ai-overview disclaimer

# 以有头浏览器模式运行（可视化调试）
npx playwright test --headed

# 以 UI 模式运行（交互式调试）
npx playwright test --ui

# 运行单个测试文件
npx playwright test onboarding.spec.ts

# 查看测试报告
npx playwright show-report
```

## 测试文件结构

```
frontend/tests/e2e/
├── fixtures/
│   ├── mock-data.ts      # 确定性 mock 数据（所有 API 响应）
│   └── api-mocks.ts      # Playwright route 拦截器（mock 全部 18 个 API 域）
├── onboarding.spec.ts    # [新] F1 新手引导测试 (3 cases)
├── ai-overview.spec.ts   # [新] F2/F3/F6 AI 概览 Tab 测试 (5 cases)
├── disclaimer.spec.ts    # [新] F4 风险提示测试 (4 cases)
├── dashboard.spec.ts     # [已有] Dashboard 基础测试
├── stock-detail.spec.ts  # [已有] 个股详情测试
├── portfolio.spec.ts     # [已有] 持仓管理测试
├── backtest.spec.ts      # [已有] 策略回测测试
├── navigation.spec.ts    # [已有] 导航测试
├── watchlist-flows.spec.ts # [已有] 自选股流程测试
├── market.spec.ts        # [已有] 市场页测试
├── settings.spec.ts      # [已有] 设置页测试
└── predictions.spec.ts   # [已有] 预测页测试
```

## 新增测试覆盖

| 文件 | 对应 PRD | 测试用例数 | 关键路径 |
|------|---------|-----------|---------|
| `onboarding.spec.ts` | F1 | 3 | 首次用户引导流程 |
| `ai-overview.spec.ts` | F2, F3, F6 | 5 | 个股 AI 分析体验 |
| `disclaimer.spec.ts` | F4 | 4 | 风险提示合规 |

## Mock 策略

所有 E2E 测试使用 Playwright 的 `page.route()` 拦截 API 请求，返回确定性 mock 数据：

- 不依赖后端运行
- 数据固定，测试可重复
- `api-mocks.ts` 统一管理所有 mock

## 配置

Playwright 配置文件: `frontend/playwright.config.ts`

```typescript
{
  testDir: './tests/e2e',
  baseURL: 'http://localhost:5173',
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
  }
}
```

## 注意事项

1. E2E 测试会自动启动 Vite dev server（如果没有运行中的）
2. 首次运行需要安装 Playwright 浏览器：`npx playwright install chromium`
3. 新增测试依赖 localStorage flags (`onboarding-completed`, `disclaimer-accepted`)
4. 测试使用 `page.addInitScript()` 在页面加载前设置/清除这些 flags
