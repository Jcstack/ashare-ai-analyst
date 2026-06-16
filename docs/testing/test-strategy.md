# Test Strategy: A股智能投顾 v4.0 UX 重构

> 日期: 2026-02-14

---

## 1. 测试范围

### 1.1 In Scope

| 模块 | 测试类型 | 覆盖目标 |
|------|---------|---------|
| Onboarding (F1) | E2E + 手工 | 首次/非首次用户流程 |
| AI 概览 Tab (F2) | E2E + 手工 | 默认 Tab 切换、内容正确性 |
| AI 综合诊断卡片 (F3) | E2E + 单元 | 数据展示、信号颜色、展开收起 |
| 风险提示 (F4) | E2E + 手工 | 免责弹窗、卡片提示 |
| 术语 tooltip (F5) | E2E + 单元 | 悬停显示、内容正确 |
| Tab 收敛 (F6) | E2E | 3 Tab 结构、内容完整性 |
| 热门推荐 (F7) | E2E | 空状态显示、有数据后隐藏 |
| 文案优化 (F8) | 手工 | 文案正确性 |

### 1.2 Out of Scope

- 后端 API 逻辑（已有 875+ 单元测试覆盖）
- 策略回测核心算法
- Docker 部署验证

---

## 2. 测试环境

| 环境 | 配置 |
|------|------|
| 浏览器 | Chromium (Playwright headless) |
| 前端 | Vite dev server (`http://localhost:5173`) |
| 后端 | API mock（Playwright route interceptor） |
| 数据 | 确定性 mock 数据（`fixtures/mock-data.ts`） |

---

## 3. 测试策略

### 3.1 E2E 测试（Playwright）

**目的**: 验证用户可见的关键路径

**执行方式**: `cd frontend && npx playwright test`

**关键路径覆盖**:

| # | 路径 | 文件 |
|---|------|------|
| CP-1 | 新手首次打开 → Onboarding → 关闭 → 看到推荐 | `onboarding.spec.ts` |
| CP-2 | 搜索股票 → 进入详情 → 看到 AI 概览 | `ai-overview.spec.ts` |
| CP-3 | AI 诊断卡片加载 → 展开详情 → 风险提示可见 | `ai-overview.spec.ts` |
| CP-4 | 免责声明首次弹出 → 确认 → 不再弹出 | `disclaimer.spec.ts` |
| CP-5 | Tab 切换（AI概览 → 技术面 → 资讯） | `ai-overview.spec.ts` |

### 3.2 手工测试

**目的**: 验证视觉/交互/文案细节

**执行方式**: 按 test-cases.md 中的用例逐项手工执行

### 3.3 回归测试

**目的**: 确保重构不破坏已有功能

**执行方式**:
1. 后端: `pytest tests/ -v`（875+ 测试全部通过）
2. 前端类型: `npx tsc --noEmit`
3. 前端构建: `npm run build`
4. E2E: `npx playwright test`

---

## 4. 验收标准

| 标准 | 要求 |
|------|------|
| E2E 关键路径 | 5 条 CP 全部 PASS |
| 后端回归 | 875+ 测试 0 新增 failure |
| 前端构建 | `tsc --noEmit` + `npm run build` 均成功 |
| 手工测试 | P0 用例 100% PASS，P1 用例 90% PASS |
| 性能 | 页面加载 < 3s，Tab 切换 < 500ms |

---

## 5. 风险与缓解

| 风险 | 缓解 |
|------|------|
| E2E 依赖前端 dev server | Playwright 自动启动 (`webServer` 配置) |
| Mock 数据与真实 API 不一致 | Mock 数据结构从现有 E2E 继承 |
| 重构引入 TypeScript 错误 | 每次改动后跑 `tsc --noEmit` |
