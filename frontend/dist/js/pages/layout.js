// Created by 小杜 on 2026/08

// 主布局：侧边菜单 + 顶栏
import api from '../api.js'
import store from '../store.js'
import { hasPerm } from '../util.js'

const { ElMessage, ElMessageBox } = window.ElementPlus

export default {
  data() {
    return {
      groups: [
        {
          title: '概览',
          items: [
            { path: '/dashboard', label: '仪表盘', icon: 'Odometer', perm: 'dashboard:view' },
            { path: '/monitor', label: '实时监控', icon: 'TrendCharts', perm: 'monitor:view' },
            { path: '/ai', label: 'AI 助手', icon: 'MagicStick', perm: 'ai:use' },
            { path: '/health', label: '体检中心', icon: 'FirstAidKit', perm: 'security:view' },
          ],
        },
        {
          title: '网站',
          items: [
            { path: '/websites', label: '网站管理', icon: 'Document', perm: 'websites:view' },
          ],
        },
        {
          title: '数据库',
          items: [
            { path: '/databases', label: '数据库管理', icon: 'Coin', perm: 'databases:view' },
          ],
        },
        {
          title: '应用',
          items: [
            { path: '/software', label: '软件商店', icon: 'Shop', perm: 'software:view' },
            { path: '/docker', label: 'Docker 管理', icon: 'Box', perm: 'docker:view' },
          ],
        },
        {
          title: '运维',
          items: [
            { path: '/files', label: '文件管理', icon: 'FolderOpened', perm: 'files:read' },
            { path: '/terminal', label: 'Web 终端', icon: 'Monitor', perm: 'terminal:use' },
            { path: '/processes', label: '进程管理', icon: 'Cpu', perm: 'processes:view' },
            { path: '/services', label: '服务管理', icon: 'SetUp', perm: 'services:view' },
            { path: '/cron', label: '计划任务', icon: 'AlarmClock', perm: 'cron:view' },
            { path: '/guardian', label: '进程守护', icon: 'Switch', perm: 'processes:view' },
            { path: '/ftp', label: 'FTP 管理', icon: 'Upload', perm: 'ftp:view' },
            { path: '/toolbox', label: '工具箱', icon: 'Suitcase', perm: 'system:view' },
          ],
        },
        {
          title: '安全',
          items: [
            { path: '/firewall', label: '防火墙', icon: 'Lock', perm: 'firewall:view' },
            { path: '/waf', label: 'WAF 防护 · VIP', icon: 'Umbrella', perm: 'waf:view' },
            { path: '/security', label: '安全中心', icon: 'Shield', perm: 'security:view' },
            { path: '/ssh', label: 'SSH 安全', icon: 'Monitor', perm: 'ssh:view' },
            { path: '/backups', label: '备份中心', icon: 'FolderChecked', perm: 'backups:view' },
            { path: '/logs', label: '日志管理', icon: 'Tickets', perm: 'logs:view' },
          ],
        },
        {
          title: '系统',
          items: [
            { path: '/network', label: '网络工具', icon: 'Position', perm: 'network:view' },
            { path: '/dns', label: 'DNS 工具', icon: 'Connection', perm: 'dns:view' },
            { path: '/users', label: '用户管理', icon: 'UserFilled', perm: 'users:view' },
            { path: '/settings', label: '面板设置', icon: 'Setting', perm: 'settings:view' },
          ],
        },
      ],
      pwdDialog: { show: false, old: '', n1: '', n2: '' },
      fa2Dialog: { show: false, secret: '', otpauth: '', code: '', enabled: !!store.user?.two_fa },
      // 二级菜单：默认仅展开「概览」，其余分组折叠（侧栏不再过长）
      openGroups: ['概览'],
      // 侧栏折叠：状态持久化到 localStorage（rt_sidebar=1 表示折叠）
      sidebarCollapsed: localStorage.getItem('rt_sidebar') === '1',
    }
  },
  computed: {
    title() { return this.$route.meta?.title || '' },
    crumbs() {
      // 面包屑：当前页所在分组 + 页面名（分组可点击，跳到该组第一个菜单）
      const p = this.$route.path
      for (const g of this.groups) {
        const it = g.items.find(i => i.path === p)
        if (it) return [{ label: g.title, path: g.items[0].path }, { label: it.label, path: p }]
      }
      return [{ label: this.$route.meta?.title || '仪表盘', path: '/dashboard' }]
    },
    licenseChip() {
      const l = store.license
      if (!l) return '绑定查询中'
      const map = { bound: '已绑定', unbound: '未绑定', mismatch: '需重新绑定',
                    rejected: '绑定失效', expired_offline: '离线超期' }
      return map[l.mode] || l.mode
    },
    hiddenMenus() {
      // 设置 → 隐藏选项 里勾选隐藏的菜单路径
      try {
        const raw = store.panel?.settings?.hidden_menus
        if (typeof raw === 'string' && raw) return JSON.parse(raw)
        if (Array.isArray(raw)) return raw
      } catch (e) {}
      return []
    },
    visibleGroups() {
      return this.groups
        .map(g => ({ ...g, items: g.items.filter(i => hasPerm(i.perm) && !this.hiddenMenus.includes(i.path)) }))
        .filter(g => g.items.length > 0)
    },
  },
  methods: {
    hasPerm,
    isOpen(title) {
      // 若当前路由属于该组，自动展开（路由跳转时组保持可见）
      const g = this.groups.find(x => x.title === title)
      if (g && g.items.some(i => i.path === this.$route.path)) return true
      return this.openGroups.includes(title)
    },
    toggleGroup(title) {
      const i = this.openGroups.indexOf(title)
      if (i >= 0) this.openGroups.splice(i, 1)
      else this.openGroups.push(title)
    },
    visibleItems(group) {
      return group.items.filter(i => hasPerm(i.perm))
    },
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
      try { localStorage.setItem('rt_sidebar', this.sidebarCollapsed ? '1' : '0') } catch (e) {}
    },
    switchTheme(key) {
      window.applyTheme(key)
      ElMessage.success('已切换为' + (key === 'lightgold' ? '白金' : key === 'light' ? '亮色' : '银黑') + '主题')
    },
    goto(path) { this.$router.push(path) },
    async logout() {
      try { await api.post('/auth/logout') } catch (e) {}
      localStorage.removeItem('ops_token')
      this.$router.push('/login')
    },
    changePwd() { this.pwdDialog.show = true },
    async submitPwd() {
      if (this.pwdDialog.n1 !== this.pwdDialog.n2) return ElMessage.warning('两次输入不一致')
      if (this.pwdDialog.n1.length < 8) return ElMessage.warning('密码至少 8 位')
      try {
        await api.put('/auth/password', { old_password: this.pwdDialog.old, new_password: this.pwdDialog.n1 })
        ElMessage.success('密码已修改')
        this.pwdDialog = { show: false, old: '', n1: '', n2: '' }
      } catch (e) {}
    },
    async open2fa() {
      this.fa2Dialog.show = true
      this.fa2Dialog.enabled = !!store.user?.two_fa
      if (!store.user?.two_fa) {
        try {
          const r = await api.post('/auth/2fa/setup')
          this.fa2Dialog.secret = r.secret
          this.fa2Dialog.otpauth = r.otpauth
        } catch (e) {}
      }
    },
    async enable2fa() {
      try {
        await api.post('/auth/2fa/enable', { secret: this.fa2Dialog.secret, code: this.fa2Dialog.code })
        ElMessage.success('两步验证已启用')
        store.user.two_fa = 1
        this.fa2Dialog.show = false
      } catch (e) {}
    },
    async disable2fa() {
      try {
        await api.post('/auth/2fa/disable', { code: this.fa2Dialog.code })
        ElMessage.success('两步验证已关闭')
        store.user.two_fa = 0
        this.fa2Dialog.show = false
      } catch (e) {}
    },
  },
  render: (function(){ const { createElementVNode: _createElementVNode, toDisplayString: _toDisplayString, renderList: _renderList, Fragment: _Fragment, openBlock: _openBlock, createElementBlock: _createElementBlock, resolveDynamicComponent: _resolveDynamicComponent, createBlock: _createBlock, resolveComponent: _resolveComponent, withCtx: _withCtx, createVNode: _createVNode, normalizeClass: _normalizeClass, createCommentVNode: _createCommentVNode, createTextVNode: _createTextVNode, Transition: _Transition } = Vue

const _hoisted_1 = { class: "op-layout" }
const _hoisted_2 = { class: "op-sidebar" }
const _hoisted_3 = { class: "op-logo" }
const _hoisted_4 = { class: "gold-text" }
const _hoisted_5 = { class: "op-menu" }
const _hoisted_6 = { class: "menu-group-title" }
const _hoisted_7 = ["onClick"]
const _hoisted_8 = { class: "op-main" }
const _hoisted_9 = { class: "op-topbar" }
const _hoisted_10 = { class: "breadcrumb" }
const _hoisted_11 = { class: "right" }
const _hoisted_12 = { style: {"cursor":"pointer","color":"var(--text-regular)"} }
const _hoisted_13 = { style: {"cursor":"pointer","display":"flex","align-items":"center","gap":"6px","color":"var(--text-primary)"} }
const _hoisted_14 = { class: "op-content" }
const _hoisted_15 = { class: "dialog-footer" }
const _hoisted_16 = {
  class: "mono gold-text",
  style: {"user-select":"all"}
}
const _hoisted_17 = { style: {"font-size":"12px","color":"var(--text-secondary)","word-break":"break-all"} }
const _hoisted_18 = { class: "dialog-footer" }

return function render(_ctx, _cache) {
  const _component_el_icon = _resolveComponent("el-icon")
  const _component_el_tooltip = _resolveComponent("el-tooltip")
  const _component_Brush = _resolveComponent("Brush")
  const _component_Refresh = _resolveComponent("Refresh")
  const _component_el_dropdown_item = _resolveComponent("el-dropdown-item")
  const _component_el_dropdown_menu = _resolveComponent("el-dropdown-menu")
  const _component_el_dropdown = _resolveComponent("el-dropdown")
  const _component_el_avatar = _resolveComponent("el-avatar")
  const _component_Key = _resolveComponent("Key")
  const _component_Cellphone = _resolveComponent("Cellphone")
  const _component_SwitchButton = _resolveComponent("SwitchButton")
  const _component_router_view = _resolveComponent("router-view")
  const _component_el_input = _resolveComponent("el-input")
  const _component_el_form_item = _resolveComponent("el-form-item")
  const _component_el_form = _resolveComponent("el-form")
  const _component_el_button = _resolveComponent("el-button")
  const _component_el_dialog = _resolveComponent("el-dialog")
  const _component_el_alert = _resolveComponent("el-alert")

  return (_openBlock(), _createElementBlock("div", {
    class: _normalizeClass(["op-layout", { collapsed: _ctx.sidebarCollapsed }])
  }, [
    _createElementVNode("aside", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _cache[12] || (_cache[12] = _createElementVNode("img", {
          class: "logo-img",
          src: "/img/badge.png",
          alt: "RT"
        }, null, -1 /* CACHED */)),
        _createElementVNode("span", _hoisted_4, _toDisplayString(_ctx.store.panel?.site_name || '云枢面板'), 1 /* TEXT */)
      ]),
      _createElementVNode("nav", _hoisted_5, [
        (_ctx.sidebarCollapsed)
          ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_ctx.visibleGroups.flatMap(g => g.items), (it) => {
                return (_openBlock(), _createElementBlock("div", {
                  key: it.path,
                  class: _normalizeClass(["menu-item", { active: _ctx.$route.path === it.path }]),
                  title: it.label,
                  onClick: $event => (_ctx.goto(it.path))
                }, [
                  _createVNode(_component_el_icon, null, {
                    default: _withCtx(() => [
                      (_openBlock(), _createBlock(_resolveDynamicComponent(it.icon)))
                    ]),
                    _: 2 /* DYNAMIC */
                  }, 1024 /* DYNAMIC_SLOTS */)
                ], 10 /* CLASS, PROPS */, _hoisted_7))
              }), 128 /* KEYED_FRAGMENT */))
            ], 64 /* STABLE_FRAGMENT */))
          : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_ctx.visibleGroups, (g) => {
                return (_openBlock(), _createElementBlock(_Fragment, {
                  key: g.title
                }, [
                  (g.items.length)
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                        _createElementVNode("div", _hoisted_6, [
                          _createElementVNode("span", {
                            class: "menu-group-title",
                            onClick: $event => (_ctx.toggleGroup(g.title))
                          }, _toDisplayString(g.title), 1 /* TEXT */),
                          _createVNode(_component_el_icon, {
                            class: _normalizeClass(["menu-group-arrow", { open: _ctx.isOpen(g.title) }]),
                            onClick: $event => (_ctx.toggleGroup(g.title))
                          }, {
                            default: _withCtx(() => [
                              (_openBlock(), _createBlock(_resolveDynamicComponent(
                                _ctx.isOpen(g.title) ? 'ArrowDown' : 'ArrowRight')))
                            ]),
                            _: 1 /* STABLE */
                          }, 8 /* PROPS */, ["class"])
                        ]),
                        (_ctx.isOpen(g.title))
                          ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(g.items, (it) => {
                                return (_openBlock(), _createElementBlock("div", {
                                  key: it.path,
                                  class: _normalizeClass(["menu-item", { active: _ctx.$route.path === it.path }]),
                                  onClick: $event => (_ctx.goto(it.path))
                                }, [
                                  _createVNode(_component_el_icon, null, {
                                    default: _withCtx(() => [
                                      (_openBlock(), _createBlock(_resolveDynamicComponent(it.icon)))
                                    ]),
                                    _: 2 /* DYNAMIC */
                                  }, 1024 /* DYNAMIC_SLOTS */),
                                  _createElementVNode("span", null, _toDisplayString(it.label), 1 /* TEXT */)
                                ], 10 /* CLASS, PROPS */, _hoisted_7))
                              }), 128 /* KEYED_FRAGMENT */))
                            ], 64 /* STABLE_FRAGMENT */))
                          : _createCommentVNode("v-if", true)
                      ], 64 /* STABLE_FRAGMENT */))
                    : _createCommentVNode("v-if", true)
                ], 64 /* STABLE_FRAGMENT */))
              }), 128 /* KEYED_FRAGMENT */))
            ], 64 /* STABLE_FRAGMENT */))
      ])
    ]),
    _createElementVNode("div", _hoisted_8, [
      _createElementVNode("header", _hoisted_9, [
        _createElementVNode("div", {
          class: "topbar-toggle",
          onClick: $event => (_ctx.toggleSidebar())
        }, [
          _createVNode(_component_el_icon, null, {
            default: _withCtx(() => [
              (_openBlock(), _createBlock(_resolveDynamicComponent(_ctx.sidebarCollapsed ? 'Expand' : 'Fold')))
            ]),
            _: 1 /* STABLE */
          })
        ]),
        _createElementVNode("div", _hoisted_10, [
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_ctx.crumbs, (c, i) => {
            return (_openBlock(), _createElementBlock(_Fragment, {
              key: c.path
            }, [
              (i > 0)
                ? (_openBlock(), _createElementBlock("span", {
                    key: 0,
                    style: {"margin":"0 6px","color":"var(--text-secondary)"}
                  }, "/", -1 /* CACHED */))
                : _createCommentVNode("v-if", true),
              _createElementVNode("span", {
                class: _normalizeClass({ "crumb-link": i === 0 }),
                onClick: i === 0 ? ($event => (_ctx.goto(c.path))) : void 0
              }, _toDisplayString(c.label), 3 /* TEXT, CLASS */, ["onClick"])
            ], 64 /* STABLE_FRAGMENT */))
          }), 128 /* KEYED_FRAGMENT */))
        ]),
        _createElementVNode("div", _hoisted_11, [
          _createVNode(_component_el_tooltip, {
            content: "刷新页面",
            placement: "bottom"
          }, {
            default: _withCtx(() => [
              _createElementVNode("span", {
                class: "topbar-icon",
                onClick: _cache[31] || (_cache[31] = $event => (_ctx.$router.go(0)))
              }, [
                _createVNode(_component_el_icon, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_Refresh)
                  ]),
                  _: 1 /* STABLE */
                })
              ])
            ]),
            _: 1 /* STABLE */
          }),
          _createVNode(_component_el_tooltip, {
            content: "授权状态",
            placement: "bottom"
          }, {
            default: _withCtx(() => [
              _createElementVNode("span", {
                class: "license-chip",
                onClick: _cache[0] || (_cache[0] = $event => (_ctx.goto('/settings')))
              }, _toDisplayString(_ctx.licenseChip), 1 /* TEXT */)
            ]),
            _: 1 /* STABLE */
          }),
          _createVNode(_component_el_dropdown, { trigger: "click" }, {
            dropdown: _withCtx(() => [
              _createVNode(_component_el_dropdown_menu, null, {
                default: _withCtx(() => [
                  _createVNode(_component_el_dropdown_item, {
                    onClick: _cache[27] || (_cache[27] = $event => (_ctx.switchTheme('lightgold')))
                  }, {
                    default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
                      _createElementVNode("b", { style: {"color":"var(--accent)"} }, "白金 · 明亮轻奢", -1 /* CACHED */)
                    ]))]),
                    _: 1 /* STABLE */
                  }),
                  _createVNode(_component_el_dropdown_item, {
                    onClick: _cache[29] || (_cache[29] = $event => (_ctx.switchTheme('light')))
                  }, {
                    default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
                      _createElementVNode("b", { style: {"color":"var(--accent)"} }, "亮色 · 现代专业", -1 /* CACHED */)
                    ]))]),
                    _: 1 /* STABLE */
                  }),
                  _createVNode(_component_el_dropdown_item, {
                    onClick: _cache[2] || (_cache[2] = $event => (_ctx.switchTheme('silverblack')))
                  }, {
                    default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                      _createElementVNode("b", { style: {"color":"var(--accent-light)"} }, "银黑 · 冷冽曜银", -1 /* CACHED */)
                    ]))]),
                    _: 1 /* STABLE */
                  })
                ]),
                _: 1 /* STABLE */
              })
            ]),
            default: _withCtx(() => [
              _createElementVNode("span", _hoisted_12, [
                _createVNode(_component_el_icon, { style: {"vertical-align":"-2px","margin-right":"4px"} }, {
                  default: _withCtx(() => [
                    _createVNode(_component_Brush)
                  ]),
                  _: 1 /* STABLE */
                }),
                _createTextVNode(" " + _toDisplayString(_ctx.store.theme === 'lightgold' ? '白金' : _ctx.store.theme === 'light' ? '亮色' : '银黑'), 1 /* TEXT */)
              ])
            ]),
            _: 1 /* STABLE */
          }),
          _createVNode(_component_el_dropdown, { trigger: "click" }, {
            dropdown: _withCtx(() => [
              _createVNode(_component_el_dropdown_menu, null, {
                default: _withCtx(() => [
                  _createVNode(_component_el_dropdown_item, { disabled: "" }, {
                    default: _withCtx(() => [
                      _createTextVNode("角色：" + _toDisplayString(_ctx.store.role?.name || _ctx.store.user?.role), 1 /* TEXT */)
                    ]),
                    _: 1 /* STABLE */
                  }),
                  _createVNode(_component_el_dropdown_item, {
                    divided: "",
                    onClick: _ctx.changePwd
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_el_icon, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_Key)
                        ]),
                        _: 1 /* STABLE */
                      }),
                      _cache[16] || (_cache[16] = _createTextVNode(" 修改密码 ", -1 /* CACHED */))
                    ]),
                    _: 1 /* STABLE */
                  }, 8 /* PROPS */, ["onClick"]),
                  _createVNode(_component_el_dropdown_item, { onClick: _ctx.open2fa }, {
                    default: _withCtx(() => [
                      _createVNode(_component_el_icon, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_Cellphone)
                        ]),
                        _: 1 /* STABLE */
                      }),
                      _createTextVNode(" " + _toDisplayString(_ctx.store.user?.two_fa ? '关闭两步验证' : '启用两步验证'), 1 /* TEXT */)
                    ]),
                    _: 1 /* STABLE */
                  }, 8 /* PROPS */, ["onClick"]),
                  _createVNode(_component_el_dropdown_item, {
                    divided: "",
                    onClick: _ctx.logout
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_el_icon, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_SwitchButton)
                        ]),
                        _: 1 /* STABLE */
                      }),
                      _cache[17] || (_cache[17] = _createTextVNode(" 退出登录 ", -1 /* CACHED */))
                    ]),
                    _: 1 /* STABLE */
                  }, 8 /* PROPS */, ["onClick"])
                ]),
                _: 1 /* STABLE */
              })
            ]),
            default: _withCtx(() => [
              _createElementVNode("span", _hoisted_13, [
                _createVNode(_component_el_avatar, {
                  size: 28,
                  style: {"background":"var(--accent-grad)","color":"var(--text-inverse)","font-weight":"700"}
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString((_ctx.store.user?.username || 'A')[0].toUpperCase()), 1 /* TEXT */)
                  ]),
                  _: 1 /* STABLE */
                }),
                _createTextVNode(" " + _toDisplayString(_ctx.store.user?.username), 1 /* TEXT */)
              ])
            ]),
            _: 1 /* STABLE */
          })
        ])
      ]),
      _createElementVNode("main", _hoisted_14, [
        _createVNode(_component_router_view, null, {
          default: _withCtx(({ Component }) => [
            _createVNode(_Transition, {
              name: "page-fade",
              mode: "out-in"
            }, {
              default: _withCtx(() => [
                (_openBlock(), _createBlock(_resolveDynamicComponent(Component)))
              ]),
              _: 2 /* DYNAMIC */
            }, 1024 /* DYNAMIC_SLOTS */)
          ]),
          _: 1 /* STABLE */
        })
      ])
    ]),
    _createCommentVNode(" 修改密码 "),
    _createVNode(_component_el_dialog, {
      modelValue: _ctx.pwdDialog.show,
      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((_ctx.pwdDialog.show) = $event)),
      title: "修改登录密码",
      width: "420px"
    }, {
      footer: _withCtx(() => [
        _createElementVNode("div", _hoisted_15, [
          _createVNode(_component_el_button, {
            onClick: _cache[6] || (_cache[6] = $event => (_ctx.pwdDialog.show = false))
          }, {
            default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
              _createTextVNode("取消", -1 /* CACHED */)
            ]))]),
            _: 1 /* STABLE */
          }),
          _createVNode(_component_el_button, {
            type: "primary",
            onClick: _ctx.submitPwd
          }, {
            default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
              _createTextVNode("确认修改", -1 /* CACHED */)
            ]))]),
            _: 1 /* STABLE */
          }, 8 /* PROPS */, ["onClick"])
        ])
      ]),
      default: _withCtx(() => [
        _createVNode(_component_el_form, { "label-width": "90px" }, {
          default: _withCtx(() => [
            _createVNode(_component_el_form_item, { label: "原密码" }, {
              default: _withCtx(() => [
                _createVNode(_component_el_input, {
                  modelValue: _ctx.pwdDialog.old,
                  "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((_ctx.pwdDialog.old) = $event)),
                  type: "password",
                  "show-password": ""
                }, null, 8 /* PROPS */, ["modelValue"])
              ]),
              _: 1 /* STABLE */
            }),
            _createVNode(_component_el_form_item, { label: "新密码" }, {
              default: _withCtx(() => [
                _createVNode(_component_el_input, {
                  modelValue: _ctx.pwdDialog.n1,
                  "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((_ctx.pwdDialog.n1) = $event)),
                  type: "password",
                  "show-password": ""
                }, null, 8 /* PROPS */, ["modelValue"])
              ]),
              _: 1 /* STABLE */
            }),
            _createVNode(_component_el_form_item, { label: "确认密码" }, {
              default: _withCtx(() => [
                _createVNode(_component_el_input, {
                  modelValue: _ctx.pwdDialog.n2,
                  "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((_ctx.pwdDialog.n2) = $event)),
                  type: "password",
                  "show-password": ""
                }, null, 8 /* PROPS */, ["modelValue"])
              ]),
              _: 1 /* STABLE */
            })
          ]),
          _: 1 /* STABLE */
        })
      ]),
      _: 1 /* STABLE */
    }, 8 /* PROPS */, ["modelValue"]),
    _createCommentVNode(" 两步验证 "),
    _createVNode(_component_el_dialog, {
      modelValue: _ctx.fa2Dialog.show,
      "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((_ctx.fa2Dialog.show) = $event)),
      title: _ctx.store.user?.two_fa ? '关闭两步验证' : '启用两步验证',
      width: "480px"
    }, {
      footer: _withCtx(() => [
        _createElementVNode("div", _hoisted_18, [
          _createVNode(_component_el_button, {
            onClick: _cache[10] || (_cache[10] = $event => (_ctx.fa2Dialog.show = false))
          }, {
            default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
              _createTextVNode("取消", -1 /* CACHED */)
            ]))]),
            _: 1 /* STABLE */
          }),
          (!_ctx.store.user?.two_fa)
            ? (_openBlock(), _createBlock(_component_el_button, {
                key: 0,
                type: "primary",
                onClick: _ctx.enable2fa
              }, {
                default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                  _createTextVNode("启用", -1 /* CACHED */)
                ]))]),
                _: 1 /* STABLE */
              }, 8 /* PROPS */, ["onClick"]))
            : (_openBlock(), _createBlock(_component_el_button, {
                key: 1,
                type: "danger",
                onClick: _ctx.disable2fa
              }, {
                default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                  _createTextVNode("确认关闭", -1 /* CACHED */)
                ]))]),
                _: 1 /* STABLE */
              }, 8 /* PROPS */, ["onClick"]))
        ])
      ]),
      default: _withCtx(() => [
        (!_ctx.store.user?.two_fa)
          ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
              _createVNode(_component_el_alert, {
                type: "warning",
                closable: false,
                style: {"margin-bottom":"14px"},
                title: "请使用 Google Authenticator / Microsoft Authenticator 等 TOTP 应用扫码或手动输入密钥"
              }),
              _createElementVNode("p", null, [
                _cache[20] || (_cache[20] = _createTextVNode("密钥：", -1 /* CACHED */)),
                _createElementVNode("span", _hoisted_16, _toDisplayString(_ctx.fa2Dialog.secret), 1 /* TEXT */)
              ]),
              _createElementVNode("p", _hoisted_17, _toDisplayString(_ctx.fa2Dialog.otpauth), 1 /* TEXT */),
              _createVNode(_component_el_form, { "label-width": "90px" }, {
                default: _withCtx(() => [
                  _createVNode(_component_el_form_item, { label: "验证码" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_el_input, {
                        modelValue: _ctx.fa2Dialog.code,
                        "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((_ctx.fa2Dialog.code) = $event)),
                        placeholder: "输入 6 位动态码确认",
                        maxlength: "6"
                      }, null, 8 /* PROPS */, ["modelValue"])
                    ]),
                    _: 1 /* STABLE */
                  })
                ]),
                _: 1 /* STABLE */
              })
            ], 64 /* STABLE_FRAGMENT */))
          : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
              _cache[21] || (_cache[21] = _createElementVNode("p", null, "请输入当前动态验证码以关闭两步验证：", -1 /* CACHED */)),
              _createVNode(_component_el_input, {
                modelValue: _ctx.fa2Dialog.code,
                "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((_ctx.fa2Dialog.code) = $event)),
                placeholder: "6 位动态码",
                maxlength: "6"
              }, null, 8 /* PROPS */, ["modelValue"])
            ], 64 /* STABLE_FRAGMENT */))
      ]),
      _: 1 /* STABLE */
    }, 8 /* PROPS */, ["modelValue", "title"])
  ]))
} })()
}
