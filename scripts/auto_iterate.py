#!/usr/bin/env python3
"""
Astock 自动迭代引擎 — 100+ 轮自我改进循环.

每轮尝试一个参数变化 → 运行回测 → 对比基线 → 保留/回退.
持续记录到 iteration_log.txt，支持断点续跑.
"""
from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import random
import sys
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 抑制打印（在迭代中我们自行控制输出）
import builtins as _builtins

# ── 参数空间 ──
# 每项: (名称, 当前值, 候选值列表)
PARAM_SPACE = [
    # === 评分权重 ===
    ("score_weights.volume",      25, [20, 25, 30, 35]),
    ("score_weights.dh",          20, [15, 20, 25]),
    ("score_weights.ma",          20, [15, 20, 25, 30]),
    ("score_weights.rsi",         15, [10, 15, 20]),
    ("score_weights.chg",         15, [10, 15, 20]),
    ("score_weights.vol_bonus",    5, [3, 5, 8]),
    ("score_weights.new_high_bonus", 5, [3, 5, 8, 10]),
    ("score_weights.pullback_bonus", 10, [5, 10, 15]),
    # === 评分返回参数 ===
    ("score_weights.target_pct",   8, [6, 8, 10, 12]),
    ("score_weights.stop_pct",  -2.8, [-2.0, -2.5, -2.8, -3.0, -3.5]),
    ("score_weights.hold_days",    3, [2, 3, 4, 5]),
    # === 硬过滤 ===
    ("hard_filters.min_vr",      0.8, [0.5, 0.7, 0.8, 1.0]),
    ("hard_filters.min_rs",       25, [20, 25, 30, 35]),
    ("hard_filters.ma_pct",     0.95, [0.93, 0.95, 0.96, 0.98]),
    # === 选池过滤 ===
    ("min_vr",                   1.5, [1.0, 1.2, 1.5, 2.0]),
    ("min_close",               10.0, [5.0, 8.0, 10.0, 15.0]),
    # === 仓位 ===
    ("max_pos_pct",             0.35, [0.25, 0.30, 0.35, 0.40]),
    # === 卖出规则 ===
    ("sell_rules.trail_trigger", 3.0, [2.0, 2.5, 3.0, 4.0]),
    ("sell_rules.trail_high_rate", 0.3, [0.2, 0.25, 0.3, 0.4]),
    ("sell_rules.trail_low_rate", 0.4, [0.3, 0.35, 0.4, 0.5]),
    ("sell_rules.trail_high_thresh", 5.0, [4.0, 5.0, 6.0, 8.0]),
    ("sell_rules.breakeven_peak", 3.0, [2.0, 3.0, 4.0]),
    ("sell_rules.breakeven_thresh", 0.5, [0.0, 0.3, 0.5, 1.0]),
    ("sell_rules.weak_hold",      2, [1, 2, 3]),
    ("sell_rules.weak_thresh", -0.5, [-1.0, -0.5, 0.0]),
    ("sell_rules.max_hold",       5, [4, 5, 6, 7]),
    # === 体制映射（5个体制 × 3参数 = 15项） ===
    *[(f"regime_map.euphoria.{i}", v, candidates)
      for i, v, candidates in [
          (0, 65, [55, 60, 65, 70]),   # min_score
          (1, 2,  [1, 2, 3]),          # max_pos
          (2, 0.35, [0.25, 0.30, 0.35, 0.40]), # cap_pct
      ]],
    *[(f"regime_map.hot.{i}", v, candidates)
      for i, v, candidates in [
          (0, 70, [60, 65, 70, 75]),
          (1, 1,  [1, 2]),
          (2, 0.20, [0.15, 0.20, 0.25]),
      ]],
    *[(f"regime_map.warmup.{i}", v, candidates)
      for i, v, candidates in [
          (0, 60, [50, 55, 60, 65]),
          (1, 5,  [3, 4, 5, 6]),
          (2, 0.30, [0.25, 0.30, 0.35]),
      ]],
    *[(f"regime_map.cooldown.{i}", v, candidates)
      for i, v, candidates in [
          (0, 60, [50, 55, 60, 65]),
          (1, 3,  [2, 3, 4]),
          (2, 0.28, [0.20, 0.25, 0.28, 0.30]),
      ]],
    *[(f"regime_map.ice.{i}", v, candidates)
      for i, v, candidates in [
          (0, 70, [60, 65, 70, 75]),
          (1, 1,  [1, 2]),
          (2, 0.15, [0.10, 0.15, 0.20]),
      ]],
]

# ── 迭代配置 ──
TOTAL_ROUNDS = 150
ITERATION_LOG = Path(__file__).resolve().parent.parent / "results" / "iteration_log.txt"
BEST_CONFIG_FILE = Path(__file__).resolve().parent.parent / "results" / "best_config.json"
PROGRESS_FILE = Path(__file__).resolve().parent.parent / "results" / "iteration_progress.json"


def set_nested(d: dict, key_path: str, value) -> dict:
    """在嵌套字典中设置值. 'a.b.c' → d['a']['b']['c'] = value"""
    keys = key_path.split(".")
    target = d
    for k in keys[:-1]:
        if k not in target or not isinstance(target[k], dict):
            target[k] = {}
        target = target[k]
    target[keys[-1]] = value
    return d


def get_nested(d: dict, key_path: str, default=None):
    """从嵌套字典取值."""
    keys = key_path.split(".")
    target = d
    for k in keys:
        if isinstance(target, dict) and k in target:
            target = target[k]
        else:
            return default
    return target


def build_config(params: dict) -> dict:
    """从扁平参数字典构建嵌套配置."""
    cfg = {}
    for key, value in params.items():
        set_nested(cfg, key, value)

    # 处理 regime_map: 用默认值填充缺失的体制
    if "regime_map" in cfg:
        defaults = {
            "euphoria": (65, 2, 0.35),
            "hot": (70, 1, 0.20),
            "warmup": (60, 5, 0.30),
            "cooldown": (60, 3, 0.28),
            "ice": (70, 1, 0.15),
        }
        for regime, default_vals in defaults.items():
            if regime not in cfg["regime_map"] or not isinstance(cfg["regime_map"].get(regime), dict):
                cfg["regime_map"][regime] = default_vals
            else:
                # dict 格式: {"0": ms, "1": mx, "2": cp} → 用默认值填充缺失
                d = cfg["regime_map"][regime]
                cfg["regime_map"][regime] = (
                    int(d.get("0", default_vals[0])),
                    int(d.get("1", default_vals[1])),
                    float(d.get("2", default_vals[2])),
                )
    return cfg


def composite_score(results: dict) -> float:
    """综合评分: 平衡收益、风险、胜率."""
    if not results:
        return -999
    sharpe = results.get("sharpe", 0)
    ret = results.get("ret", 0)
    mdd = results.get("mdd", 20)
    wr = results.get("wr", 0)
    pf = results.get("pf", 0)
    monthly = results.get("monthly_ret_mean", 0)

    # 夏普权重最高
    score = sharpe * 3.0
    # 总收益（年化后）
    score += min(ret, 300) / 100 * 2.0
    # 胜率
    score += (wr - 40) / 20
    # 盈亏比
    score += min(pf, 5) / 2
    # 惩罚回撤
    score -= mdd / 10
    # 月均收益
    score += monthly / 5
    # 惩罚亏损月比例
    neg_ratio = results.get("negative_months", 0) / max(results.get("total_months", 1), 1)
    score -= neg_ratio * 3
    # 奖励交易次数（数据量）
    score += min(results.get("trades", 0) / 100, 2)

    return score


def format_params(params: dict) -> str:
    """格式化参数字典为可读字符串."""
    lines = []
    for k, v in sorted(params.items()):
        lines.append(f"    {k} = {v}")
    return "\n".join(lines)


def run_single_backtest(config: dict, silent: bool = True) -> dict:
    """运行一次回测."""
    # 始终跳过缓存写入（首次已缓存）
    cfg = {**config, "skip_cache_save": True}
    # 导入（每次重新加载）
    import backtest_2yr
    importlib.reload(backtest_2yr)

    # 保存当前打印函数，临时替换为静默
    orig_print = _builtins.print
    if silent:
        def null_print(*args, **kwargs):
            pass
        _builtins.print = null_print

    try:
        t0 = time.time()
        results = backtest_2yr.run_backtest(cfg)
        elapsed = time.time() - t0
        if results:
            results["elapsed"] = round(elapsed, 1)
        return results
    except Exception as e:
        if silent:
            _builtins.print = orig_print
        print(f"  [ERROR] Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return {}
    finally:
        if silent:
            _builtins.print = orig_print


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE) as f:
                return json.load(f)
        except Exception:
            return {"round": 0, "best_score": -999, "best_params": {}, "history": []}
    return {"round": 0, "best_score": -999, "best_params": {}, "history": []}


def save_progress(progress: dict):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def main():
    print("=" * 80)
    print("  Astock 自动迭代引擎 v1")
    print(f"  目标: {TOTAL_ROUNDS} 轮参数优化")
    print(f"  参数空间: {len(PARAM_SPACE)} 个可调参数")
    print(f"  开始时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 加载进度（支持断点续跑）
    progress = load_progress()
    start_round = progress["round"]
    best_score = progress["best_score"]
    best_params = progress.get("best_params", {})
    history = progress.get("history", [])

    # 如果没有历史，先跑基线
    if start_round == 0:
        print("\n[Round 0] 建立基线...")
        baseline_config = {}
        results = run_single_backtest(baseline_config, silent=False)
        if not results:
            print("基线回测失败！退出。")
            return
        baseline_score = composite_score(results)
        best_score = baseline_score
        best_params = {}
        history.append({
            "round": 0,
            "params": {},
            "composite": round(baseline_score, 2),
            "ret": results.get("ret"),
            "sharpe": results.get("sharpe"),
            "wr": results.get("wr"),
            "pf": results.get("pf"),
            "mdd": results.get("mdd"),
            "monthly": results.get("monthly_ret_mean"),
            "trades": results.get("trades"),
        })
        progress = {"round": 1, "best_score": best_score, "best_params": {}, "history": history}
        save_progress(progress)
        print(f"  基线: composite={baseline_score:.2f}, ret={results.get('ret'):+.2f}%, "
              f"sharpe={results.get('sharpe'):.2f}, wr={results.get('wr'):.0f}%, "
              f"mdd={results.get('mdd'):.2f}%")
        start_round = 1

    # 读取最佳参数
    current_params = deepcopy(best_params)
    current_score = best_score
    no_improve_count = 0

    print(f"\n从第 {start_round} 轮开始，当前最佳 composite={best_score:.2f}")

    for round_num in range(start_round, TOTAL_ROUNDS + 1):
        print(f"\n{'─'*60}")
        print(f"[Round {round_num}/{TOTAL_ROUNDS}] "
              f"最佳: {best_score:.2f} ({no_improve_count}轮无改进)")

        # 选择一个随机参数进行变异
        param_name, current_val, candidates = random.choice(PARAM_SPACE)

        # 排除当前值，选一个不同的值
        available = [v for v in candidates if v != current_val]
        if not available:
            print(f"  跳过 {param_name}: 无候选值")
            no_improve_count += 1
            continue

        new_val = random.choice(available)

        # 获取当前值
        old_val = get_nested(current_params, param_name, current_val)
        if old_val != current_val:
            available = [v for v in candidates if v != old_val]
            if available:
                new_val = random.choice(available)
            else:
                continue
            param_val = old_val
        else:
            param_val = current_val

        print(f"  变异: {param_name}: {old_val} → {new_val}")

        # 构建新配置
        test_params = deepcopy(current_params)
        set_nested(test_params, param_name, new_val)
        config = build_config(test_params)

        # 运行回测
        t0 = time.time()
        results = run_single_backtest(config, silent=False)
        if not results:
            print(f"  回测失败，跳过")
            no_improve_count += 1
            continue

        new_score = composite_score(results)
        elapsed = time.time() - t0
        entry = {
            "round": round_num,
            "param": param_name,
            "old_val": old_val,
            "new_val": new_val,
            "composite": round(new_score, 2),
            "ret": results.get("ret"),
            "sharpe": results.get("sharpe"),
            "wr": results.get("wr"),
            "pf": results.get("pf"),
            "mdd": results.get("mdd"),
            "monthly": results.get("monthly_ret_mean"),
            "trades": results.get("trades"),
            "elapsed": round(elapsed, 1),
        }

        # 比较
        if new_score > best_score * 0.995:
            # 保留改进
            best_score = new_score
            best_params = deepcopy(test_params)
            current_params = deepcopy(test_params)
            current_score = new_score
            no_improve_count = 0
            entry["verdict"] = "ACCEPT (new best)"
            print(f"  ✓ ACCEPT: composite {new_score:.2f} > {best_score:.2f} "
                  f"(ret={results.get('ret'):+.2f}%, sharpe={results.get('sharpe'):.2f}, "
                  f"wr={results.get('wr'):.0f}%, mdd={results.get('mdd'):.2f}%)")

            # 保存最佳配置
            with open(BEST_CONFIG_FILE, "w") as f:
                json.dump({"params": best_params, "config": config, "results": {
                    "ret": results.get("ret"),
                    "sharpe": results.get("sharpe"),
                    "wr": results.get("wr"),
                    "pf": results.get("pf"),
                    "mdd": results.get("mdd"),
                    "monthly_ret_mean": results.get("monthly_ret_mean"),
                    "trades": results.get("trades"),
                    "composite": round(new_score, 2),
                }}, f, indent=2, ensure_ascii=False)
        else:
            entry["verdict"] = "REJECT"
            no_improve_count += 1
            current_params = deepcopy(best_params)  # 回退到最佳参数
            print(f"  ✗ REJECT: composite {new_score:.2f} vs best {best_score:.2f}")

        history.append(entry)

        # 每 5 轮保存进度
        if round_num % 5 == 0 or no_improve_count >= 10:
            progress = {
                "round": round_num + 1,
                "best_score": best_score,
                "best_params": best_params,
                "history": history,
            }
            save_progress(progress)

        # 如果长时间无改进，扩大搜索范围
        if no_improve_count >= 15:
            print(f"\n  ⚠ 连续 {no_improve_count} 轮无改进，扩大搜索范围...")
            # 重置变异计数器，尝试更多极端值
            no_improve_count = 0

        # 每 10 轮打印汇总
        if round_num % 10 == 0:
            wins = sum(1 for h in history[-10:] if "ACCEPT" in h.get("verdict", ""))
            print(f"\n  [汇总] 最近10轮: {wins}次改进 | "
                  f"最佳 composite: {best_score:.2f}")

    # ── 最终报告 ──
    print("\n" + "=" * 80)
    print("  迭代完成!")
    print(f"  总轮数: {TOTAL_ROUNDS}")
    print(f"  最佳 composite: {best_score:.2f}")
    print(f"  最佳参数:")
    print(format_params(best_params))
    print("=" * 80)

    # 保存最终结果
    progress = {
        "round": TOTAL_ROUNDS + 1,
        "best_score": best_score,
        "best_params": best_params,
        "history": history,
        "finished": True,
    }
    save_progress(progress)

    # 生成迭代日志
    lines = []
    lines.append("=" * 120)
    lines.append("  Astock 自动迭代报告")
    lines.append(f"  时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  总轮数: {TOTAL_ROUNDS}")
    lines.append(f"  最佳 composite: {best_score:.2f}")
    lines.append("=" * 120)
    lines.append("")
    lines.append("最佳参数:")
    lines.append(format_params(best_params))
    lines.append("")
    lines.append(f"{'Round':>5} {'Param':<30} {'Change':<16} {'Composite':>9} "
                 f"{'Ret%':>7} {'Sharpe':>6} {'WR%':>5} {'MDD%':>6} {'Trades':>6} Verdict")
    lines.append("-" * 120)

    for h in history:
        param = h.get("param", "-")
        old = h.get("old_val", "")
        new = h.get("new_val", "")
        change = f"{old}→{new}" if old != "" else "-"
        lines.append(
            f"{h['round']:>5} {str(param):<30} {change:<16} "
            f"{h['composite']:>8.1f} "
            f"{h.get('ret', 0):>+6.1f}% "
            f"{h.get('sharpe', 0):>5.1f} "
            f"{h.get('wr', 0):>4.0f}% "
            f"{h.get('mdd', 0):>5.1f}% "
            f"{h.get('trades', 0):>5} "
            f"{h.get('verdict', '')}"
        )

    with open(ITERATION_LOG, "w") as f:
        f.write("\n".join(lines))
    print(f"\n迭代日志已保存: {ITERATION_LOG}")
    print(f"最佳配置已保存: {BEST_CONFIG_FILE}")


if __name__ == "__main__":
    main()
