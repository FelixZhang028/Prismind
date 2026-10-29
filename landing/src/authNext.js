// 没登录时打开功能台的某个页面（例如首页“一键试试”的链接）：先去登录，登录或注册后回到原来那一页。
// 只接受本站功能台的地址，免得登录页被人拿来跳到别的网站。
const HOME = '/app.html'

export function safeNext(raw) {
  const next = String(raw || '')
  if (!next.startsWith(HOME) || next.includes('//') || next.includes('\\')) return HOME
  const rest = next.slice(HOME.length)
  return rest === '' || rest.startsWith('?') || rest.startsWith('#') ? next : HOME
}

// 功能台发现没登录时去的登录页地址，带上现在这一页。
export function loginUrl(location) {
  const here = `${location.pathname || ''}${location.search || ''}`
  const next = safeNext(here)
  return next === HOME ? '/auth.html' : `/auth.html?next=${encodeURIComponent(next)}`
}

// 登录页读出登录以后要去的地方。
export function nextFrom(search) {
  return safeNext(new URLSearchParams(search || '').get('next'))
}
