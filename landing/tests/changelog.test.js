import assert from 'node:assert/strict'
import test from 'node:test'
import {
  CHANGELOG_ENTRIES,
  filterChangelogEntries,
  hasUnreadChangelog,
  latestChangelogDate,
  latestChangelogId,
  markChangelogSeen,
  readLastSeenChangelogId,
} from '../src/workspace/changelog.js'
import { allItems } from '../src/workspace/modules.js'

test('更新日志按日期倒序排列，且直达入口全部指向已注册页面', () => {
  assert.ok(CHANGELOG_ENTRIES.length >= 4)
  for (let i = 1; i < CHANGELOG_ENTRIES.length; i++) {
    assert.ok(CHANGELOG_ENTRIES[i - 1].date >= CHANGELOG_ENTRIES[i].date)
  }
  const validViews = new Set(allItems.map((item) => item.key))
  for (const entry of CHANGELOG_ENTRIES) {
    for (const item of entry.items) {
      if (item.action) assert.ok(validViews.has(item.action.view), `无效页面: ${item.action.view}`)
    }
  }
  assert.equal(latestChangelogId(), CHANGELOG_ENTRIES[0].id)
  assert.equal(latestChangelogDate(), CHANGELOG_ENTRIES[0].date)
})

test('按分类筛选更新日志且不返回空批次', () => {
  assert.equal(filterChangelogEntries('all').length, CHANGELOG_ENTRIES.length)
  const fixes = filterChangelogEntries('fix')
  assert.ok(fixes.length >= 1)
  for (const entry of fixes) {
    assert.ok(entry.items.length >= 1)
    assert.ok(entry.items.every((item) => item.category === 'fix'))
  }
  assert.deepEqual(filterChangelogEntries('nonexistent'), [])
})

test('未读提示与标记已读逻辑', () => {
  const store = new Map()
  const storage = {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, val) => store.set(key, val),
  }
  assert.equal(readLastSeenChangelogId(storage), '')
  assert.equal(hasUnreadChangelog(readLastSeenChangelogId(storage)), true)
  const seen = markChangelogSeen(storage)
  assert.equal(seen, latestChangelogId())
  assert.equal(hasUnreadChangelog(readLastSeenChangelogId(storage)), false)
})
