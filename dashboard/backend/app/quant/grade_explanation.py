"""Explain the effective credibility grade using the audit's own findings."""
from quant_platform.backtest.credibility import HEADLINES, CredibilityReport

ACTIONS = {
    "data_integrity": "检查行情和交易状态覆盖，补齐缺失数据后重跑。",
    "lookahead_guard": "核对信号、成交和复权数据的可用日期，修正后重跑。",
    "sample_bias": "用当时的指数成分股或另选一个样本外区间验证。",
    "cost_realism": "核对手续费、印花税和滑点设置，按实际成本重跑。",
    "capacity": "检查订单规模与成交量，按合理的参与率验证。",
    "selection_bias": "用未参加调参的区间做样本外或滚动验证，并保存筛选记录。",
}

FINDING_ACTIONS = {
    "FIXED_UNIVERSE": "重跑时可选「沪深300历史成分股」等随日期变化的股票范围，减少固定名单带来的选股偏差。",
    "IN_SAMPLE_ONLY": "留出一段没参与选策略或调参的日期，做样本外回测。",
}

GRADE_RULES = {
    "A": "无警告，适用的审计检查通过。",
    "B": "有一项需要复核的警告。",
    "C": "有至少两项不同的警告，同一问题重复出现只计一次。",
    "D": "存在错误级问题，或缺少判断绩效是否可靠的证据。",
}


def grade_explanation(result: dict, report: CredibilityReport | None = None) -> dict:
    grade = report.grade if report else None
    headline = report.headline if report else None
    reasons = []
    seen = set()
    if report:
        for dimension in report.dimensions:
            for finding in dimension.findings:
                if finding.severity not in {"warn", "fail"}:
                    continue
                key = ("code", finding.code) if finding.code else ("message", finding.message)
                if key in seen:
                    continue
                seen.add(key)
                reasons.append({
                    "title": dimension.title, "severity": finding.severity,
                    "message": finding.message, "action": FINDING_ACTIONS.get(finding.code) or ACTIONS.get(dimension.key),
                })
    if result.get("legacy_unverified"):
        grade, headline = "D", "该回测缺少可复核的有效性证据。"
        reasons.insert(0, {"title": "历史记录", "severity": "fail", "message": headline,
                           "action": "用当前版本重新回测，生成新的审计证据。"})
    elif not result.get("metrics_reliable") or (grade == "A" and result.get("validity_status") == "WARNING"):
        reliable = result.get("metrics_reliable")
        grade = "B" if reliable else "D"
        headline = "存在需要复核的有效性警告。" if reliable else "有效性证据不足或存在错误，绩效指标不可用于策略评价。"
        if not reasons:
            issues = result.get("validity_issues") or []
            reasons = [{"title": "有效性", "severity": "warn" if reliable else "fail",
                        "message": message, "action": "核对相关数据或回测设置后重跑。"}
                       for message in dict.fromkeys(i.get("message") for i in issues if isinstance(i, dict)) if message]
        if not reasons:
            reasons.append({"title": "有效性", "severity": "warn" if reliable else "fail",
                            "message": headline, "action": "核对本次回测的有效性说明。"})
    reasons.sort(key=lambda reason: reason["severity"] != "fail")
    return {"grade": grade, "headline": headline or HEADLINES.get(grade), "grade_reasons": reasons,
            "grade_rule": GRADE_RULES.get(grade)}
