// 管理后台的两种身份：管理员（全部功能）和子管理员（只能管普通用户）。
// 这里只决定页面上显示什么；后端每个接口都会再检查一遍（dashboard/backend/app/routes/admin.py）。

// 子管理员能打开的页签。积分与兑换码、数据更新、系统设置只给管理员。
export const SUB_ADMIN_TABS = ['overview', 'users', 'feedback', 'invites', 'words', 'audit']

export function visibleTabs(tabs, subAdmin) {
  return subAdmin ? tabs.filter((t) => SUB_ADMIN_TABS.includes(t.key)) : tabs
}

// 用户列表里一行能做什么。subAdmin：现在登录的是子管理员。
// 子管理员只能改普通用户的昵称、停用或恢复普通用户；设为或取消子管理员只有管理员能做。
export function userActions(target, subAdmin) {
  const plain = !target.is_admin && !target.is_sub_admin
  if (subAdmin) return { rename: plain, toggleActive: plain, toggleSubAdmin: false }
  return {
    rename: true,
    toggleActive: !target.is_admin,
    // 停用的账户要先恢复才能设为子管理员；已经是子管理员的随时可以取消。
    toggleSubAdmin: !target.is_admin && (target.is_sub_admin || target.is_active),
  }
}

// “角色”一列的标签。停用的子管理员也标“已停用”：先看到不能登录这件事。
export function roleLabel(user) {
  if (user.is_admin) return { text: '管理员', tone: 'admin' }
  if (!user.is_active) return { text: '已停用', tone: 'disabled' }
  if (user.is_sub_admin) return { text: '子管理员', tone: 'sub' }
  return { text: '用户', tone: 'user' }
}
