# 2026-09-14多报告联合审计+代码修复记录

## 审计范围
6份自动推送报告：盘前预案、盘中天梯(10:15/14:15)、涨停归档、收盘复盘、策略进化审计

## 发现P0问题

### P0-1: iron_rule_gate缺streak>=3物理拦截
- 文件: market_regime_check.py
- 问题: 买入候选推送4板标的(闽东电力)无拦截
- 修复: 新增门禁0.5 — 方向buy且streak>=3直接熔断
- 验证: streak=3/4/7🚫, streak=0/2/无🚫✅

### P0-2: 天梯评分公式成交额权重过高
- 文件: intraday_hot_sector_sniper.py
- 问题: 原公式 = amt×10 + chg×5 → 三环集团(126元)等机构大票冒充连板天梯
- 修复: total_score = limitup_cnt×0.6 + max_streak×1.0 + norm_inflow×0.4

### P0-3: 盘中天梯不读增强天梯数据
- 文件: intraday_hot_sector_sniper.py
- 问题: 只用问财行业资金流入排序，国芳7板/桂林5板消失
- 修复: fetch_intraday_ladder()优先读取 ladder_enhanced_YYYY-MM-DD.json

### P0-4: 持仓止盈线静态锚定
- 文件: premarket_plan_compiler.py
- 问题: 平潭+15%浮盈仍用7.32止盈(较前收盘跌-5.55%)
- 修复: 浮盈>10% → max(昨收×0.98,今高×0.95); 浮盈5-10% → 成本×1.03

## 关键发现
- 盘中天梯输出第一行必须展示全市场最高空间龙(国芳7板/桂林5板)
- 候选标的强制剔除股价>50元大盘股
- 转化率0%+贝叶斯17%是策略层系统性死锁，非单点bug
