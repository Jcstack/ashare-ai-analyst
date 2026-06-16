import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import type { ReactNode } from "react"

interface GlossaryEntry {
  title: string
  definition: string
  benchmark?: string
}

const GLOSSARY_MAP: Record<string, GlossaryEntry> = {
  // ─── 回测绩效指标 ───
  sharpe_ratio: {
    title: "夏普比率 (Sharpe Ratio)",
    definition: "衡量每承受一单位风险所获得的超额收益。数值越高，策略的风险调整后收益越好。",
    benchmark: ">2.0 优秀, >1.0 良好, >0.5 一般, <0.5 较差",
  },
  max_drawdown: {
    title: "最大回撤 (Max Drawdown)",
    definition: "从最高点到最低点的最大跌幅，衡量策略可能面临的最大亏损。回撤越小，策略越稳健。",
    benchmark: "<10% 优秀, <20% 良好, <30% 一般, >30% 风险较高",
  },
  win_rate: {
    title: "胜率 (Win Rate)",
    definition: "盈利交易占总交易次数的比例。胜率高不一定盈利多，还要看盈亏比。",
    benchmark: ">60% 优秀, >50% 良好, <50% 需关注盈亏比",
  },
  total_return: {
    title: "总收益率",
    definition: "回测期间的累计收益率，即（最终资金 - 初始资金）/ 初始资金。",
  },
  annual_return: {
    title: "年化收益率",
    definition: "将总收益率折算为每年的收益率，便于不同时长的策略互相比较。",
    benchmark: ">15% 优秀, >8% 良好, <0% 亏损",
  },
  profit_factor: {
    title: "盈亏比 (Profit Factor)",
    definition: "总盈利金额 / 总亏损金额。大于1表示总体盈利，数值越大越好。",
    benchmark: ">2.0 优秀, >1.5 良好, >1.0 盈利, <1.0 亏损",
  },
  avg_holding_days: {
    title: "平均持仓天数",
    definition: "所有交易的平均持有时间，反映策略的交易频率。持仓天数短代表短线风格，长则是中长线。",
  },
  total_trades: {
    title: "交易次数",
    definition: "回测期间完成的完整买入-卖出交易对的数量。交易次数过少（<10）时统计意义有限。",
  },
  // ─── 趋势类指标 ───
  MA: {
    title: "均线 (Moving Average)",
    definition: "过去N日收盘价的算术平均值，用于平滑价格波动、识别趋势方向。股价在均线上方为多头排列，下方为空头排列。短期均线上穿长期均线形成金叉（买入信号），下穿则为死叉（卖出信号）。",
    benchmark: "MA5/10 短线, MA20/60 中线, MA120/250 长线",
  },
  EMA: {
    title: "指数移动均线 (EMA)",
    definition: "对近期价格赋予更高权重的均线，比MA对价格变化更敏感。EMA比MA更快反映趋势转折，但也更容易产生假信号。常用于MACD计算和短线交易。",
    benchmark: "EMA12/26 常用于MACD, EMA20 常用于趋势跟踪",
  },
  MACD: {
    title: "MACD (指数平滑异同移动平均线)",
    definition: "由DIF线（快线EMA12-慢线EMA26）、DEA线（DIF的9日EMA）和柱状图（DIF-DEA）组成。是最常用的趋势跟踪和动量指标。DIF上穿DEA为金叉（买入），下穿为死叉（卖出）；柱状图由负转正代表多头力量增强，反之空头增强。零轴以上为多头市场，以下为空头市场。",
    benchmark: "金叉+放量=强买入, 顶背离=见顶风险, 底背离=见底信号",
  },
  // ─── 超买超卖指标 ───
  RSI: {
    title: "RSI (相对强弱指数)",
    definition: "衡量一段时间内上涨幅度与下跌幅度的比率，范围0-100。RSI反映市场超买/超卖状态。当RSI>70时市场可能过热（超买），有回调风险；RSI<30时市场可能过冷（超卖），有反弹机会。RSI与价格走势背离是重要的反转信号。",
    benchmark: ">80 强超买, >70 超买区, 30-70 正常区, <30 超卖区, <20 强超卖",
  },
  rsi: {
    title: "RSI (相对强弱指数)",
    definition: "衡量一段时间内上涨幅度与下跌幅度的比率，范围0-100。RSI反映市场超买/超卖状态。当RSI>70时市场可能过热（超买），有回调风险；RSI<30时市场可能过冷（超卖），有反弹机会。RSI与价格走势背离是重要的反转信号。",
    benchmark: ">80 强超买, >70 超买区, 30-70 正常区, <30 超卖区, <20 强超卖",
  },
  KDJ: {
    title: "KDJ (随机指标)",
    definition: "由K线、D线、J线组成的超买超卖指标。K为快速线，D为慢速线，J为方向灵敏度指标。J值最敏感，超过100为超买，低于0为超卖。K线上穿D线为金叉（买入），下穿为死叉（卖出）。在低位（<20）金叉价值更高，高位（>80）死叉价值更高。",
    benchmark: "J>100 超买, K/D>80 高位, K/D<20 低位, J<0 超卖",
  },
  // ─── 波动率指标 ───
  BOLL: {
    title: "布林带 (Bollinger Bands)",
    definition: "由中轨（20日均线）、上轨（中轨+2倍标准差）和下轨（中轨-2倍标准差）组成。约95%的价格在上下轨之间波动。布林带收窄（缩口）预示即将出现大幅波动，扩张（开口）说明行情正在展开。股价触及上轨可能超买回调，触及下轨可能超卖反弹，但强势趋势中会沿上/下轨持续运行。",
    benchmark: "触上轨+放量=强势, 触下轨+缩量=超卖, 缩口=变盘前兆",
  },
  bollinger_bands: {
    title: "布林带 (Bollinger Bands)",
    definition: "由中轨（20日均线）、上轨（中轨+2倍标准差）和下轨（中轨-2倍标准差）组成。约95%的价格在上下轨之间波动。布林带收窄预示即将出现大幅波动，扩张说明行情正在展开。",
    benchmark: "触上轨+放量=强势, 触下轨+缩量=超卖, 缩口=变盘前兆",
  },
  ATR: {
    title: "ATR (平均真实波幅)",
    definition: "衡量股价波动幅度的指标。ATR越大说明波动越剧烈，风险越高；ATR缩小说明波动减弱，可能酝酿突破。常用于设置止损位和仓位管理：止损距离通常为1.5~3倍ATR。",
    benchmark: "ATR扩大=波动加剧, ATR缩小=盘整蓄势",
  },
  // ─── 量价指标 ───
  OBV: {
    title: "OBV (能量潮)",
    definition: "将成交量按涨跌方向累加：涨日加成交量，跌日减成交量。反映市场买卖力量的变化。OBV与股价同步上升确认上涨趋势；OBV上升而股价未涨暗示主力吸筹，可能即将突破；OBV下降而股价未跌可能是主力出货信号。",
    benchmark: "OBV创新高+价涨=趋势确认, OBV背离价格=警示信号",
  },
  VWAP: {
    title: "VWAP (成交量加权平均价)",
    definition: "考虑成交量的加权平均价格，反映当日的平均交易成本。股价在VWAP上方说明多数持仓者盈利（多头占优），下方则多数亏损（空头占优）。机构投资者常用VWAP作为交易基准。",
    benchmark: "价格>VWAP 多头占优, 价格<VWAP 空头占优",
  },
  volume: {
    title: "成交量",
    definition: "一段时间内成交的股票数量，反映市场参与度和资金活跃程度。放量上涨确认趋势强度，缩量上涨可能是上涨乏力；放量下跌说明恐慌抛售，缩量下跌可能是下跌尾声。量价配合是最基础的技术分析原则。",
    benchmark: "放量突破=有效突破, 缩量回调=健康调整, 天量见天价=警惕",
  },
  turnover_rate: {
    title: "换手率",
    definition: "当日成交量 / 流通股本 × 100%，反映股票的流动性和市场关注度。高换手率说明交易活跃、分歧大；低换手率说明关注度低或一致看好惜售。新股和题材股换手率通常较高。",
    benchmark: "<3% 清淡, 3%-7% 正常, 7%-15% 活跃, >15% 异常活跃",
  },
  // ─── 趋势概念 ───
  golden_cross: {
    title: "金叉",
    definition: "短期均线（或指标线）从下向上穿越长期均线（或慢速线），通常被视为买入信号。金叉出现在低位区域时更有效，高位区域的金叉可信度降低。需配合成交量确认。",
  },
  death_cross: {
    title: "死叉",
    definition: "短期均线（或指标线）从上向下穿越长期均线（或慢速线），通常被视为卖出信号。死叉出现在高位区域时更有效，低位区域的死叉可能是假信号。",
  },
  support: {
    title: "支撑位",
    definition: "价格下跌到某一区域后多次止跌反弹，该区域即为支撑位。支撑位代表买方力量集中区。支撑位被有效跌破后会转化为阻力位（支撑阻力互换原理）。前期低点、整数关口、均线位置都可能形成支撑。",
  },
  resistance: {
    title: "阻力位",
    definition: "价格上涨到某一区域后多次受阻回落，该区域即为阻力位。阻力位代表卖方力量集中区。阻力位被有效突破后会转化为支撑位。前期高点、套牢密集区、整数关口都可能形成阻力。",
  },
  divergence: {
    title: "背离",
    definition: "股价走势与技术指标（如MACD、RSI）走势相反的现象。顶背离：股价创新高但指标未创新高，预示上涨动力衰竭，是卖出警示。底背离：股价创新低但指标未创新低，预示下跌动能减弱，是买入机会。背离是最强的反转预警信号之一。",
  },
  // ─── 资金面概念 ───
  fund_flow: {
    title: "资金流向",
    definition: "通过分析大单、中单、小单的买卖差额判断资金进出。主力资金（大单）净流入通常是积极信号，净流出则需警惕。北向资金（外资）流向被视为A股的「聪明钱」风向标。",
  },
  dragon_tiger: {
    title: "龙虎榜",
    definition: "沪深交易所公布的异常交易数据。当股票日涨跌幅偏离值达7%、换手率达20%或连续三日涨跌偏离值达20%时上榜。龙虎榜显示买卖前五席位的机构和营业部，是分析主力动向的重要参考。机构席位净买入通常是看好信号。",
  },
  // ─── A股交易规则 ───
  t_plus_one: {
    title: "T+1 制度",
    definition: "A股交易规则：今天买入的股票，最早明天才能卖出。这意味着短线操作需承受隔夜风险。",
  },
  lot_size: {
    title: "手 (Lot)",
    definition: "A股最小交易单位，1手 = 100股。买入时必须是100股的整数倍。",
  },
  stamp_tax: {
    title: "印花税",
    definition: "卖出股票时征收的税费，税率为成交金额的0.05%（仅卖出方收取）。",
  },
  limit_up: {
    title: "涨停",
    definition: "A股涨跌幅限制制度。主板个股单日涨幅不超过10%（ST股5%），创业板和科创板不超过20%。涨停说明买方力量极强，但涨停板上买入风险也大。",
    benchmark: "主板±10%, 创业板/科创板±20%, ST股±5%",
  },
  limit_down: {
    title: "跌停",
    definition: "股价单日跌幅达到涨跌幅限制。跌停说明卖方恐慌，通常意味着重大利空或市场情绪极度悲观。跌停板上的大量封单越多，次日继续下跌的概率越高。",
  },
}

interface GlossaryTooltipProps {
  term: string
  children: ReactNode
}

export function GlossaryTooltip({ term, children }: GlossaryTooltipProps) {
  const entry = GLOSSARY_MAP[term]
  if (!entry) return <>{children}</>

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="border-b border-dotted border-muted-foreground/40 cursor-help">
            {children}
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs p-3">
          <p className="font-medium text-sm mb-1">{entry.title}</p>
          <p className="text-xs text-muted-foreground">{entry.definition}</p>
          {entry.benchmark && (
            <p className="text-xs text-primary mt-1">{entry.benchmark}</p>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export { GLOSSARY_MAP }
