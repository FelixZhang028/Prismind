import assert from 'node:assert/strict'
import test from 'node:test'
import { TRY_QUESTIONS, tryHref } from '../src/tryQuestions.js'
import { decodePreset } from '../src/workspace/eventStudy.js'

test('每个问题的链接打开事件研究，条件原样带过去', () => {
  for (const question of TRY_QUESTIONS) {
    const url = new URL(tryHref(question), 'https://getprismind.com')
    assert.equal(url.pathname, '/app.html')
    assert.equal(url.searchParams.get('view'), 'event-study')
    assert.deepEqual(decodePreset(url.searchParams.get('preset')), question.conditions)
    assert.ok(question.zh.question && question.en.question)
  }
})

test('第一个问题和首页“开始使用”第一步用的是同一组条件', () => {
  const url = new URL(tryHref(TRY_QUESTIONS[0]), 'https://getprismind.com')
  assert.equal(url.searchParams.get('preset'), 'ret:20::<=:-20')   // 后端 home.FIRST_QUESTION_PRESET
})
