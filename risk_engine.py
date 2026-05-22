import os
import json
import tempfile
from quant_calc import calc_ma, calc_ma_slope, calc_volatility_z, calc_correlation, get_ret, z_to_position

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "macro_state.json")

try:
    import fcntl
except ImportError:
    fcntl = None

ASSETS = ("VOO", "QQQ", "GOLD", "COPX")
DEFAULT_POS = {asset: 0.0 for asset in ASSETS}

def load_state():
    default_state = {
        "pos": dict(DEFAULT_POS),
        "risk_comp": 0.0,
        "nav_real": 1.0,
        "hwm": 1.0,
        "regime": "NORMAL"
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                data = json.load(f)
                merged = {**default_state, **data}
                merged["pos"] = {**DEFAULT_POS, **(data.get("pos") or {})}
                return merged
        except Exception:
            pass
    return default_state

def save_state(state_dict):
    try:
        state_dir = os.path.dirname(STATE_FILE) or "."
        os.makedirs(state_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix="macro_state_", suffix=".json", dir=state_dir)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                json.dump(state_dict, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, STATE_FILE)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    except Exception:
        pass

def calc_risk_exposure(pos):
    return {
        "rate": pos["QQQ"] * 1.5 + pos["VOO"] * 0.8 + pos["GOLD"] * 1.0,
        "liquidity": pos["VOO"] * 1.0 + pos["QQQ"] * 1.5 + pos["COPX"] * 1.0,
        "china_macro": pos["COPX"] * 1.5
    }

def assess_data_quality(factors):
    required_assets = {
        "VOO": factors.get("voo_hist", []),
        "QQQ": factors.get("qqq_hist", []),
        "GOLD": factors.get("gold_hist", []),
        "COPX": factors.get("copx_hist", [])
    }
    required_signals = {
        "z_vix": factors.get("z_vix"),
        "z_move": factors.get("z_move"),
        "z_hy": factors.get("z_hy"),
        "z_realrate": factors.get("z_realrate"),
        "z_us10y": factors.get("z_us10y"),
        "z_dxy": factors.get("z_dxy"),
        "z_yc": factors.get("z_yc"),
        "z_t10": factors.get("z_t10")
    }

    issues = []
    for asset, history in required_assets.items():
        if len(history) < 210:
            issues.append(f"{asset}历史长度不足")
    for name, value in required_signals.items():
        if value is None:
            issues.append(f"{name}缺失")

    if len(issues) >= 5:
        scale = 0.0
    elif issues:
        scale = 0.5
    else:
        scale = 1.0

    return {
        "issues": issues,
        "degrade_scale": scale,
        "is_healthy": not issues
    }

def execute_quant_strategy(f):
    pos, const, action = {}, {}, {}
    state = load_state()
    prev_pos = {**DEFAULT_POS, **state.get("pos", {})}
    z_vix = f.get('z_vix') if f.get('z_vix') is not None else 0.0
    z_move = f.get('z_move') if f.get('z_move') is not None else 0.0
    z_hy = f.get('z_hy') if f.get('z_hy') is not None else 0.0
    z_realrate = f.get('z_realrate') if f.get('z_realrate') is not None else 0.0
    z_us10y = f.get('z_us10y') if f.get('z_us10y') is not None else 0.0
    z_dxy = f.get('z_dxy') if f.get('z_dxy') is not None else 0.0
    z_yc = f.get('z_yc') if f.get('z_yc') is not None else 0.0
    z_t10 = f.get('z_t10') if f.get('z_t10') is not None else 0.0
    liq_impulse = f.get('liq_impulse') if f.get('liq_impulse') is not None else 0.0

    # PnL & Drawdown Feedback
    port_ret = sum([
        prev_pos.get("VOO", 0) * get_ret(f.get('voo_hist')),
        prev_pos.get("QQQ", 0) * get_ret(f.get('qqq_hist')),
        prev_pos.get("GOLD", 0) * get_ret(f.get('gold_hist')),
        prev_pos.get("COPX", 0) * get_ret(f.get('copx_hist'))
    ])

    nav_real = state.get("nav_real", 1.0) * (1 + port_ret)
    hwm = max(state.get("hwm", 1.0), nav_real)
    drawdown = (hwm - nav_real) / hwm if hwm > 0 else 0.0

    # Risk Comp & Regime
    risk_comp_base = max(z_vix, z_move, z_hy) * 0.6 + sum([z_vix, z_move, z_hy]) / 3.0 * 0.4
    risk_comp_adj = risk_comp_base + 0.5 * max(0, f.get('z_vix_mom', 0.0))
    tail_shock_proxy = max(0, f.get('z_vix_mom', 0.0) + z_move)

    if risk_comp_adj > 2.5 or tail_shock_proxy > 4.0: current_regime = "CRISIS"
    elif drawdown > 0.05: current_regime = "DRAWDOWN"
    elif risk_comp_adj < 0.8 and drawdown < 0.02: current_regime = "RISK_ON"
    else: current_regime = "NORMAL"

    def risk_penalty(r):
        if r < 1.0: return r * 0.3
        elif r < 2.0: return r * 0.8
        else: return r * 1.5

    def rate_penalty(z):
        if z < 0: return z * 0.5
        elif z < 1.5: return z * 1.0
        else: return z * 2.0

    # Dynamic Weights
    if current_regime == "CRISIS": w_liq, w_risk, w_rate = 0.1, 2.0, 1.0
    elif current_regime == "DRAWDOWN": w_liq, w_risk, w_rate = 0.4, 1.2, 0.8
    else: w_liq, w_risk, w_rate = (0.3, 1.2, 0.8) if z_us10y > 1.5 else (0.8, 0.8, 0.4)

    usd_tightening = max(0, z_dxy)
    global_liq = liq_impulse - 0.2 * usd_tightening
    z_growth = -z_yc
    data_quality = assess_data_quality(f)

    # Base Signals
    z_voo = (global_liq * w_liq) - (risk_penalty(risk_comp_adj) * w_risk) - (rate_penalty(z_realrate) * 1.2)
    z_qqq = (global_liq * w_liq * 1.5) - (risk_penalty(risk_comp_adj) * w_risk * 1.2) - (rate_penalty(z_realrate) * 1.5)
    gold_penalty = rate_penalty(z_realrate) + 0.5 * max(0, f.get('z_realrate_mom', 0.0))
    z_gold = (-gold_penalty * 1.0 - z_dxy * 0.5 + z_t10 * 0.8 + risk_penalty(risk_comp_adj) * 0.3)
    cnh_stress = max(0, f.get('cnh_stress_pips', 0) / 300.0)
    z_copx = -(z_dxy * 0.6) + (global_liq * w_liq) - (risk_penalty(risk_comp_adj) * w_risk) - cnh_stress + (z_growth * 0.5)

    def apply_filters(price, history, base_z, vol_z_override):
        if price is None or not history or len(history) < 210: return 0.0, "数据不足"
        ma200 = calc_ma(history, 200)
        slope = calc_ma_slope(history, 50, 10)
        confidence = 1.0 / (1.0 + max(0, vol_z_override - 1.0) * 0.3)
        target = z_to_position(base_z) * confidence
        msgs = []
        if vol_z_override > 1.5: msgs.append(f"高波动折扣(x{confidence:.2f})")
        if price < ma200 and slope < 0: return 0.0, "🚨 破位向下"
        elif price >= ma200 and slope < 0: target = min(target, 0.3); msgs.append("⚠️ 均线背离")
        elif price < ma200 and slope > 0: target = min(target, 0.3); msgs.append("⚠️ 熊市反弹")
        elif price >= ma200 and slope > 0: target = min(target + 0.3, 1.0); msgs.append("🚀 趋势确认")
        return target, " | ".join(msgs) if msgs else "✅ 结构健康"

    target_pos = {}
    target_pos["VOO"], const["VOO"] = apply_filters(f['voo_cur'], f['voo_hist'], z_voo, calc_volatility_z(f.get('voo_hist', []), 20))
    target_pos["QQQ"], const["QQQ"] = apply_filters(f['qqq_cur'], f['qqq_hist'], z_qqq, calc_volatility_z(f.get('qqq_hist', []), 20))
    target_pos["GOLD"], const["GOLD"] = apply_filters(f['gold_cur'], f['gold_hist'], z_gold, calc_volatility_z(f.get('gold_hist', []), 20))
    target_pos["COPX"], const["COPX"] = apply_filters(f['copx_cur'], f['copx_hist'], z_copx, calc_volatility_z(f.get('copx_hist', []), 20))

    # Min-Max Risk Constraints
    limit_corr, limit_budget, limit_tail = 1.0, 1.0, 1.0
    corr_voo_qqq = calc_correlation(f.get('voo_hist', []), f.get('qqq_hist', []), window=60)
    effective_qqq = target_pos["QQQ"] * (1.7 if corr_voo_qqq >= 0.9 else (1.4 if corr_voo_qqq >= 0.85 else (1.2 if corr_voo_qqq >= 0.7 else 1.0)))
    if target_pos["VOO"] + effective_qqq + target_pos["COPX"] > 2.0:
        limit_corr = 2.0 / (target_pos["VOO"] + effective_qqq + target_pos["COPX"])
        const["PORTFOLIO"] = f"⚖️ 高度相关(ρ={corr_voo_qqq:.2f})挤压敞口"

    dd_penalty = max(0.5, 1.0 - drawdown * 4.0)
    RISK_BUDGET = {"rate": 1.5 * dd_penalty, "liquidity": 2.0 * dd_penalty, "china_macro": 1.0 * dd_penalty}
    pre_constraint_exposure = calc_risk_exposure(target_pos)

    triggered_budgets = []
    for k in RISK_BUDGET:
        if pre_constraint_exposure[k] > RISK_BUDGET[k]:
            overload = pre_constraint_exposure[k] / RISK_BUDGET[k]
            if (1.0 / overload) < limit_budget: limit_budget = 1.0 / overload
            triggered_budgets.append(k)
    if triggered_budgets:
        msg = f"🛡️ 触发[{','.join(triggered_budgets)}]极值预算控制"
        const["PORTFOLIO"] = msg if "PORTFOLIO" not in const else const["PORTFOLIO"] + f" | {msg}"

    if tail_shock_proxy > 4.0:
        limit_tail = 0.5
        const["GLOBAL"] = "🌪️ 侦测到未知极端宏观尾部，触发强制降维"
    elif risk_comp_adj > 2.5:
        limit_tail = 0.3
        const["GLOBAL"] = "🔥 已知系统性极度恐慌：全线强制降至 30% 防深 V"

    final_scale = min(limit_corr, limit_budget, limit_tail, data_quality["degrade_scale"])
    constrained_target_pos = {asset: target_pos[asset] * final_scale for asset in ASSETS}

    if data_quality["issues"]:
        const["GLOBAL"] = (
            f"⚠️ 数据质量降级：{','.join(data_quality['issues'][:4])}"
            if "GLOBAL" not in const
            else const["GLOBAL"] + f" | ⚠️ 数据质量降级:{','.join(data_quality['issues'][:4])}"
        )

    # Asymmetric Smoothing & Friction Cost
    daily_turnover = 0.0
    for asset in ASSETS:
        target, prev = constrained_target_pos[asset], prev_pos.get(asset, 0.0)
        if target == 0.0:
            pos[asset], action[asset] = 0.0, "🛑 止损清仓 (Clear)"
        else:
            alpha = 0.8 if current_regime == "CRISIS" and target < prev else (0.5 if target < prev else 0.2)
            actual_pos = prev + (target - prev) * alpha
            pos[asset] = actual_pos
            if abs(actual_pos - prev) < 0.02: action[asset] = "🔒 平滑微调 (Smooth)"
            elif actual_pos > prev: action[asset] = "🟢 顺势加仓 (Scale In)"
            else: action[asset] = "🔻 减持防守 (Scale Out)"
        daily_turnover += abs(pos[asset] - prev)

    friction_cost = daily_turnover * 0.0015
    nav_real = nav_real - friction_cost

    save_state({"pos": pos, "risk_comp": risk_comp_adj, "nav_real": nav_real, "hwm": hwm, "regime": current_regime})

    final_risk_exposure = calc_risk_exposure(pos)
    f['system_nav'], f['system_dd'], f['system_regime'] = nav_real, drawdown, current_regime
    f['dd_penalty'], f['friction_cost'] = dd_penalty, friction_cost
    f['risk_exposure'] = final_risk_exposure
    f['pre_constraint_risk_exposure'] = pre_constraint_exposure
    f['target_pos'] = target_pos
    f['constrained_target_pos'] = constrained_target_pos
    f['executed_pos'] = pos
    f['data_quality'] = data_quality

    return pos, action, risk_comp_adj, const, f
