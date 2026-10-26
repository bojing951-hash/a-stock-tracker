# -*- coding: utf-8 -*-
"""
指标注册表 (阶段3/预警系统配置中心)
================================================
每个行业定义:
  - current_phase: "auto" 表示从 industry_cycle.csv 自动读取最新阶段
  - indicators: 可自动采集的指标列表 (source/field/file/frequency)
  - transition_rules: 阶段转换触发条件 (字符串规则，由 alert_engine 解析)
  - leading_indicators: 领先指标 (解决出清期踏空问题，多为人工跟踪)
  - strategy_override: 可选，标记 binary 失效行业改用 conservative
  - note: 备注

source 类型:
  sw_valuation  -> raw_data/indicators/sw_valuation.csv
  margin        -> raw_data/indicators/margin_balance.csv
  gold_sge      -> raw_data/indicators/gold_price_sge.csv
  lithium       -> raw_data/indicators/lithium_carbonate_futures.csv
  rebar         -> raw_data/indicators/rebar_spot.csv
  manual        -> 需人工确认 (返回 None，标记 pending_manual)

行业分组依据 backtest binary 超额年化:
  A组(2015起完整) / B组(2021起短周期)
"""

INDICATOR_REGISTRY = {

    # ====== A组：回测超额为正的行业（策略有效，重点维护规则）======

    "计算机设备": {  # binary超额+8.4%，A组第1
        "current_phase": "auto",
        "indicators": [
            {"name": "计算机行业PE_TTM", "source": "sw_valuation",
             "field": "pe_ttm", "sw_industry": "计算机", "frequency": "daily"},
            {"name": "AI服务器出货预期", "source": "manual",
             "frequency": "monthly", "note": "需人工跟踪IDC/Gartner季报"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "计算机行业PE_TTM > 55 AND 指数60日涨幅 > 40%",
            "成长期→成熟稳定期": "计算机行业PE_TTM 在 25-35 持续60日",
            "过剩期→出清期": "计算机行业PE_TTM < 20 AND 指数创250日新低",
        },
        "leading_indicators": [
            "指数是否突破250日均线（出清→复苏的领先信号）",
            "成交量20日均量 vs 60日均量（放量突破=资金先行）",
        ],
    },

    "非银金融": {  # binary超额+6.7%，A组第2
        "current_phase": "auto",
        "indicators": [
            {"name": "两融余额", "source": "margin",
             "field": "total_balance_yi", "frequency": "daily"},
            {"name": "非银金融PE_TTM", "source": "sw_valuation",
             "sw_industry": "非银金融", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "复苏期→成长期": "两融余额 > 22000 AND 非银金融PE_TTM > 18 AND 指数60日涨幅 > 25%",
            "成长期→景气顶部": "两融余额 > 30000 AND 非银金融PE_TTM > 25",
            "景气顶部→过剩期": "两融余额从峰值回落 > 15% AND 指数跌破60日均线",
            "过剩期→出清期": "两融余额 < 15000 AND 非银金融PE_TTM < 10",
        },
        "leading_indicators": [
            "两融余额20日变化率（>+3%/周=加速信号）",
            "日均成交额 vs 60日均值（>1.5倍=情绪升温）",
        ],
    },

    "传媒": {  # binary超额+6.0%
        "current_phase": "auto",
        "indicators": [
            {"name": "传媒行业PE_TTM", "source": "sw_valuation",
             "sw_industry": "传媒", "field": "pe_ttm", "frequency": "daily"},
            {"name": "游戏版号月度发放数", "source": "manual",
             "frequency": "monthly", "note": "国家新闻出版署每月公布，需人工录入"},
            {"name": "月度票房", "source": "manual",
             "frequency": "monthly", "note": "猫眼/灯塔数据，需人工录入"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "传媒行业PE_TTM > 40 AND 指数60日涨幅 > 50%",
            "成长期→成熟稳定期": "传媒行业PE_TTM 在 15-25 持续90日",
        },
        "leading_indicators": ["版号发放数量环比变化（政策松紧的领先信号）"],
    },

    "软件开发": {  # binary超额+4.2%
        "current_phase": "auto",
        "indicators": [
            {"name": "计算机行业PE_TTM", "source": "sw_valuation",
             "sw_industry": "计算机", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "计算机行业PE_TTM > 50 AND RSI_14 > 80",
            "过剩期→复苏期": "计算机行业PE_TTM < 25 AND 指数突破120日均线",
        },
        "leading_indicators": ["信创/国产替代政策事件（人工跟踪）"],
    },

    "电子": {  # binary超额+3.1%
        "current_phase": "auto",
        "indicators": [
            {"name": "电子行业PE_TTM", "source": "sw_valuation",
             "sw_industry": "电子", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "电子行业PE_TTM > 40 AND 指数60日涨幅 > 35%",
            "过剩期→复苏期": "电子行业PE_TTM < 18 AND MLCC价格环比转正",
        },
        "leading_indicators": [
            "MLCC渠道库存月数（<2个月=供给出清信号）",
            "费城半导体指数走势（领先A股电子2-3个月）",
        ],
    },

    "国防军工": {
        "current_phase": "auto",
        "indicators": [
            {"name": "国防军工PE_TTM", "source": "sw_valuation",
             "sw_industry": "国防军工", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "国防军工PE_TTM > 70 AND 指数60日涨幅 > 40%",
            "成长期→成熟稳定期": "国防军工PE_TTM 在 40-55 持续120日",
        },
        "leading_indicators": [
            "年度国防预算增速（每年3月两会公布）",
            "军工龙头季度合同负债变化",
        ],
    },

    "贵金属": {  # 逻辑切换型行业，传统产能周期弱
        "current_phase": "auto",
        "indicators": [
            {"name": "上海金基准价", "source": "gold_sge",
             "field": "price", "frequency": "daily"},
            {"name": "有色金属PE_TTM", "source": "sw_valuation",
             "sw_industry": "有色金属", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "上海金基准价 > 1000 AND 金价30日波动率 > 3%",
            "成长期→成熟稳定期": "上海金基准价 在 800-950 持续60日",
            "景气顶部→过剩期": "上海金基准价 从峰值回落 > 15%",
        },
        "leading_indicators": [
            "美元指数DXY走势（负相关领先指标）",
            "全球央行购金量月度数据（世界黄金协会）",
        ],
    },

    "房地产": {
        "current_phase": "auto",
        "indicators": [
            {"name": "房地产行业PE_TTM", "source": "sw_valuation",
             "sw_industry": "房地产", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "出清期→复苏期": "房地产行业PE_TTM 从底部回升 > 20% AND 指数突破120日均线",
            "复苏期→成长期": "商品房月度销售面积连续3月同比转正",
        },
        "leading_indicators": [
            "30大中城市商品房成交面积周数据",
            "房贷利率变化（政策领先信号）",
        ],
    },

    "食品饮料": {
        "current_phase": "auto",
        "indicators": [
            {"name": "食品饮料PE_TTM", "source": "sw_valuation",
             "sw_industry": "食品饮料", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "出清期→复苏期": "食品饮料PE_TTM < 25 AND 指数突破250日均线",
            "复苏期→成长期": "食品饮料PE_TTM 在 25-35 AND 白酒批价企稳",
        },
        "leading_indicators": [
            "茅台批价走势（行业信心锚）",
            "社零消费数据月度同比",
        ],
    },

    "电力设备": {
        "current_phase": "auto",
        "indicators": [
            {"name": "电力设备PE_TTM", "source": "sw_valuation",
             "sw_industry": "电力设备", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "过剩期→复苏期": "电力设备PE_TTM < 20 AND 指数突破120日均线",
            "成长期→景气顶部": "电力设备PE_TTM > 50",
        },
        "leading_indicators": ["电网投资完成额月度数据"],
    },

    "汽车零部件": {  # binary超额+1.89%（补充：任务清单遗漏，补齐22行业）
        "current_phase": "auto",
        "indicators": [
            {"name": "汽车行业PE_TTM", "source": "sw_valuation",
             "sw_industry": "汽车", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "汽车行业PE_TTM > 35 AND 指数60日涨幅 > 30%",
            "过剩期→复苏期": "汽车行业PE_TTM < 18 AND 指数突破120日均线",
        },
        "leading_indicators": [
            "乘用车月度销量同比（中汽协）",
            "新能源车渗透率月度数据",
        ],
    },

    # ====== A组：回测超额为负的行业（策略失效，需特殊处理）======

    "基础化工": {  # binary超额-6.1%，最差！时滞偏离严重
        "current_phase": "auto",
        "indicators": [
            {"name": "基础化工PE_TTM", "source": "sw_valuation",
             "sw_industry": "基础化工", "field": "pe_ttm", "frequency": "daily"},
            {"name": "螺纹钢现货价", "source": "rebar",
             "field": "spot", "frequency": "daily"},
        ],
        "transition_rules": {
            "过剩期→出清期": "基础化工PE_TTM < 12 AND 螺纹钢现货价 < 3200",
            "出清期→复苏期": "基础化工PE_TTM 从底部回升 > 15% AND 指数突破60日均线",
        },
        "strategy_override": "CONSERVATIVE_ONLY",
        "note": "binary模式超额-6.1%，时滞偏离严重。建议仅用conservative模式(出清期也持仓)，或降级为纯估值择时",
    },

    "煤炭": {  # binary超额-3.9%
        "current_phase": "auto",
        "indicators": [
            {"name": "煤炭行业PE_TTM", "source": "sw_valuation",
             "sw_industry": "煤炭", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "成熟稳定期→过剩期": "煤炭行业PE_TTM > 15 AND 动力煤期货跌破800",
            "过剩期→出清期": "煤炭行业PE_TTM > 20（亏损扩大）",
        },
        "strategy_override": "CONSERVATIVE_ONLY",
        "note": "高股息属性强，周期择时效果差。建议用股息率>5%作为买入信号替代周期择时",
    },

    "有色金属": {
        "current_phase": "auto",
        "indicators": [
            {"name": "有色金属PE_TTM", "source": "sw_valuation",
             "sw_industry": "有色金属", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "有色金属PE_TTM > 30 AND RSI_14 > 75",
        },
        "strategy_override": "CONSERVATIVE_ONLY",
        "note": "binary超额-1.9%，子行业差异大(贵金属vs能源金属vs工业金属)，一级行业周期择时失效",
    },

    "通信设备": {
        "current_phase": "auto",
        "indicators": [
            {"name": "通信行业PE_TTM", "source": "sw_valuation",
             "sw_industry": "通信", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "通信行业PE_TTM > 35 AND 指数60日涨幅 > 25%",
        },
        "leading_indicators": ["5G/6G基站建设招标数据"],
    },

    # ====== B组行业（2021起数据，短周期但超额表现好）======

    "能源金属": {  # binary超额+15.6%，全场最佳
        "current_phase": "auto",
        "indicators": [
            {"name": "碳酸锂期货价", "source": "lithium",
             "field": "close", "frequency": "daily"},
            {"name": "有色金属PE_TTM", "source": "sw_valuation",
             "sw_industry": "有色金属", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "出清期→复苏期": "碳酸锂期货价 > 100000 持续20日 AND 指数突破60日均线",
            "复苏期→成长期": "碳酸锂期货价 > 150000 AND 锂矿龙头合同负债增长",
            "成长期→景气顶部": "碳酸锂期货价 > 400000 AND 指数60日涨幅 > 60%",
            "景气顶部→过剩期": "碳酸锂期货价 从峰值回落 > 30%",
            "过剩期→出清期": "碳酸锂期货价 < 100000 AND 行业产能利用率 < 55%",
        },
        "leading_indicators": [
            "碳酸锂期货价20日趋势方向（最强领先指标）",
            "下游新能源车月度产量（中汽协数据，人工录入）",
        ],
    },

    "医疗器械": {  # binary超额+10.3%
        "current_phase": "auto",
        "indicators": [
            {"name": "医药生物PE_TTM", "source": "sw_valuation",
             "sw_industry": "医药生物", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "复苏期→成长期": "医药生物PE_TTM > 30 AND 指数突破250日均线",
            "出清期→复苏期": "医药生物PE_TTM < 22 AND 集采边际放缓",
        },
        "leading_indicators": ["集采政策动态（人工跟踪）", "医保基金支出增速"],
    },

    "电池": {  # binary超额+5.5%
        "current_phase": "auto",
        "indicators": [
            {"name": "碳酸锂期货价", "source": "lithium",
             "field": "close", "frequency": "daily"},
            {"name": "电力设备PE_TTM", "source": "sw_valuation",
             "sw_industry": "电力设备", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "复苏期→成长期": "碳酸锂期货价 企稳 AND 电池装机量月度同比 > 30%",
            "成长期→景气顶部": "电力设备PE_TTM > 50 AND 碳酸锂期货价 > 250000",
        },
        "leading_indicators": ["碳酸锂价格趋势（与能源金属共享）", "动力电池月度装机量"],
    },

    "风电设备": {  # binary超额+4.7%
        "current_phase": "auto",
        "indicators": [
            {"name": "电力设备PE_TTM", "source": "sw_valuation",
             "sw_industry": "电力设备", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "过剩期→复苏期": "电力设备PE_TTM < 20 AND 风电招标量连续2月环比增长",
        },
        "leading_indicators": ["风电招标量月度数据", "电网投资计划"],
    },

    "半导体": {  # binary超额+3.5%
        "current_phase": "auto",
        "indicators": [
            {"name": "电子行业PE_TTM", "source": "sw_valuation",
             "sw_industry": "电子", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "成长期→景气顶部": "电子行业PE_TTM > 40 AND RSI_14 > 80",
            "过剩期→复苏期": "电子行业PE_TTM < 20 AND 全球半导体销售额同比转正",
        },
        "leading_indicators": [
            "费城半导体指数SOX（领先A股半导体2-3月）",
            "SIA全球半导体月度销售数据",
        ],
    },

    "光伏设备": {  # binary超额+0.8%
        "current_phase": "auto",
        "indicators": [
            {"name": "电力设备PE_TTM", "source": "sw_valuation",
             "sw_industry": "电力设备", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "出清期→复苏期": "光伏组件价格企稳连续3月不创新低 AND 指数突破60日均线",
            "复苏期→成长期": "硅料价格回升 > 20% AND 装机量同比 > 40%",
        },
        "leading_indicators": ["硅料/硅片/电池片/组件价格链周度数据（InfoLink）"],
    },

    "消费电子": {  # binary超额-5.1%，B组最差
        "current_phase": "auto",
        "indicators": [
            {"name": "电子行业PE_TTM", "source": "sw_valuation",
             "sw_industry": "电子", "field": "pe_ttm", "frequency": "daily"},
        ],
        "transition_rules": {
            "过剩期→复苏期": "电子行业PE_TTM < 18 AND 手机出货量月度同比转正",
        },
        "strategy_override": "CONSERVATIVE_ONLY",
        "note": "binary超额-5.1%，产品周期驱动而非产能周期，择时框架不适配",
    },
}


if __name__ == "__main__":
    import json
    n = len(INDICATOR_REGISTRY)
    auto = sum(1 for v in INDICATOR_REGISTRY.values()
               if any(i["source"] != "manual" for i in v["indicators"]))
    manual = sum(1 for v in INDICATOR_REGISTRY.values()
                 if any(i["source"] == "manual" for i in v["indicators"]))
    override = [k for k, v in INDICATOR_REGISTRY.items()
                if v.get("strategy_override") == "CONSERVATIVE_ONLY"]
    print(f"注册表行业数: {n}")
    print(f"有自动化指标: {auto}/{n}")
    print(f"含manual指标: {manual}/{n}")
    print(f"CONSERVATIVE_ONLY: {len(override)}个 -> {override}")
