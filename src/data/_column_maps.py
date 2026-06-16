"""AKShare Chinese-to-English column name mappings.

Centralizes all column renaming dictionaries used by the data fetcher
to translate AKShare's Chinese column names to English equivalents.
Per PRD AC-D001-2: DataFrame columns must use English names.
"""

# 日线 OHLCV 列映射 (ak.stock_zh_a_hist)
OHLCV_COLUMN_MAP: dict[str, str] = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_change",
    "涨跌额": "change",
    "换手率": "turnover",
}

# 指数日线列映射 (ak.stock_zh_index_daily_em)
INDEX_COLUMN_MAP: dict[str, str] = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
}

# 北向资金列映射 (ak.stock_hsgt_hist_em)
# Note: 当日资金流入 became NaN after Aug 2024; 当日成交净买额 has data.
NORTHBOUND_COLUMN_MAP: dict[str, str] = {
    "日期": "date",
    "当日成交净买额": "net_buy_amount",
    "当日余额": "daily_quota_balance",
    "历史累计净买额": "cumulative_net_buy",
}

# 融资融券列映射 (ak.macro_china_market_margin_sh / _sz)
MARGIN_COLUMN_MAP: dict[str, str] = {
    "日期": "date",
    "融资余额": "margin_balance",
    "融券余额": "short_balance",
    "融资融券余额": "total_margin_balance",
}

# 基本面数据列映射 (ak.stock_individual_info_em)
FUNDAMENTAL_COLUMN_MAP: dict[str, str] = {
    "item": "metric",
    "value": "value",
}

# 基本面中文指标名 -> 英文配置key的映射
FUNDAMENTAL_METRIC_NAME_MAP: dict[str, str] = {
    "总市值": "total_mv",
    "市盈率(动态)": "pe_ttm",
    "市净率": "pb",
    "营业收入": "revenue",
    "净利润": "net_profit",
}

# Index codes starting with "0" belong to SSE (上证); "3"/"4" to SZSE (深证)
SSE_INDEX_PREFIXES: tuple[str, ...] = ("000",)
SZSE_INDEX_PREFIXES: tuple[str, ...] = ("399", "395")

# 实时行情列映射 (ak.stock_zh_a_spot, Sina source)
REALTIME_SPOT_COLUMN_MAP: dict[str, str] = {
    "代码": "symbol",
    "名称": "name",
    "最新价": "price",
    "涨跌额": "change",
    "涨跌幅": "pct_change",
    "今开": "open",
    "最高": "high",
    "最低": "low",
    "昨收": "prev_close",
    "成交量": "volume",
    "成交额": "amount",
    "买入": "bid",
    "卖出": "ask",
}

# 龙虎榜列映射 (ak.stock_lhb_detail_em)
DRAGON_TIGER_COLUMN_MAP: dict[str, str] = {
    "序号": "rank",
    "代码": "symbol",
    "名称": "name",
    "上榜日": "date",
    "解读": "reason",
    "收盘价": "close",
    "涨跌幅": "pct_change",
    "龙虎榜净买额": "net_buy",
    "龙虎榜买入额": "buy_amount",
    "龙虎榜卖出额": "sell_amount",
    "龙虎榜成交额": "total_amount",
    "市场总成交额": "market_total",
    "净买额占总成交比": "net_buy_ratio",
    "成交额占总成交比": "amount_ratio",
    "换手率": "turnover",
    "流通市值": "float_mv",
    "上榜原因": "list_reason",
}

# 涨停板列映射 (ak.stock_zt_pool_em)
LIMIT_UP_COLUMN_MAP: dict[str, str] = {
    "序号": "rank",
    "代码": "symbol",
    "名称": "name",
    "涨跌幅": "pct_change",
    "最新价": "price",
    "成交额": "amount",
    "流通市值": "float_mv",
    "总市值": "total_mv",
    "换手率": "turnover",
    "封板资金": "seal_amount",
    "首次封板时间": "first_seal_time",
    "最后封板时间": "last_seal_time",
    "炸板次数": "break_count",
    "涨停统计": "streak",
    "连板数": "consecutive",
    "所属行业": "industry",
}

# 跌停板列映射 (ak.stock_zt_pool_dtgc_em)
LIMIT_DOWN_COLUMN_MAP: dict[str, str] = {
    "序号": "rank",
    "代码": "symbol",
    "名称": "name",
    "涨跌幅": "pct_change",
    "最新价": "price",
    "成交额": "amount",
    "流通市值": "float_mv",
    "总市值": "total_mv",
    "换手率": "turnover",
    "封单资金": "seal_amount",
    "最后封板时间": "last_seal_time",
    "板上成交额": "seal_amount_traded",
    "连续跌停": "consecutive",
    "开板次数": "break_count",
    "所属行业": "industry",
}

# 龙虎榜个股席位明细列映射 (ak.stock_lhb_stock_detail_em)
DRAGON_TIGER_SEAT_COLUMN_MAP: dict[str, str] = {
    "序号": "rank",
    "交易营业部名称": "seat_name",
    "买入金额": "buy_amount",
    "买入金额-占总成交比例": "buy_pct",
    "卖出金额": "sell_amount",
    "卖出金额-占总成交比例": "sell_pct",
    "净额": "net_amount",
    "类型": "reason",
}

# 龙虎榜个股统计列映射 (ak.stock_lhb_stock_statistic_em)
DRAGON_TIGER_STOCK_STATS_COLUMN_MAP: dict[str, str] = {
    "序号": "rank",
    "代码": "symbol",
    "名称": "name",
    "最近上榜日": "last_date",
    "收盘价": "close",
    "涨跌幅": "pct_change",
    "上榜次数": "appearances",
    "龙虎榜净买额": "net_amount",
    "龙虎榜买入额": "total_buy",
    "龙虎榜卖出额": "total_sell",
    "龙虎榜总成交额": "total_amount",
    "买方机构次数": "inst_buy_count",
    "卖方机构次数": "inst_sell_count",
    "机构买入净额": "inst_net_amount",
    "机构买入总额": "inst_buy_amount",
    "机构卖出总额": "inst_sell_amount",
}

# Known institutional / hot-money seat name patterns
SEAT_TYPE_PATTERNS: dict[str, str] = {
    "机构专用": "机构",
    "沪股通": "机构",
    "深股通": "机构",
}

# 个股新闻列映射 (ak.stock_news_em)
NEWS_COLUMN_MAP: dict[str, str] = {
    "新闻标题": "title",
    "新闻内容": "content",
    "发布时间": "datetime",
    "文章来源": "source",
    "新闻链接": "url",
}

# 异动列映射 (ak.stock_changes_em)
ANOMALY_COLUMN_MAP: dict[str, str] = {
    "时间": "datetime",
    "代码": "symbol",
    "名称": "name",
    "板块": "sector",
    "相关信息": "description",
}

# 个股资金流向列映射 (ak.stock_individual_fund_flow)
FUND_FLOW_COLUMN_MAP: dict[str, str] = {
    "日期": "date",
    "收盘价": "close",
    "涨跌幅": "pct_change",
    "主力净流入-净额": "main_net",
    "主力净流入-净占比": "main_net_pct",
    "超大单净流入-净额": "super_large_net",
    "超大单净流入-净占比": "super_large_net_pct",
    "大单净流入-净额": "large_net",
    "大单净流入-净占比": "large_net_pct",
    "中单净流入-净额": "medium_net",
    "中单净流入-净占比": "medium_net_pct",
    "小单净流入-净额": "small_net",
    "小单净流入-净占比": "small_net_pct",
}

# 个股资金流向排名列映射 (ak.stock_individual_fund_flow_rank)
FUND_FLOW_RANK_COLUMN_MAP: dict[str, str] = {
    "代码": "symbol",
    "名称": "name",
    "最新价": "price",
    "今日涨跌幅": "pct_change",
    "今日主力净流入-净额": "main_net",
    "今日主力净流入-净占比": "main_net_pct",
    "今日超大单净流入-净额": "super_large_net",
    "今日超大单净流入-净占比": "super_large_net_pct",
    "今日大单净流入-净额": "large_net",
    "今日大单净流入-净占比": "large_net_pct",
    "今日中单净流入-净额": "medium_net",
    "今日中单净流入-净占比": "medium_net_pct",
    "今日小单净流入-净额": "small_net",
    "今日小单净流入-净占比": "small_net_pct",
}

# 个股资金流向明细列映射 (ak.stock_fund_flow_individual)
# Note: AKShare may return either "代码"/"名称" or "股票代码"/"股票简称"
FUND_FLOW_DETAIL_COLUMN_MAP: dict[str, str] = {
    "代码": "symbol",
    "股票代码": "symbol",
    "名称": "name",
    "股票简称": "name",
    "最新价": "price",
    "涨跌幅": "pct_change",
    "流入资金": "inflow",
    "流出资金": "outflow",
    "净额": "net",
    "成交额": "amount",
}

# Backward compat: fetcher.py uses stock_report_fund_hold_detail (fund code → portfolio)
FUND_HOLD_COLUMN_MAP: dict[str, str] = {
    "序号": "rank",
    "股票代码": "fund_code",
    "股票简称": "fund_name",
    "持股数": "shares_held",
    "持股市值": "market_value",
    "占总股本比例": "pct_of_total",
    "占流通股本比例": "pct_of_float",
}

# 机构持仓列映射 (ak.stock_institute_hold_detail: stock code → holders)
INSTITUTE_HOLD_COLUMN_MAP: dict[str, str] = {
    "持股机构类型": "inst_type",
    "持股机构代码": "inst_code",
    "持股机构简称": "inst_name",
    "持股机构全称": "inst_full_name",
    "持股数": "shares_held",
    "最新持股数": "latest_shares",
    "持股比例": "pct_of_total",
    "最新持股比例": "latest_pct_total",
    "占流通股比例": "pct_of_float",
    "最新占流通股比例": "latest_pct_float",
    "持股比例增幅": "pct_total_change",
    "占流通股比例增幅": "pct_float_change",
}

# 分析师评级列映射 (ak.stock_analyst_rank_em)
ANALYST_RANK_COLUMN_MAP: dict[str, str] = {
    "序号": "rank",
    "分析师名称": "analyst",
    "分析师单位": "institution",
    "年度指数": "annual_score",
    "成分股个数": "stock_count",
    "行业": "industry",
}

# 热门排名列映射 (ak.stock_hot_rank_em)
HOT_RANK_COLUMN_MAP: dict[str, str] = {
    "当前排名": "rank",
    "代码": "symbol",
    "股票名称": "name",
    "最新价": "price",
    "涨跌幅": "pct_change",
}
