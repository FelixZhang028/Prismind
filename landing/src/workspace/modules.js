import { defineAsyncComponent } from 'vue'

// 首页为默认入口
export const overviewKey = 'overview'

// 侧栏按一次量化研究的顺序分组：① 研究 → ② 构建 → ③ 验证 → ④ 跟踪，最后是数据。
// 名称用专业说法；hint 是一句白话，鼠标停在侧栏这一项上时显示。
export const groups = [
  // 研究：看一类情况（事件研究）、按条件找股票（条件选股）、看一只股票（个股分析）、看行情。
  { label: '研究', en: 'Research', step: 1, items: [
    { key: 'event-study', label: '事件研究', hint: '某种情况出现以后，股票之后通常怎么走' },
    { key: 'stock-screen', label: '条件选股', hint: '按自己设的条件，从全市场筛出今天符合的股票' },
    { key: 'agent-lab', label: '个股分析', hint: '用平台数据整理一只股票，AI 解读每条都注明依据' },
    { key: 'market-chart', label: '行情图表', hint: 'K 线、均线、成交量和技术指标' },
  ] },
  { label: '构建', en: 'Build', step: 2, items: [
    { key: 'strategy-hub', label: '我的策略', hint: '不写代码建规则策略：从模板开始、用一句话描述或自己填' },
    { key: 'factor-lab', label: '因子研究', hint: '因子库、单因子评估和多因子组合' },
  ] },
  { label: '验证', en: 'Validate', step: 3, items: [
    { key: 'backtest-review', label: '策略回测', hint: '按 A 股真实规则和历史费用，在过去的行情里模拟交易' },
    { key: 'audit-report', label: '可信度审计', hint: '从六个维度检查一次回测的结果靠不靠得住', tag: '特色' },
    { key: 'research', label: '参数验证', hint: '比较几组候选参数，再用没参与挑选的数据检验' },
    { key: 'run-library', label: '研究记录', hint: '每次回测都保存在这里，可以重新打开或放在一起比较' },
  ] },
  { label: '跟踪', en: 'Track', step: 4, items: [
    { key: 'paper-accounts', label: '模拟账户', hint: '用之后每天的新行情继续模拟，看策略在样本外的表现' },
  ] },
  // 数据由平台统一更新：所有人查股票、管自己的股票池、看数据说明；数据运维只有管理员看得到。
  { label: '数据', en: 'Data', items: [
    { key: 'market-lookup', label: '股票查询', hint: '查一只股票的行情、估值和财报数据' },
    { key: 'universe', label: '股票池', hint: '管理自己关注的股票，回测和因子研究可以只用这些' },
    { key: 'data-guide', label: '数据说明', hint: '平台有哪些数据、更新到哪天、回测怎么用它们' },
    { key: 'data-update', label: '数据运维', hint: '下载和检查行情数据', admin: true },
  ] },
]

// 完整路由注册表保留页内入口，兼容官网、新手引导及已有直达链接。
const utilityItems = [
  // 文档问答与决策辅助暂不放进侧栏，旧链接仍能打开。研究经验在个股分析页面里管理。
  { key: 'knowledge-base', label: '投研知识库', parent: 'agent-lab' },
  { key: 'decision-center', label: '决策辅助', parent: 'agent-lab' },
  { key: 'data-management', label: '数据检查', parent: 'data-update', admin: true },
  { key: 'xtick-data', label: 'XTick 数据服务', parent: 'data-update', admin: true },
  { key: 'strategy-studio', label: '新建规则策略', parent: 'strategy-hub' },
  { key: 'strategy-forensics', label: '成交核查', parent: 'backtest-review' },
  // 账户相关的页面在右上角的头像菜单里，不占侧栏。
  { key: 'account', label: '个人中心' },
  { key: 'points', label: '积分与打卡' },
  { key: 'settings', label: '设置' },
]

// 右上角头像菜单：个人中心、积分、设置，最后是退出登录（由外壳处理）。
export const accountMenu = ['account', 'points', 'settings']
export const allItems = [{ key: overviewKey, label: '首页' }, ...groups.flatMap((g) =>
  g.items.flatMap((item) => item.children || [item])), ...utilityItems]

// 已合并页面的旧链接，直接落到现在包含该功能的页面。
const legacyViews = {
  'walk-forward': 'research', 'risk-management': 'backtest-review', 'nl-strategy': 'strategy-studio', 'prior-knowledge': 'agent-lab',
  // Python 策略已停用：旧链接落到我的策略。
  'custom-strategy': 'strategy-hub',
}
export function resolveView(key) {
  return legacyViews[key] || key
}

// 只有管理员能打开的页面；其他人打开旧链接（以前的“数据更新”“数据概览”）时落到数据说明。
export const adminViews = new Set(allItems.filter((item) => item.admin).map((item) => item.key))
export function viewFor(key, isAdmin) {
  const resolved = resolveView(key)
  return !isAdmin && adminViews.has(resolved) ? 'data-guide' : resolved
}

// 侧栏：普通用户看不到只给管理员的入口。
export function visibleGroups(isAdmin) {
  return groups.map((group) => ({ ...group, items: group.items.filter((item) => isAdmin || !item.admin) }))
}

export function navigationItem(key) {
  const parentKey = utilityItems.find((item) => item.key === key)?.parent || key
  return groups.flatMap((group) => group.items).find((item) =>
    item.key === parentKey || item.children?.some((child) => child.key === key))
}

export function itemLabel(key) {
  const found = allItems.find((i) => i.key === key)
  return found ? found.label : key
}

// 内容宽度与外壳独立：研究页为图表留空间，账户/设置保持紧凑。
const wideViews = new Set([
  'market-chart', 'event-study', 'stock-screen',
  'factor-lab', 'backtest-review', 'research', 'audit-report',
  'strategy-forensics', 'strategy-studio', 'run-library', 'paper-accounts',
])
const compactViews = new Set(['account', 'settings', 'points'])

export function contentLayout(key) {
  if (compactViews.has(key)) return 'compact'
  return wideViews.has(key) ? 'wide' : 'standard'
}

const investmentKnowledgeView = defineAsyncComponent(() => import('./views/InvestmentKnowledgeView.vue'))
export const views = {
  [overviewKey]: defineAsyncComponent(() => import('./views/OverviewView.vue')),
  'market-chart': defineAsyncComponent(() => import('./views/MarketChartView.vue')),
  'strategy-hub': defineAsyncComponent(() => import('./views/StrategyHubView.vue')),
  'strategy-studio': defineAsyncComponent(() => import('./views/StrategyStudioView.vue')),
  'factor-lab': defineAsyncComponent(() => import('./views/FactorLabView.vue')),
  'agent-lab': defineAsyncComponent(() => import('./views/AgentLabView.vue')),
  'event-study': defineAsyncComponent(() => import('./views/EventStudyView.vue')),
  'stock-screen': defineAsyncComponent(() => import('./views/StockScreenView.vue')),
  'decision-center': defineAsyncComponent(() => import('./views/DecisionCenterView.vue')),
  'knowledge-base': investmentKnowledgeView,
  'backtest-review': defineAsyncComponent(() => import('./views/BacktestReviewView.vue')),
  'audit-report': defineAsyncComponent(() => import('./views/AuditReportView.vue')),
  'strategy-forensics': defineAsyncComponent(() => import('./views/StrategyForensicsView.vue')),
  research: defineAsyncComponent(() => import('./views/ResearchView.vue')),
  'run-library': defineAsyncComponent(() => import('./views/RunLibraryView.vue')),
  'paper-accounts': defineAsyncComponent(() => import('./views/PaperAccountsView.vue')),
  'data-guide': defineAsyncComponent(() => import('./views/DataGuideView.vue')),
  'market-lookup': defineAsyncComponent(() => import('./views/MarketLookupView.vue')),
  'data-update': defineAsyncComponent(() => import('./views/DataUpdateView.vue')),
  'data-management': defineAsyncComponent(() => import('./views/DataManagementView.vue')),
  'xtick-data': defineAsyncComponent(() => import('./views/XtickDataView.vue')),
  universe: defineAsyncComponent(() => import('./views/UniverseView.vue')),
  settings: defineAsyncComponent(() => import('./views/SettingsView.vue')),
  account: defineAsyncComponent(() => import('./views/AccountView.vue')),
  points: defineAsyncComponent(() => import('./views/PointsView.vue')),
}
