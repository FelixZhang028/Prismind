import test from 'node:test'
import assert from 'node:assert/strict'
import { formatCoveragePct, neutralizationCoverageSummary } from '../src/workspace/neutralizationPresentation.js'

test('formatCoveragePct handles valid ratios and missing values', () => {
  assert.equal(formatCoveragePct(0.2134), '21.3%')
  assert.equal(formatCoveragePct(1), '100.0%')
  assert.equal(formatCoveragePct(null), '—')
  assert.equal(formatCoveragePct(undefined), '—')
})

test('neutralizationCoverageSummary builds warning, columns and low-year flags for both mode', () => {
  assert.equal(neutralizationCoverageSummary(null), null)
  const summary = neutralizationCoverageSummary({
    mode: 'both',
    requested_start: '2016-01-01',
    requested_end: '2026-11-09',
    effective_start: '2025-10-13',
    effective_end: '2026-11-09',
    total_days: 2600,
    effective_days: 260,
    skipped_days: 4,
    industry_coverage: 0.999,
    size_coverage: 0.213,
    joint_coverage: 0.213,
    insufficient: true,
    warning: '中性化覆盖不足：实际有效日期为 2025-10-13 至 2026-11-09。',
    yearly: [
      { year: 2024, samples: 190000, industry_coverage: 1, size_coverage: 0, joint_coverage: 0, total_days: 242, effective_days: 0, skipped_days: 0 },
      { year: 2025, samples: 190000, industry_coverage: 1, size_coverage: 0.25, joint_coverage: 0.25, total_days: 242, effective_days: 55, skipped_days: 4 },
      { year: 2026, samples: 160000, industry_coverage: 1, size_coverage: 0.98, joint_coverage: 0.98, total_days: 205, effective_days: 205, skipped_days: 0 },
    ],
  })
  assert.equal(summary.insufficient, true)
  assert.equal(summary.effectiveRange, '2025-10-13 至 2026-11-09')
  assert.deepEqual(summary.columns.map((c) => c.key), ['year', 'industry', 'size', 'joint', 'days', 'samples'])
  assert.equal(summary.rows[0].year, '2024（不足）')
  assert.equal(summary.rows[0].low, true)
  assert.equal(summary.rows[2].year, '2026')
  assert.equal(summary.rows[2].low, false)
  assert.ok(summary.metrics.some((m) => m.label === '样本不足跳过' && m.value === '4 天'))
})

test('neutralizationCoverageSummary omits unused exposure column for single-exposure modes', () => {
  const ind = neutralizationCoverageSummary({
    mode: 'industry',
    requested_start: '2025-01-01',
    requested_end: '2025-12-31',
    effective_start: '2025-01-02',
    effective_end: '2025-12-31',
    total_days: 240,
    effective_days: 240,
    skipped_days: 0,
    industry_coverage: 1,
    size_coverage: null,
    joint_coverage: 1,
    insufficient: false,
    warning: '',
    yearly: [{ year: 2025, samples: 72000, industry_coverage: 1, size_coverage: null, joint_coverage: 1, total_days: 240, effective_days: 240, skipped_days: 0 }],
  })
  assert.deepEqual(ind.columns.map((c) => c.key), ['year', 'industry', 'joint', 'days', 'samples'])
  assert.equal(ind.insufficient, false)
  assert.ok(!ind.metrics.some((m) => m.label === '样本不足跳过'))

  const size = neutralizationCoverageSummary({
    mode: 'size',
    requested_start: '2025-01-01',
    requested_end: '2025-12-31',
    effective_start: '2025-01-02',
    effective_end: '2025-12-31',
    total_days: 240,
    effective_days: 240,
    skipped_days: 0,
    industry_coverage: null,
    size_coverage: 0.99,
    joint_coverage: 0.99,
    insufficient: false,
    warning: '',
    yearly: [{ year: 2025, samples: 72000, industry_coverage: null, size_coverage: 0.99, joint_coverage: 0.99, total_days: 240, effective_days: 240, skipped_days: 0 }],
  })
  assert.deepEqual(size.columns.map((c) => c.key), ['year', 'size', 'joint', 'days', 'samples'])
})
