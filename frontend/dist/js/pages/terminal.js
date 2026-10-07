// Created by 小杜 on 2026/08

// Web 终端（xterm.js + WebSocket）
import { hasPerm } from '../util.js'

export default {
  data() {
    return { term: null, fit: null, ws: null, status: '未连接', cols: 120, rows: 32, sessions: 1,
             quickCmds: [
               { name: '面板状态', cmd: 'rt status' },
               { name: '重启面板', cmd: 'rt restart' },
               { name: '查看端口', cmd: 'netstat -tlnp 2>/dev/null || netstat -ano | findstr LISTENING' },
               { name: '内存占用', cmd: 'free -m || wmic OS get FreePhysicalMemory' },
               { name: '磁盘空间', cmd: 'df -h || wmic logicaldisk get DeviceID,FreeSpace' },
               { name: '重载 Nginx', cmd: 'nginx -s reload 2>&1 || echo Nginx未安装' },
               { name: '查看负载', cmd: 'uptime' },
               { name: '清屏', cmd: 'clear' },
             ] }
  },
  mounted() { this.init() },
  beforeUnmount() {
    if (this.ws) this.ws.close()
    if (this.term) this.term.dispose()
  },
  methods: {
    hasPerm,
    sendQuick(cmd) {
      // 快捷命令：写入终端并回车执行
      if (this.ws && this.ws.readyState === 1) {
        this.ws.send(JSON.stringify({ type: 'in', data: cmd + '\r' }))
        this.term.focus()
      }
    },
    init() {
      if (!hasPerm('terminal:use')) return
      this.term = new window.Terminal({
        cursorBlink: true, fontSize: 14, fontFamily: 'Cascadia Code, Consolas, monospace',
        theme: { background: '#0b0d10', foreground: '#d5dde8', cursor: '#d4af37' },
        scrollback: 4000, convertEol: false,
      })
      this.fit = new window.FitAddon.FitAddon()
      this.term.loadAddon(this.fit)
      this.term.open(this.$refs.termEl)
      this.fit.fit()
      this.connect()
      window.addEventListener('resize', this.onResize)
      this.term.onData(data => {
        if (this.ws && this.ws.readyState === 1) {
          this.ws.send(JSON.stringify({ type: 'in', data }))
        }
      })
    },
    connect() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const token = localStorage.getItem('ops_token')
      this.ws = new WebSocket(`${proto}://${location.host}/ws/terminal?token=${encodeURIComponent(token)}`)
      this.status = '连接中…'
      this.ws.onopen = () => {
        this.status = '已连接'
        this.term.writeln('\x1b[1;33m—— 锐同面板 Web 终端 ——\x1b[0m')
        this.sendResize()
        this.term.focus()
      }
      this.ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'out') this.term.write(msg.data)
          else if (msg.type === 'exit') { this.status = '会话结束'; this.term.writeln('\r\n\x1b[31m[会话已结束，点击重新连接]\x1b[0m') }
        } catch (e) {}
      }
      this.ws.onclose = () => { this.status = '已断开' }
      this.ws.onerror = () => { this.status = '连接错误' }
    },
    sendResize() {
      if (this.ws && this.ws.readyState === 1) {
        const dims = this.fit.proposeDimensions()
        if (dims) {
          this.ws.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }))
        }
      }
    },
    onResize() {
      if (this.fit && this.term) {
        this.fit.fit()
        this.sendResize()
      }
    },
    reconnect() {
      if (this.ws) this.ws.close()
      this.term.reset()
      this.connect()
    },
    clearTerm() { this.term.clear() },
  },
  render: (function(){ const { toDisplayString: _toDisplayString, createTextVNode: _createTextVNode, resolveComponent: _resolveComponent, withCtx: _withCtx, createVNode: _createVNode, createElementVNode: _createElementVNode, openBlock: _openBlock, createElementBlock: _createElementBlock, createBlock: _createBlock, renderList: _renderList, Fragment: _Fragment } = Vue

const _hoisted_1 = { class: "op-page" }
const _hoisted_2 = { class: "op-card" }
const _hoisted_3 = { class: "card-title" }
const _hoisted_4 = { style: {"margin-left":"auto","display":"flex","gap":"8px"} }
const _hoisted_5 = { class: "card-body" }
const _hoisted_6 = {
  class: "term-container",
  style: {"height":"calc(100vh - 220px)"}
}
const _hoisted_7 = {
  ref: "termEl",
  style: {"height":"100%"}
}

return function render(_ctx, _cache) {
  const _component_el_tag = _resolveComponent("el-tag")
  const _component_el_button = _resolveComponent("el-button")

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _cache[2] || (_cache[2] = _createTextVNode("Web 终端 ", -1 /* CACHED */)),
        _createVNode(_component_el_tag, {
          size: "small",
          type: _ctx.status === '已连接' ? 'success' : 'warning',
          style: {"margin-left":"8px"}
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(_ctx.status), 1 /* TEXT */)
          ]),
          _: 1 /* STABLE */
        }, 8 /* PROPS */, ["type"]),
        _createElementVNode("div", _hoisted_4, [
          _createVNode(_component_el_button, {
            size: "small",
            onClick: _ctx.reconnect
          }, {
            default: _withCtx(() => [...(_cache[0] || (_cache[0] = [
              _createTextVNode("重新连接", -1 /* CACHED */)
            ]))]),
            _: 1 /* STABLE */
          }, 8 /* PROPS */, ["onClick"]),
          _createVNode(_component_el_button, {
            size: "small",
            onClick: _ctx.clearTerm
          }, {
            default: _withCtx(() => [...(_cache[1] || (_cache[1] = [
              _createTextVNode("清屏", -1 /* CACHED */)
            ]))]),
            _: 1 /* STABLE */
          }, 8 /* PROPS */, ["onClick"])
        ])
      ]),
      _createElementVNode("div", _hoisted_5, [
        _createElementVNode("div", { class: "term-quick" }, [
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_ctx.quickCmds, (q) => {
            return (_openBlock(), _createBlock(_component_el_button, {
              key: q.name,
              size: "small",
              onClick: $event => (_ctx.sendQuick(q.cmd)),
              style: {"margin":"0 6px 8px 0"}
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(q.name), 1 /* TEXT */)
              ]),
              _: 2 /* DYNAMIC */
            }, 1032 /* PROPS, DYNAMIC_SLOTS */, ["onClick"]))
          }), 128 /* KEYED_FRAGMENT */))
        ]),
        _createElementVNode("div", _hoisted_6, [
          _createElementVNode("div", _hoisted_7, null, 512 /* NEED_PATCH */)
        ]),
        _cache[3] || (_cache[3] = _createElementVNode("div", { style: {"margin-top":"10px","color":"var(--text-secondary)","font-size":"12px"} }, " 终端运行于服务器本地环境 · 所有操作将被审计记录 · 服务器上可直接运行 rt 命令管理面板（Linux）· 快捷按钮一键执行常用命令 ", -1 /* CACHED */))
      ])
    ])
  ]))
} })()
}
