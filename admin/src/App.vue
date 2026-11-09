<script setup>
import { onMounted, ref } from 'vue'
import DynamicBackground from './components/DynamicBackground.vue'
import AdminLogin from './components/AdminLogin.vue'
import AdminPage from './components/AdminPage.vue'
import { clearSession, getToken, logout, me } from './api.js'

const checking = ref(true)
const authed = ref(false)
const user = ref(null)   // 管理员或子管理员；子管理员只看到自己能用的页面

onMounted(async () => {
  if (!getToken()) {
    checking.value = false
    return
  }
  try {
    const u = await me()
    if (u.is_admin || u.is_sub_admin) {
      user.value = u
      authed.value = true
    }
    else clearSession()
  } catch {
    clearSession()
  }
  checking.value = false
})

function onLogin(u) {
  user.value = u
  authed.value = true
}
function onLogout() {
  logout()
  authed.value = false
}
</script>

<template>
  <div class="relative min-h-screen text-slate-200">
    <DynamicBackground />
    <div v-if="checking" class="flex min-h-screen items-center justify-center">
      <div class="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-indigo-400" />
    </div>
    <AdminLogin v-else-if="!authed" @logged-in="onLogin" />
    <AdminPage v-else :sub-admin="!user?.is_admin" @logout="onLogout" />
  </div>
</template>
