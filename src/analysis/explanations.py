"""Beginner-friendly explanations for technical analysis indicators.

Provides clear Chinese explanations of all technical indicators used
in the system.  The platform acts as a senior quant analyst explaining
concepts to beginners (NFR-UX002).
"""

from typing import Any


INDICATOR_EXPLANATIONS: dict[str, dict[str, Any]] = {
    "MA": {
        "name": "移动平均线 (MA)",
        "short_desc": "一段时间内的平均收盘价，用于判断趋势方向",
        "full_desc": (
            "移动平均线是最基础的技术指标，它计算过去N天的平均收盘价，"
            "形成一条平滑的曲线。当股价在均线上方运行，说明当前处于上升趋势；"
            "当股价跌破均线，可能意味着趋势转弱。"
        ),
        "params": {
            "MA_5": "5日均线（短期趋势，反应灵敏但易产生假信号）",
            "MA_10": "10日均线（短中期过渡）",
            "MA_20": "20日均线（中期趋势，月线级别）",
            "MA_60": "60日均线（中长期趋势，季度线，机构常用）",
        },
        "signals": {
            "golden_cross": "金叉：短期均线上穿长期均线 → 看涨信号",
            "death_cross": "死叉：短期均线下穿长期均线 → 看跌信号",
            "support": "股价回踩均线获得支撑 → 均线有效，趋势延续",
            "breakdown": "股价跌破重要均线（如60日线） → 趋势可能反转",
        },
        "beginner_tip": (
            "💡 新手建议：关注20日和60日均线。股价站上60日线通常意味着"
            "中期趋势向好；跌破60日线则需要谨慎。不要仅凭5日线做决定，"
            "它波动太大。"
        ),
    },
    "MACD": {
        "name": "MACD 指标",
        "short_desc": "趋势跟踪指标，用于判断买卖时机和趋势强弱",
        "full_desc": (
            "MACD由两条线和柱状图组成：DIF线（快线）、DEA线（慢线）和MACD柱。"
            "DIF是12日和26日指数移动平均线的差值，DEA是DIF的9日平均。"
            "MACD柱 = (DIF - DEA) × 2。"
            "简单理解：MACD反映了短期趋势和长期趋势之间的差距。"
        ),
        "signals": {
            "golden_cross": "金叉：DIF上穿DEA（尤其在零轴下方） → 买入信号",
            "death_cross": "死叉：DIF下穿DEA（尤其在零轴上方） → 卖出信号",
            "above_zero": "DIF和DEA都在零轴上方 → 市场处于多头趋势",
            "below_zero": "DIF和DEA都在零轴下方 → 市场处于空头趋势",
            "divergence_top": "顶背离：股价创新高但MACD没创新高 → 上涨动力衰竭，注意风险",
            "divergence_bottom": "底背离：股价创新低但MACD没创新低 → 下跌动力减弱，可能反弹",
        },
        "beginner_tip": (
            "💡 新手建议：MACD最有价值的信号是'背离'。当股价不断上涨但MACD"
            "开始走平或下降，说明上涨的动力正在减弱，此时要特别警惕。"
            "金叉死叉在震荡市容易失效，需结合趋势判断。"
        ),
    },
    "RSI": {
        "name": "相对强弱指标 (RSI)",
        "short_desc": "衡量股票超买或超卖程度的动量指标",
        "full_desc": (
            "RSI计算一段时间内上涨幅度占总波动幅度的比例，"
            "范围在0-100之间。RSI > 70通常认为超买（涨太多），"
            "RSI < 30通常认为超卖（跌太多）。常用周期为14天。"
        ),
        "signals": {
            "overbought": "RSI > 70 → 超买区域，股价可能回调",
            "oversold": "RSI < 30 → 超卖区域，股价可能反弹",
            "strong_trend": "RSI在50以上运行 → 整体偏强",
            "weak_trend": "RSI在50以下运行 → 整体偏弱",
            "divergence": "RSI与股价走势背离 → 趋势可能反转",
        },
        "beginner_tip": (
            "💡 新手建议：RSI超买不等于立刻会跌！强势股的RSI可以长期在"
            "70以上运行。RSI更适合用于震荡行情的判断。在单边上涨的牛市中，"
            "RSI超买信号经常失效。超卖区域往往比超买区域更可靠。"
        ),
    },
    "KDJ": {
        "name": "KDJ 随机指标",
        "short_desc": "短期超买超卖指标，比RSI更灵敏",
        "full_desc": (
            "KDJ由K线、D线和J线三条线组成。K线是RSV（未成熟随机值）的平滑值，"
            "D线是K线的平滑值，J线 = 3K - 2D，是最灵敏的一条线。"
            "KDJ对短期价格变化非常敏感，适合捕捉短线机会。"
        ),
        "signals": {
            "golden_cross": "K线上穿D线（J线先行） → 短线买入信号",
            "death_cross": "K线下穿D线 → 短线卖出信号",
            "overbought": "J值 > 100 → 极度超买，短期可能回调",
            "oversold": "J值 < 0 → 极度超卖，短期可能反弹",
        },
        "beginner_tip": (
            "💡 新手建议：KDJ变化非常快，容易产生假信号。建议配合MACD一起"
            "使用——当MACD金叉时KDJ也金叉，信号更可靠。单独使用KDJ做交易"
            "决策风险较高。J值超过100或低于0时的极端情况比较有参考价值。"
        ),
    },
    "BOLL": {
        "name": "布林带 (Bollinger Bands)",
        "short_desc": "由上中下三条轨道组成，反映价格波动范围",
        "full_desc": (
            "布林带由三条线组成：中轨（20日移动平均线）、上轨（中轨+2倍标准差）、"
            "下轨（中轨-2倍标准差）。统计学上约95%的价格会落在上下轨之间。"
            "布林带会随波动率自动调节宽窄——行情剧烈时变宽，平静时变窄。"
        ),
        "signals": {
            "upper_touch": "股价触及上轨 → 短期偏强，但可能面临压力",
            "lower_touch": "股价触及下轨 → 短期偏弱，但可能获得支撑",
            "squeeze": "布林带收窄（缩口） → 即将出现大幅波动，方向待定",
            "breakout_up": "股价突破上轨 → 强势信号（但需确认）",
            "breakout_down": "股价跌破下轨 → 弱势信号（但需确认）",
            "walk_band": "股价沿上轨运行（走带） → 强势上涨趋势",
        },
        "beginner_tip": (
            "💡 新手建议：布林带收窄后的突破往往是重要信号。当三条轨道快速"
            "收紧，意味着一波大行情即将来临。但注意：股价触及上轨不等于要跌，"
            "在强势行情中股价可以持续'走'在上轨附近。关键看布林带是在扩张还是收缩。"
        ),
    },
    "VOL": {
        "name": "成交量",
        "short_desc": "交易活跃度的直接体现，量价关系是技术分析的基础",
        "full_desc": (
            "成交量是指某段时间内的股票交易数量。成交量放大表示市场参与度高，"
            "缩量表示观望情绪浓厚。量价配合是判断趋势的核心依据之一。"
        ),
        "signals": {
            "vol_price_up": "放量上涨 → 上涨得到资金认可，趋势健康",
            "vol_price_down": "放量下跌 → 抛压沉重，注意风险",
            "shrink_up": "缩量上涨 → 上涨缺乏资金支持，持续性存疑",
            "shrink_down": "缩量下跌 → 卖压减轻，可能接近底部",
            "vol_spike": "突然放巨量 → 通常是变盘信号，需特别关注",
        },
        "beginner_tip": (
            "💡 新手建议：永远不要忽视成交量！'量在价先'是最重要的规律之一。"
            "如果股价上涨但成交量持续萎缩，这是一个危险信号。"
            "底部放量通常是资金开始进场的标志。"
        ),
    },
    "SUPPORT_RESISTANCE": {
        "name": "支撑位与压力位",
        "short_desc": "股价在某些价位容易获得支撑或遇到阻力",
        "full_desc": (
            "支撑位是股价下跌到某个价位后，买方力量增强导致股价止跌的位置。"
            "压力位是股价上涨到某个价位后，卖方力量增强导致股价止涨的位置。"
            "这些位置通常由历史高低点、均线、密集成交区等形成。"
        ),
        "signals": {
            "support_hold": "股价在支撑位获得支撑并反弹 → 可考虑买入",
            "support_break": "股价跌破支撑位 → 可能继续下跌，原支撑变压力",
            "resistance_break": "股价突破压力位 → 打开上行空间，原压力变支撑",
            "resistance_hold": "股价在压力位遇阻回落 → 短期上涨受限",
        },
        "beginner_tip": (
            "💡 新手建议：整数关口（如100元、50元）往往是天然的支撑/压力位。"
            "一个位置被测试的次数越多（多次触及后反弹），支撑就越强。"
            "但一旦被突破，反转的力度也可能更大。"
        ),
    },
}


INDICATOR_ANALOGIES: dict[str, str] = {
    "RSI": "RSI 就像温度计——数值越高表示市场情绪越热，超过 80 就像'发烧'。",
    "MACD": "MACD 柱状图就像潮汐——正值代表涨潮（多头），负值代表退潮（空头）。",
    "KDJ": "KDJ 的 J 线就像弹簧——压得越低反弹越猛，拉得越高回调越快。",
    "BOLL": "布林带就像高速公路——中轨是车道中线，靠近上轨说明在超车道。",
    "VOL": "量比就像人流量——1.0 是正常，超过 2.0 相当于'客流暴增'。",
    "MA": "均线就像河流的平均水位——价格在水位之上说明在涨水期。",
    "SUPPORT_RESISTANCE": "支撑位就像地板，阻力位就像天花板——突破才能上楼或下楼。",
}


def get_indicator_explanation(indicator: str) -> dict[str, Any] | None:
    """Get the explanation for a specific indicator.

    Args:
        indicator: Indicator key (e.g. "MA", "MACD", "RSI").

    Returns:
        Explanation dictionary or None if not found.
    """
    return INDICATOR_EXPLANATIONS.get(indicator.upper())


def get_all_explanations() -> dict[str, dict[str, Any]]:
    """Get all indicator explanations."""
    return INDICATOR_EXPLANATIONS
