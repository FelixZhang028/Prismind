import test from 'node:test'
import assert from 'node:assert/strict'
import { roleLabel, userActions, visibleTabs } from '../src/roles.js'

const tabs = ['overview', 'users', 'feedback', 'invites', 'words', 'points', 'data', 'settings', 'audit'].map((key) => ({ key }))
const admin = { is_admin: true, is_sub_admin: false, is_active: true }
const sub = { is_admin: false, is_sub_admin: true, is_active: true }
const user = { is_admin: false, is_sub_admin: false, is_active: true }

test('子管理员看不到积分、数据更新和系统设置', () => {
  assert.deepEqual(visibleTabs(tabs, false).map((t) => t.key), tabs.map((t) => t.key))
  assert.deepEqual(visibleTabs(tabs, true).map((t) => t.key), ['overview', 'users', 'feedback', 'invites', 'words', 'audit'])
})

test('管理员：能设为或取消子管理员，停用的账户要先恢复', () => {
  assert.deepEqual(userActions(user, false), { rename: true, toggleActive: true, toggleSubAdmin: true })
  assert.deepEqual(userActions(sub, false), { rename: true, toggleActive: true, toggleSubAdmin: true })
  assert.deepEqual(userActions(admin, false), { rename: true, toggleActive: false, toggleSubAdmin: false })
  assert.equal(userActions({ ...user, is_active: false }, false).toggleSubAdmin, false)
  assert.equal(userActions({ ...sub, is_active: false }, false).toggleSubAdmin, true)
})

test('子管理员：只能管普通用户，不能设子管理员', () => {
  assert.deepEqual(userActions(user, true), { rename: true, toggleActive: true, toggleSubAdmin: false })
  for (const target of [admin, sub]) {
    assert.deepEqual(userActions(target, true), { rename: false, toggleActive: false, toggleSubAdmin: false })
  }
})

test('角色标签', () => {
  assert.equal(roleLabel(admin).text, '管理员')
  assert.equal(roleLabel(sub).text, '子管理员')
  assert.equal(roleLabel(user).text, '用户')
  assert.equal(roleLabel({ ...sub, is_active: false }).text, '已停用')
})
