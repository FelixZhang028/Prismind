import assert from 'node:assert/strict'
import test from 'node:test'
import { accountMenu, allItems, groups, itemLabel, navigationItem, visibleGroups } from '../src/workspace/modules.js'

test('侧栏按研究顺序分组：① 研究 → ② 构建 → ③ 验证 → ④ 跟踪，最后是数据', () => {
  assert.deepEqual(groups.map((g) => [g.step ?? null, g.label, g.en]), [
    [1, '研究', 'Research'], [2, '构建', 'Build'], [3, '验证', 'Validate'], [4, '跟踪', 'Track'], [null, '数据', 'Data'],
  ])
  assert.equal(groups[0].items[0].key, 'event-study')                 // 和首页“一键试试”一致，最快出结果
  assert.equal(itemLabel('agent-lab'), '个股分析')
})

test('侧栏每一项都有一句白话说明', () => {
  for (const item of groups.flatMap((g) => g.items)) assert.ok(item.hint && item.hint.length <= 30, item.key)
})

test('普通用户的侧栏不放账户页面，也看不到数据运维；这些页面照样能直达', () => {
  const keys = visibleGroups(false).flatMap((g) => g.items.map((i) => i.key))
  for (const key of [...accountMenu, 'data-update']) assert.ok(!keys.includes(key), key)
  assert.ok(visibleGroups(true).flatMap((g) => g.items.map((i) => i.key)).includes('data-update'))
  for (const key of accountMenu) assert.ok(allItems.some((i) => i.key === key), key)
  assert.deepEqual(accountMenu.map(itemLabel), ['个人中心', '积分与打卡', '设置'])
})

test('页内的子页面在侧栏上点亮所属的那一项', () => {
  assert.equal(navigationItem('audit-report').key, 'audit-report')
  assert.equal(navigationItem('research').key, 'research')
  assert.equal(navigationItem('strategy-studio').key, 'strategy-hub')
  assert.equal(navigationItem('strategy-forensics').key, 'backtest-review')
  assert.equal(navigationItem('decision-center').key, 'agent-lab')
  assert.equal(navigationItem('settings'), undefined)
})
