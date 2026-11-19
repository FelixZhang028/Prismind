// 因子评估「中性化覆盖率」的格式化与警告展示模型。

export function formatCoveragePct(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

export function neutralizationCoverageSummary(coverage) {
  if (!coverage) return null
  const hasIndustry = coverage.industry_coverage != null
  const hasSize = coverage.size_coverage != null
  const effectiveRange = coverage.effective_start && coverage.effective_end
    ? `${coverage.effective_start} 至 ${coverage.effective_end}`
    : '—'
  const requestedRange = coverage.requested_start && coverage.requested_end
    ? `${coverage.requested_start} 至 ${coverage.requested_end}`
    : '—'

  const metrics = [
    { label: '实际有效日期', value: effectiveRange },
    { label: '有效交易日', value: `${coverage.effective_days ?? 0} / ${coverage.total_days ?? 0}` },
  ]
  if (hasIndustry) metrics.push({ label: '行业覆盖率', value: formatCoveragePct(coverage.industry_coverage) })
  if (hasSize) metrics.push({ label: '市值覆盖率', value: formatCoveragePct(coverage.size_coverage) })
  metrics.push({ label: '联合覆盖率', value: formatCoveragePct(coverage.joint_coverage) })
  if ((coverage.skipped_days ?? 0) > 0) {
    metrics.push({ label: '样本不足跳过', value: `${coverage.skipped_days} 天` })
  }

  const columns = [{ key: 'year', label: '年份' }]
  if (hasIndustry) columns.push({ key: 'industry', label: '行业覆盖率', align: 'right' })
  if (hasSize) columns.push({ key: 'size', label: '市值覆盖率', align: 'right' })
  columns.push(
    { key: 'joint', label: '联合覆盖率', align: 'right' },
    { key: 'days', label: '有效 / 总交易日', align: 'right' },
    { key: 'samples', label: '样本数', align: 'right' },
  )

  const rows = (coverage.yearly || []).map((row) => {
    const low = row.effective_days === 0 || Number(row.joint_coverage) < 0.5
    return {
      year: `${row.year}${low ? '（不足）' : ''}`,
      industry: formatCoveragePct(row.industry_coverage),
      size: formatCoveragePct(row.size_coverage),
      joint: formatCoveragePct(row.joint_coverage),
      days: `${row.effective_days} / ${row.total_days}`,
      samples: String(row.samples ?? 0),
      low,
    }
  })

  return {
    effectiveRange,
    requestedRange,
    jointText: formatCoveragePct(coverage.joint_coverage),
    insufficient: Boolean(coverage.insufficient),
    warning: coverage.warning || '',
    metrics,
    columns,
    rows,
  }
}
