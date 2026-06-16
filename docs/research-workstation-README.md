# Research Workstation 使用手册

多模型协同投研工作站：Gemini(哨兵) + Qlib(精算师) + Claude(决策大脑)

## 快速开始

### 一条命令完成 "异动扫描→量化评分→深度研判"

```bash
./research.sh
```

### 自定义标的

```bash
./research.sh --symbols 600519,000001,300750
```

### 降级模式（无 Qlib / 无 Gemini）

```bash
# 跳过哨兵扫描（Gemini 不可用时）
./research.sh --skip-sentinel

# 跳过量化推理（Qlib 未安装时）
./research.sh --skip-qlib

# 纯技术面模式（仅贝叶斯指标）
./research.sh --skip-sentinel --skip-qlib
```

### Claude Code 深度研究

```
/deep-research 600519
```

生成 1000+ 字中文深度报告，包含：市场环境、哨兵信号、量化预测、技术面、A股约束、综合研判。

## 三步流水线

| 步骤 | 模型角色 | 说明 | 失败行为 |
|------|---------|------|---------|
| Step 1 | 哨兵 (Gemini 2.5-flash) | 新闻/异动/热度扫描 + 情绪合成 | 记日志跳过，后续使用纯数据 |
| Step 2 | 精算师 (Qlib) | 量化预测 + IC验证 + Alpha因子 | 记日志跳过，使用技术指标 |
| Step 3 | 聚合器 | 贝叶斯融合 + A股约束检查 | **必须成功** |

## 前置条件

### 必需

- Python 3.11+ 虚拟环境 (`.venv/`)
- `config/research.yaml` 配置文件
- 技术面依赖：`ta` 库（已在 requirements.txt）

### 可选

- **Qlib**: `pip install qlib` — 量化预测引擎（Docker 环境无需安装）
- **Gemini API**: 配置 `GOOGLE_API_KEY` 环境变量 — 哨兵情绪合成

## 配置说明

所有参数在 `config/research.yaml` 中：

```yaml
sentinel:        # Gemini 哨兵配置
actuary:         # Qlib 精算师配置
decision_brain:  # Claude 决策大脑配置
bayesian_fusion: # 贝叶斯融合权重
ashare_constraints: # A股特殊约束
orchestration:   # 编排脚本设置
```

### 融合权重默认值

| 来源 | 权重 | 说明 |
|------|-----|------|
| 哨兵 (Gemini) | 0.25 | 降级时权重归零 |
| 精算师 (Qlib) | 0.35 | Qlib 不可用时归零 |
| 技术面 (贝叶斯) | 0.40 | 始终可用 |

不可用源的权重自动重新归一化到 1.0。

## 输出文件

| 文件 | 路径 | 说明 |
|------|-----|------|
| 哨兵快照 | `data/raw/gemini_sense.json` | Gemini 情绪合成结果 |
| 研究信号 | `scripts/output/reports/research_signal_{date}.json` | 融合信号 |
| 深度报告 | `scripts/output/reports/{symbol}_deep_research_{date}.md` | 中文报告 |
| 运行日志 | `scripts/output/logs/research_{date}.log` | 流水线日志 |

## 自动化调度

Celery 任务自动执行：

- **哨兵扫描**: 交易时段每 30 分钟 (09:00-15:00 CST, Mon-Fri)
- **信号聚合**: 收盘后 15:35 CST (Mon-Fri)

## 降级链说明

```
Full (3源) → No-Qlib (2源) → No-Gemini (2源) → Technical-only (1源) → Template-report
```

每一级降级都保证系统正常运行，只是信号置信度随可用源减少而降低。

## 独立脚本

```bash
# Qlib 推理
python scripts/qlib_inference.py --symbols 600519 --output json

# IC 验证
python scripts/check_alpha.py --symbols 600519 --threshold 0.03

# 数据聚合
python scripts/data_aggregator.py --symbols 600519 --date 2026-03-01
```
