import assert from 'node:assert/strict'
import test from 'node:test'
import { loginUrl, nextFrom, safeNext } from '../src/authNext.js'

test('只接受本站功能台的地址，其他一律回功能台首页', () => {
  assert.equal(safeNext('/app.html?view=event-study&preset=ret%3A20'), '/app.html?view=event-study&preset=ret%3A20')
  assert.equal(safeNext('/app.html'), '/app.html')
  for (const bad of ['', null, 'https://evil.example/app.html', '//evil.example', '/app.html//evil', '/app.htmlx', '/auth.html', '/app.html?a=\\b'])
    assert.equal(safeNext(bad), '/app.html')
})

test('没登录时带上现在这一页去登录，登录后回来', () => {
  const url = loginUrl({ pathname: '/app.html', search: '?view=event-study&preset=ret%3A20%3A%3A%3C%3D%3A-20' })
  assert.equal(url, '/auth.html?next=%2Fapp.html%3Fview%3Devent-study%26preset%3Dret%253A20%253A%253A%253C%253D%253A-20')
  assert.equal(nextFrom(url.slice('/auth.html'.length)), '/app.html?view=event-study&preset=ret%3A20%3A%3A%3C%3D%3A-20')
  assert.equal(loginUrl({ pathname: '/app.html', search: '' }), '/auth.html')
  assert.equal(nextFrom(''), '/app.html')
  assert.equal(nextFrom('?next=https%3A%2F%2Fevil.example'), '/app.html')
})
