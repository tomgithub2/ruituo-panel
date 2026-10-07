// Created by 小杜 on 2026/08

// 网页初始化向导：安装完成后首次配置管理员账号 + 官网账户
import api from '../api.js'

const { ElMessage } = window.ElementPlus

export default {
  data() {
    return {
      loading: false,
      status: { initialized: true, need_token: false, site_url: 'https://www.rt888.icu' },
      form: {
        token: '',
        username: '',
        password: '',
        password2: '',
        bind: false,
        site_account: '',
        site_password: '',
      },
      rules: {
        token: [{ required: true, message: '请输入安装时打印的初始化令牌', trigger: 'blur' }],
        username: [{ required: true, message: '请输入管理员用户名', trigger: 'blur' },
                   { pattern: /^[a-zA-Z][a-zA-Z0-9_]{2,31}$/, message: '以字母开头，3-32位字母/数字/下划线', trigger: 'blur' }],
        password: [{ required: true, message: '请设置管理员密码', trigger: 'blur' },
                   { pattern: /^(?=.*[a-zA-Z])(?=.*[0-9]).{8,}$/, message: '至少8位且包含字母和数字', trigger: 'blur' }],
        password2: [{ required: true, message: '请再次输入密码', trigger: 'blur' }],
        site_account: [{ required: true, message: '请输入官网账户（邮箱）', trigger: 'blur' }],
        site_password: [{ required: true, message: '请输入官网账户密码', trigger: 'blur' }],
      },
      themes: [
        { key: 'lightgold', label: '白金', desc: '明亮轻奢' },
        { key: 'light', label: '亮色', desc: '现代专业' },
        { key: 'silverblack', label: '银黑', desc: '冷冽曜银' },
      ],
    }
  },
  mounted() {
    api.get('/setup/status').then(res => {
      this.status = res
      if (res.initialized) {
        ElMessage.info('面板已完成初始化，即将前往登录页')
        setTimeout(() => location.hash = '#/login', 800)
      }
    }).catch(() => {})
  },
  methods: {
    switchTheme(key) {
      window.applyTheme(key)
      this.$forceUpdate()
    },
    async doInit() {
      if (this.form.password !== this.form.password2) {
        return ElMessage.warning('两次输入的密码不一致')
      }
      if (this.form.bind && (!this.form.site_account || !this.form.site_password)) {
        return ElMessage.warning('请填写官网账户和密码，或取消绑定官网账户')
      }
      this.loading = true
      try {
        const r = await api.post('/setup/init', this.form)
        this.$message.success('初始化完成！正在前往登录页…')
        setTimeout(() => location.hash = '#/login', 1200)
      } catch (e) {
        // 错误已由 api 拦截器提示
      } finally {
        this.loading = false
      }
    },
  },
  render: (function(){ const { createElementVNode: _createElementVNode, createTextVNode: _createTextVNode, resolveComponent: _resolveComponent, createVNode: _createVNode, withCtx: _withCtx, openBlock: _openBlock, createBlock: _createBlock, createCommentVNode: _createCommentVNode, renderList: _renderList, Fragment: _Fragment, createElementBlock: _createElementBlock, toDisplayString: _toDisplayString, createStaticVNode: _createStaticVNode } = Vue

const _hoisted_1 = { class: "op-page setup-page" }
const _hoisted_2 = { class: "setup-card" }
const _hoisted_3 = { class: "setup-themes" }
const _hoisted_4 = ["title", "onClick"]

return function render(_ctx, _cache) {
  const _component_el_input = _resolveComponent("el-input")
  const _component_el_form_item = _resolveComponent("el-form-item")
  const _component_el_col = _resolveComponent("el-col")
  const _component_el_row = _resolveComponent("el-row")
  const _component_el_switch = _resolveComponent("el-switch")
  const _component_el_button = _resolveComponent("el-button")
  const _component_el_form = _resolveComponent("el-form")

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[11] || (_cache[11] = _createStaticVNode("<div class=\"setup-brand\"><div class=\"setup-logo\">RT</div><div class=\"setup-title\">初始化 锐同面板</div><div class=\"setup-sub\">首次使用 · 创建管理员账号 · 绑定官网账户解锁全部能力</div></div><div class=\"setup-steps\"><div class=\"step done\"><i>1</i><span>校验令牌</span></div><div class=\"step-line\"></div><div class=\"step\"><i>2</i><span>管理员账号</span></div><div class=\"step-line\"></div><div class=\"step\"><i>3</i><span>官网账户<span class=\"opt\">可选</span></span></div></div>", 2)),
      _createVNode(_component_el_form, {
        ref: "formRef",
        model: _ctx.form,
        rules: _ctx.rules,
        "label-position": "top",
        size: "large"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_el_form_item, {
            label: "初始化令牌（安装时终端已打印）",
            prop: "token"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_el_input, {
                modelValue: _ctx.form.token,
                "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((_ctx.form.token) = $event)),
                placeholder: "例如 a1b2c3d4e5f60718",
                "show-password": "",
                maxlength: "32",
                autocomplete: "off"
              }, null, 8 /* PROPS */, ["modelValue"])
            ]),
            _: 1 /* STABLE */
          }),
          _createVNode(_component_el_row, { gutter: 16 }, {
            default: _withCtx(() => [
              _createVNode(_component_el_col, { span: 24 }, {
                default: _withCtx(() => [
                  _createVNode(_component_el_form_item, {
                    label: "管理员用户名",
                    prop: "username"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_el_input, {
                        modelValue: _ctx.form.username,
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((_ctx.form.username) = $event)),
                        placeholder: "面板登录用户名",
                        autocomplete: "off"
                      }, null, 8 /* PROPS */, ["modelValue"])
                    ]),
                    _: 1 /* STABLE */
                  })
                ]),
                _: 1 /* STABLE */
              })
            ]),
            _: 1 /* STABLE */
          }),
          _createVNode(_component_el_row, { gutter: 16 }, {
            default: _withCtx(() => [
              _createVNode(_component_el_col, { span: 12 }, {
                default: _withCtx(() => [
                  _createVNode(_component_el_form_item, {
                    label: "登录密码",
                    prop: "password"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_el_input, {
                        modelValue: _ctx.form.password,
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((_ctx.form.password) = $event)),
                        type: "password",
                        "show-password": "",
                        placeholder: "至少8位，含字母和数字",
                        autocomplete: "new-password"
                      }, null, 8 /* PROPS */, ["modelValue"])
                    ]),
                    _: 1 /* STABLE */
                  })
                ]),
                _: 1 /* STABLE */
              }),
              _createVNode(_component_el_col, { span: 12 }, {
                default: _withCtx(() => [
                  _createVNode(_component_el_form_item, {
                    label: "确认密码",
                    prop: "password2"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_el_input, {
                        modelValue: _ctx.form.password2,
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((_ctx.form.password2) = $event)),
                        type: "password",
                        "show-password": "",
                        placeholder: "再次输入密码",
                        autocomplete: "new-password"
                      }, null, 8 /* PROPS */, ["modelValue"])
                    ]),
                    _: 1 /* STABLE */
                  })
                ]),
                _: 1 /* STABLE */
              })
            ]),
            _: 1 /* STABLE */
          }),
          _cache[8] || (_cache[8] = _createElementVNode("div", { class: "setup-divider" }, [
            _createElementVNode("span", null, "官网账户绑定（可稍后在「面板设置 → 账户绑定」中完成）")
          ], -1 /* CACHED */)),
          _createVNode(_component_el_switch, {
            modelValue: _ctx.form.bind,
            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((_ctx.form.bind) = $event)),
            "active-text": "立即绑定官网账户",
            "inactive-text": "暂不绑定（免费版可绑定 2 台机器）"
          }, null, 8 /* PROPS */, ["modelValue"]),
          (_ctx.form.bind)
            ? (_openBlock(), _createBlock(_component_el_row, {
                key: 0,
                gutter: 16,
                style: {"margin-top":"16px"}
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_el_col, { span: 12 }, {
                    default: _withCtx(() => [
                      _createVNode(_component_el_form_item, {
                        label: "官网账户（邮箱）",
                        prop: "site_account"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_el_input, {
                            modelValue: _ctx.form.site_account,
                            "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((_ctx.form.site_account) = $event)),
                            placeholder: "在 rt888.icu 注册的账户",
                            autocomplete: "off"
                          }, null, 8 /* PROPS */, ["modelValue"])
                        ]),
                        _: 1 /* STABLE */
                      })
                    ]),
                    _: 1 /* STABLE */
                  }),
                  _createVNode(_component_el_col, { span: 12 }, {
                    default: _withCtx(() => [
                      _createVNode(_component_el_form_item, {
                        label: "官网密码",
                        prop: "site_password"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_el_input, {
                            modelValue: _ctx.form.site_password,
                            "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((_ctx.form.site_password) = $event)),
                            type: "password",
                            "show-password": "",
                            placeholder: "官网账户密码",
                            autocomplete: "off"
                          }, null, 8 /* PROPS */, ["modelValue"])
                        ]),
                        _: 1 /* STABLE */
                      })
                    ]),
                    _: 1 /* STABLE */
                  })
                ]),
                _: 1 /* STABLE */
              }))
            : _createCommentVNode("v-if", true),
          _createVNode(_component_el_button, {
            type: "primary",
            size: "large",
            class: "setup-btn",
            loading: _ctx.loading,
            onClick: _ctx.doInit
          }, {
            default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
              _createTextVNode(" 完成初始化，进入面板 ", -1 /* CACHED */)
            ]))]),
            _: 1 /* STABLE */
          }, 8 /* PROPS */, ["loading", "onClick"]),
          _cache[9] || (_cache[9] = _createElementVNode("div", { class: "setup-foot" }, [
            _createElementVNode("span", null, [
              _createTextVNode("忘记令牌？在服务器上执行："),
              _createElementVNode("code", null, "cat data/setup_token.txt"),
              _createTextVNode("（Windows: "),
              _createElementVNode("code", null, "type data\\\\setup_token.txt"),
              _createTextVNode("）")
            ])
          ], -1 /* CACHED */))
        ]),
        _: 1 /* STABLE */
      }, 8 /* PROPS */, ["model", "rules"]),
      _createElementVNode("div", _hoisted_3, [
        _cache[10] || (_cache[10] = _createElementVNode("span", { class: "theme-label" }, "外观主题", -1 /* CACHED */)),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_ctx.themes, (t) => {
          return (_openBlock(), _createElementBlock("button", {
            key: t.key,
            class: "theme-chip",
            title: t.desc,
            onClick: $event => (_ctx.switchTheme(t.key))
          }, _toDisplayString(t.label), 9 /* TEXT, PROPS */, _hoisted_4))
        }), 128 /* KEYED_FRAGMENT */))
      ])
    ])
  ]))
} })(),
}
