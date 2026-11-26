// 站内更新日志：随代码发版维护，按日期倒序展示给投资者。

export const CHANGELOG_STORAGE_KEY = 'fq_changelog_seen_id'

export const CHANGELOG_CATEGORIES = [
  { value: 'all', label: '全部' },
  { value: 'feat', label: '新增' },
  { value: 'fix', label: '修复' },
  { value: 'improve', label: '优化' },
  { value: 'data', label: '数据' },
]

export const CATEGORY_STYLE = {
  feat: { label: '新增', tone: 'border-indigo-400/30 bg-indigo-500/10 text-indigo-200' },
  fix: { label: '修复', tone: 'border-rose-400/30 bg-rose-500/10 text-rose-200' },
  improve: { label: '优化', tone: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200' },
  data: { label: '数据', tone: 'border-amber-400/30 bg-amber-500/10 text-amber-200' },
}

export const CHANGELOG_ENTRIES = [
  {
    id: '2026-11-25-backtest-confirm-save-as-new-and-instant-preview',
    date: '2026-11-25',
    title: '回测新增配置速览与一键恢复默认、修复「另存为新策略」反馈、规则预览即时刷新',
    items: [
      {
        category: 'improve',
        summary: '策略回测新增「本次回测配置」核对条与「恢复默认配置」按钮',
        detail: '提交回测前直接在按钮旁集中展示策略、股票范围、区间、持仓数、调仓频率与换手缓冲，并在沿用上次参数时给出提醒，支持一键恢复中证 800 历史成分股及默认参数。',
        action: { label: '去策略回测查看', view: 'backtest-review' },
      },
      {
        category: 'fix',
        summary: '修复「另存为新策略」后跳回空白新建表单且看不到成功提示的问题',
        detail: '另存为新策略后自动留在新策略编辑态，清晰展示成功卡片并自动滚动到可视区域；返回「我的策略」时同步展示列表刷新状态。',
        action: { label: '去我的策略体验', view: 'strategy-hub' },
      },
      {
        category: 'improve',
        summary: '规则策略周期与条件预览改为 0ms 本地即时刷新，并缓存后端交易日历预检',
        detail: '修改排序或条件周期时预览文案立刻更新，无需等待 1.5 秒后端往返；同时后端预检缓存交易日历元数据，显著缩短校验耗时。',
        action: { label: '去策略工坊体验', view: 'strategy-studio' },
      },
    ],
  },
  {
    id: '2026-11-25-default-csi800-edit-strategy-and-preview-sync',
    date: '2026-11-25',
    title: '回测默认使用中证800历史成分股、支持直接编辑已保存策略、修复规则周期预览同步',
    items: [
      {
        category: 'improve',
        summary: '新建回测默认选择「中证 800 历史成分股」并记住用户主动选择的股票范围',
        detail: '从新保存的规则策略点击「去回测」不再默认落到静态「当前股票池」，默认优先使用中证 800 历史成分股（未下载时回退沪深 300 历史成分股），从源头避免静态成分股前视偏差。',
        action: { label: '去策略回测查看', view: 'backtest-review' },
      },
      {
        category: 'feat',
        summary: '「我的策略」卡片新增「编辑」按钮，已保存策略与副本均可直接修改',
        detail: '无需反复复制重做，点击「编辑」即可在策略工坊修改原策略的名称、选股条件、排序指标、周期与交易纪律，支持直接「保存修改」或「另存为新策略」。',
        action: { label: '去我的策略体验', view: 'strategy-hub' },
      },
      {
        category: 'fix',
        summary: '修复规则策略排序/条件周期修改后预览偶尔不更新的问题',
        detail: '补全数字输入框 change 与 input 双事件同步，缩短预览防抖并显示同步提示，保存前自动等待最新校验完成，确保所见即所存。',
        action: { label: '去策略工坊查看', view: 'strategy-studio' },
      },
    ],
  },
  {
    id: '2026-11-25-rule-factors-and-quantile-filters',
    date: '2026-11-25',
    title: '规则策略支持引用因子库与 Alpha101，新增按分位剔除/保留过滤',
    items: [
      {
        category: 'feat',
        summary: '规则策略与条件选股现可引用全部内置因子库、Alpha101 与自定义因子',
        detail: '选股条件与排序不再局限于 13 项固定指标，支持按分组或关键词快速检索并选用因子库和 Alpha101 因子，每个调仓日在有效股票池截面上无前视偏差计算。',
        action: { label: '去策略工坊体验', view: 'strategy-studio' },
      },
      {
        category: 'feat',
        summary: '选股条件新增横截面分位过滤（剔除最差/最低/最高 %、保留前/后 %）',
        detail: '例如设置「剔除最差 20%（按因子方向）」即可按因子方向自动剔除尾部 20% 标的，方便对高 ROE、低波动、Alpha101 等因子做剔除测试与组合过滤，条件选股与策略回测口径完全一致。',
        action: { label: '去条件选股体验', view: 'stock-screen' },
      },
    ],
  },
  {
    id: '2026-11-25-research-progress-risk-reset-and-last-settings',
    date: '2026-11-25',
    title: '组合研究新增后台进度条与取消、风控一键恢复默认、回测跨会话沿用上次配置',
    items: [
      {
        category: 'feat',
        summary: '因子「组合研究」改为后台任务执行，支持实时阶段提示、步骤进度条与取消',
        detail: '长时间运行（8~10 分钟）的多因子组合研究不再阻塞页面，切换页面后继续在后台推进，实时展示当前阶段（训练期计算/中性化、权重拟合、测试期评估、BH-FDR 校正）与完成百分比，并可随时取消。',
        action: { label: '去因子研究体验', view: 'factor-lab' },
      },
      {
        category: 'improve',
        summary: '风控配置新增「恢复默认」按钮',
        detail: '一键将风控开关、总仓位、单股与单行业仓位上限、最大回撤线等恢复为平台默认值并保存。',
        action: { label: '去策略回测查看', view: 'backtest-review' },
      },
      {
        category: 'fix',
        summary: '跨会话自动沿用最近一次回测配置，「用此组合回测」不再重置参数',
        detail: '后端目录接口补充返回最近一次回测的日期、持仓、调仓频率、换手缓冲与费率/过滤设置，新浏览器或首次从因子研究跳入也能完整保留。',
        action: { label: '去因子研究查看', view: 'factor-lab' },
      },
    ],
  },
  {
    id: '2026-11-24-backtest-ux-dedupe-and-compare-annual',
    date: '2026-11-24',
    title: '回测自动保存风控与防重提交、参数持久化记忆、研究对比新增分年收益',
    items: [
      {
        category: 'improve',
        summary: '风控有未保存修改时，点击「运行回测」自动先保存风控再提交',
        detail: '无需再手动先点「保存风控配置」，若风控校验失败则自动展开面板并给出明确提示。',
        action: { label: '去策略回测体验', view: 'backtest-review' },
      },
      {
        category: 'improve',
        summary: '回测常用配置自动记忆，「用此组合回测」不再重置持仓/频率/成本与过滤',
        detail: '回测页的日期区间、持仓数、调仓频率、换手缓冲、交易成本与股票过滤会自动保存在本地；从因子研究点「用此组合回测」时保留当前参数，并提供一键切换至组合测试区间的按钮。',
        action: { label: '去因子研究体验', view: 'factor-lab' },
      },
      {
        category: 'feat',
        summary: '研究记录「对比所选」新增分年收益对比表',
        detail: '勾选 2~5 次回测对比时，除归一化净值曲线与总指标外，新增按自然年并排展示各次回测年度收益率的表格。',
        action: { label: '去研究记录查看', view: 'run-library' },
      },
      {
        category: 'fix',
        summary: '前后端双层防止相同配置回测重复提交',
        detail: '后端任务队列在排队/运行中对同用户完全相同配置的提交自动去重并返回已有任务，前端同步加锁防连点。',
        action: { label: '去策略回测查看', view: 'backtest-review' },
      },
    ],
  },
  {
    id: '2026-11-24-quarterly-rebalance-hold-buffer-dividend-fdr',
    date: '2026-11-24',
    title: '回测新增季度调仓与换手缓冲、内置股息率因子与单因子报告增强',
    items: [
      {
        category: 'feat',
        summary: '回测与策略全链路新增「每季」调仓频率，回测页开放「换手缓冲」配置',
        detail: '策略回测、策略工坊、条件选股、模拟账户与研究默认值均已支持每季调仓（按每季度最后一个交易日触发）；回测页可直接设置换手缓冲（如 +10 / +20 / +30 或自定义名次），已持股排名未跌出前 N+K 名时继续保留，显著降低低换手基本面策略的摩擦成本。',
        action: { label: '去策略回测体验', view: 'backtest-review' },
      },
      {
        category: 'feat',
        summary: '内置因子库正式加入「股息率（近一年）」因子',
        detail: '基于本地分红送配记录计算过去 365 天已除权现金分红合计除以当日未复权收盘价（已按送转拆股折算），无未来函数，可直接用于单因子评估、多因子合成与策略回测。',
        action: { label: '去因子库查看', view: 'factor-lab' },
      },
      {
        category: 'improve',
        summary: '单因子评估顶部卡片直接展示 BH-FDR q 值，风格相关性补充 250 日年化波动率',
        detail: '单因子报告「稳定性与显著性」卡片新增跨持有期 BH-FDR 多重检验 q 值与结论（兼容历史缓存报告）；「常见风格相关性速查」新增长期波动率（250 日年化波动率）一行，便于排查长周期低波暴露。',
        action: { label: '去因子评估查看', view: 'factor-lab' },
      },
    ],
  },
  {
    id: '2026-11-23-industry-constraints-backtest-costs',
    date: '2026-11-23',
    title: '行业仓位上限与因子回测中性化、回测费率与过滤规则透明可配',
    items: [
      {
        category: 'feat',
        summary: '风控设置新增「单一行业最大权重」并支持选股顺延递补',
        detail: '在「策略回测 → 风险设置」中可直接限制单一证监会行业仓位上限（如 25%）；选股时自动跳过已满额行业并按评分顺延递补其他行业股票，避免组合集中在银行等单一行业。',
        action: { label: '去策略回测体验', view: 'backtest-review' },
      },
      {
        category: 'feat',
        summary: '因子合成策略回测支持行业/市值中性化与行业内排名，且从因子研究一键带入',
        detail: '因子组合编辑器新增中性化下拉选项；在「因子研究 → 组合研究 / 多因子合成」中设置的中性化方式会随「用此组合回测」与「用此组合开模拟账户」自动带入。',
        action: { label: '去因子研究体验', view: 'factor-lab' },
      },
      {
        category: 'feat',
        summary: '回测页新增「交易成本与股票过滤」设置，结果页拆解佣金/印花税/滑点与实际费率',
        detail: '回测前可直接查看并调整佣金率、最低佣金、历史/固定印花税、滑点、排除 ST/停牌与最少上市天数（60/250天快捷切换）；回测结果与「交易与成本」页签完整列出三项成本明细、占资金比例与实际采用费率（含历史回测自动补全）。',
        action: { label: '去策略回测查看', view: 'backtest-review' },
      },
    ],
  },
  {
    id: '2026-11-23-neutralization-annual-compare',
    date: '2026-11-23',
    title: '组合研究中性化、回测分年收益与换手、研究记录对比优化',
    items: [
      {
        category: 'feat',
        summary: '因子组合研究（训练/测试模式）与多因子合成新增中性化选项',
        detail: '支持按行业、市值、行业+市值及行业内排名做点时中性化，训练期与测试期分别独立处理，避免未来数据泄露。',
        action: { label: '去因子研究体验', view: 'factor-lab' },
      },
      {
        category: 'feat',
        summary: '策略回测新增年化换手率指标卡与分年收益/换手明细表',
        detail: '回测概览与「交易与成本」页签展示单边年化换手率，并按自然年拆解策略收益、基准收益、超额收益、最大回撤、当年换手与成交笔数（历史回测打开即有）。',
        action: { label: '去策略回测查看', view: 'backtest-review' },
      },
      {
        category: 'fix',
        summary: '修复研究记录「对比所选」结果被藏在底部与错误一闪而过的问题',
        detail: '对比结果卡片与错误提示置顶并自动定位，对比折线图补齐横轴日期刻度与基线，对比表格同步展示年化换手率。',
        action: { label: '去研究记录体验', view: 'run-library' },
      },
    ],
  },
  {
    id: '2026-11-22-fdr-changelog',
    date: '2026-11-22',
    title: '因子多重检验校正（BH-FDR）与站内更新日志',
    items: [
      {
        category: 'feat',
        summary: '组合研究与单因子衰减表新增 Benjamini-Hochberg（BH-FDR）多重检验校正',
        detail: '在「因子研究 → 组合研究」测试期对比表与单因子「因子衰减」表中，新增 HAC t 值、HAC p 值、BH-FDR q 值和校正结论，并在顶部用白话提示过滤掉多少个“看似显著但可能碰运气”的候选因子。',
        action: { label: '去因子研究查看', view: 'factor-lab' },
      },
      {
        category: 'feat',
        summary: '新增站内更新日志页面与未读更新提示',
        detail: '每次核心功能上线、引擎修复或数据改进都会在这里集中记录，支持按分类筛选并一键直达体验。',
      },
    ],
  },
  {
    id: '2026-11-22-paper-factor-composite',
    date: '2026-11-22',
    title: '模拟账户支持多因子合成策略',
    items: [
      {
        category: 'feat',
        summary: '多因子合成组合可直接开设每日自动推进的模拟账户',
        detail: '支持在「模拟账户」直接配置因子组合（含正向/反向与自定义权重），也可从「因子研究」或「策略回测」结果页一键带入；创建时自动锁定自定义因子定义快照，日后改因子库不影响跟踪。',
        action: { label: '去模拟账户体验', view: 'paper-accounts' },
      },
    ],
  },
  {
    id: '2026-11-22-health-check-card',
    date: '2026-11-22',
    title: '回测概览白话体检卡与浅色主题按钮修复',
    items: [
      {
        category: 'feat',
        summary: '回测结果概览新增 4 项确定性白话体检',
        detail: '自动计算单股运气依赖（去掉最赚钱 1 只股还剩多少收益）、交易成本翻倍抗压、全期间行业集中度与大小盘偏向、以及最大回撤修复与空仓时长，3 秒排查常见回测陷阱。',
        action: { label: '去策略回测查看', view: 'backtest-review' },
      },
      {
        category: 'fix',
        summary: '修复可信度审计页浅色主题下切换按钮紫底黑字问题',
        detail: '将「平台回测 / 外部材料」切换栏统一为工作台胶囊分段样式，并确保纯色品牌按钮在浅色主题下保持白字高对比度。',
        action: { label: '去可信度审计查看', view: 'audit-report' },
      },
    ],
  },
  {
    id: '2026-11-22-factor-tradability-ux',
    date: '2026-11-22',
    title: '因子可交易性完善、回测因子方向编辑与数据说明优化',
    items: [
      {
        category: 'feat',
        summary: '因子评估支持涨跌停过滤与单边交易成本扣减',
        detail: '评估单因子时可勾选「排除涨跌停」并设置单边估算成本（bps），分组净值与多空收益差同步展示毛收益与扣成本后的净收益。',
        action: { label: '去因子研究体验', view: 'factor-lab' },
      },
      {
        category: 'fix',
        summary: '修复因子常见风格相关性缺失估值（EP/BP）的问题',
        detail: '修正扩展估值列加载覆盖 bug，风格相关性速查现已完整展示市值、波动率、换手率、动量及估值（EP/BP）重合度。',
      },
      {
        category: 'improve',
        summary: '策略回测页支持可视化编辑因子方向与一键切换历史成分股',
        detail: '「因子合成策略」回测不再需要手写 JSON，可直接添加因子并切换正向/反向；当静态股票池起点早于名单快照时，一键切换为无前视偏差的历史成分股。',
        action: { label: '去策略回测体验', view: 'backtest-review' },
      },
      {
        category: 'data',
        summary: '数据说明页新增「总股本与历史市值」覆盖率行并提速加载',
        detail: '公开展示历史市值样本覆盖情况，并为数据状态接口增加按文件修改时间自动失效的内存缓存，显著减少页面等待。',
        action: { label: '去数据说明查看', view: 'data-guide' },
      },
    ],
  },
  {
    id: '2026-11-21-factor-diagnostics',
    date: '2026-11-21',
    title: '因子深度诊断升级与逐因子方向自由设置',
    items: [
      {
        category: 'feat',
        summary: '单因子评估新增分年份 Rank IC、Newey-West HAC 显著性与风格相关性',
        detail: '拆解每一年份的 Rank IC 与正 IC 占比，以 HAC t/p 检验均值是否显著异于 0，并在 Rank IC 与多空收益差符号相反时自动给出白话口径说明。',
      },
      {
        category: 'feat',
        summary: '多因子合成与组合研究支持逐因子自由设置正向/反向',
        detail: '「越低越好」的因子（如低波动、低估值）可直接设为反向参与合成与权重优化。',
      },
    ],
  },
  {
    id: '2026-11-21-strategy-protection',
    date: '2026-11-21',
    title: '策略保护升级：止损止盈、持仓缓冲与大盘均线择时',
    items: [
      {
        category: 'feat',
        summary: '规则策略新增单股固定止损、移动止盈与全链路成交原因标签',
        detail: '成交记录与 K 线买卖标记现已明确注明每笔交易属于「规则调仓」「固定止损」「移动止盈」「大盘择时」还是「风控降仓」。',
        action: { label: '去我的策略配置', view: 'strategy-hub' },
      },
      {
        category: 'feat',
        summary: '新增排名持仓缓冲与大盘均线择时保护',
        detail: '支持对已持股放宽卖出排名阈值以降低无谓换手，并支持按基准指数均线（如沪深 300 MA20/60/120）在弱势期自动降仓或空仓。',
      },
    ],
  },
]

export function latestChangelogId() {
  return CHANGELOG_ENTRIES[0]?.id || ''
}

export function latestChangelogDate() {
  return CHANGELOG_ENTRIES[0]?.date || ''
}

export function filterChangelogEntries(category = 'all') {
  if (!category || category === 'all') return CHANGELOG_ENTRIES
  return CHANGELOG_ENTRIES
    .map((entry) => ({
      ...entry,
      items: entry.items.filter((item) => item.category === category),
    }))
    .filter((entry) => entry.items.length > 0)
}

export function readLastSeenChangelogId(storage = typeof localStorage !== 'undefined' ? localStorage : null) {
  try {
    return storage?.getItem(CHANGELOG_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function hasUnreadChangelog(lastSeenId) {
  const latest = latestChangelogId()
  return Boolean(latest) && lastSeenId !== latest
}

export function markChangelogSeen(storage = typeof localStorage !== 'undefined' ? localStorage : null) {
  const latest = latestChangelogId()
  if (!latest) return ''
  try {
    storage?.setItem(CHANGELOG_STORAGE_KEY, latest)
  } catch {
    // 隐私模式或禁用存储时忽略
  }
  return latest
}
