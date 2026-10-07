// 云枢面板 前端入口
import router from './router.js'
import store from './store.js'
import api from './api.js'
import { hasPerm } from './util.js'

const { createApp, h } = window.Vue
const { ElMessage } = window.ElementPlus
const ElConfigProvider = window.ElementPlus.ElConfigProvider
const zhLocale = window.ElementPlusLocaleZhCn || null

// 注册全局图标
const icons = window.ElementPlusIconsVue || {}

const app = createApp({
  data: () => ({ store }),
  methods: { hasPerm },
  render() {
    const view = h(window.VueRouter.RouterView)
    return zhLocale ? h(ElConfigProvider, { locale: zhLocale }, [view]) : view
  },
})

// 图标全局组件
for (const [name, comp] of Object.entries(icons)) {
  app.component(name, comp)
}
// 常用图标别名
app.config.globalProperties.$icons = icons

// Element Plus 全量注册
app.use(window.ElementPlus, { size: 'default' })

// 全局属性：模板中的 store 引用编译为 _ctx.store，需要全局注册
app.config.globalProperties.store = store
app.config.globalProperties.hasPerm = hasPerm

// 全局工具
app.config.globalProperties.$fmt = (ts, p) => window.__util?.fmtTime(ts, p)

// 恢复会话
const token = localStorage.getItem('ops_token')
if (token) {
  api.get('/auth/me').then(res => {
    store.user = res.user
    store.perms = res.perms || []
    store.role = res.role
    store.panel = res.panel
  }).catch(() => {})
  // 加载授权状态（有权限时）
  api.get('/license/status').then(res => { store.license = res }).catch(() => {})
}

// 主题初始化
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem('ops_theme', theme)
  store.theme = theme
}
applyTheme(store.theme)
window.applyTheme = applyTheme
window.switchTheme = (t) => { applyTheme(t) }
window.store = store
window.hasPerm = hasPerm
window.__app = app
window.__router = router
import('./util.js').then(m => { window.__util = m })

app.use(router)
app.mount('#app')
