#!/bin/bash
# Created by 小杜 on 2026/08

# ============================================================
#  芮拓面板 命令行管理工具（自研）
#  用法: rt [status|start|stop|restart|port|password|entrance|ssl|info|help]
#  无参数时进入交互式菜单
# ============================================================
RT_DIR="/opt/rt-panel/backend"
CONF="$RT_DIR/data/config.json"
SVC="rt-panel"

GOLD=$'\033[38;2;212;175;55m'
GREY=$'\033[38;2;140;134;120m'
GREEN=$'\033[38;2;103;194;58m'
RED=$'\033[38;2;245;108;108m'
RESET=$'\033[0m'

get_port() { grep -o '"port"[[:space:]]*:[[:space:]]*[0-9]*' "$CONF" 2>/dev/null | grep -o '[0-9]*' | head -n 1; }
get_entrance() { grep -o '"security_entrance"[[:space:]]*:[[:space:]]*"[^"]*"' "$CONF" 2>/dev/null | sed 's/.*: *"//;s/"//'; }

menu() {
  echo ""
  echo "${GOLD}  ========== 芮拓面板 命令行管理 ==========${RESET}"
  echo "   ${GREY}1)${RESET} 查看面板状态       ${GREY}6)${RESET} 查看面板信息"
  echo "   ${GREY}2)${RESET} 重启面板           ${GREY}7)${RESET} 设置安全入口"
  echo "   ${GREY}3)${RESET} 停止面板           ${GREY}8)${RESET} 生成面板HTTPS证书"
  echo "   ${GREY}4)${RESET} 启动面板           ${GREY}9)${RESET} 查看登录信息"
  echo "   ${GREY}5)${RESET} 修改访问端口       ${GREY}0)${RESET} 退出"
  echo ""
  read -r -p "  请选择 [0-9]: " c
  case "$c" in
    1) rt_status ;;
    2) do_restart ;;
    3) systemctl stop "$SVC" && echo "${GREEN}已停止${RESET}" ;;
    4) systemctl start "$SVC" && echo "${GREEN}已启动${RESET}" ;;
    5) set_port ;;
    6) do_info ;;
    7) set_entrance ;;
    8) gen_ssl ;;
    9) show_login ;;
    0) exit 0 ;;
    *) echo "${RED}无效选择${RESET}" ;;
  esac
}

rt_status() {
  if systemctl is-active --quiet "$SVC"; then
    echo "${GREEN}● 芮拓面板运行中${RESET}  http://服务器IP:$(get_port)"
  else
    echo "${RED}○ 芮拓面板未运行${RESET}"
  fi
}

do_restart() { systemctl restart "$SVC" && echo "${GREEN}面板已重启${RESET}"; }

set_port() {
  read -r -p "请输入新端口号(1-65535): " np
  case "$np" in
    ''|*[!0-9]*) echo "${RED}端口无效${RESET}"; return ;;
  esac
  if [ "$np" -lt 1 ] || [ "$np" -gt 65535 ]; then echo "${RED}端口超出范围${RESET}"; return; fi
  python3 -c "
import json, sys
p = '$CONF'
cfg = json.load(open(p))
cfg['port'] = int('$np')
json.dump(cfg, open(p, 'w'), ensure_ascii=False, indent=2)
print('端口已修改为 $np')
"
  systemctl restart "$SVC"
  echo "${GREEN}端口已修改为 $np 并重启面板${RESET}"
}

set_entrance() {
  read -r -p "请输入安全入口(6-32位字母数字下划线，留空关闭): " ent
  ent=$(echo "$ent" | tr -d '/')
  if [ -n "$ent" ] && ! echo "$ent" | grep -qE '^[a-zA-Z0-9_-]{6,32}$'; then
    echo "${RED}入口格式无效${RESET}"; return
  fi
  python3 -c "
import json
p = '$CONF'
cfg = json.load(open(p))
cfg['security_entrance'] = '$ent'
json.dump(cfg, open(p, 'w'), ensure_ascii=False, indent=2)
"
  systemctl restart "$SVC"
  if [ -n "$ent" ]; then
    echo "${GREEN}安全入口已设置，访问地址: http://服务器IP:$(get_port)/$ent/${RESET}"
  else
    echo "${GREEN}安全入口已关闭${RESET}"
  fi
}

gen_ssl() {
  openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -keyout "$RT_DIR/data/certs/panel/panel.key" \
    -out "$RT_DIR/data/certs/panel/panel.crt" \
    -subj "/CN=芮拓面板/O=Ruituo Panel/C=CN" 2>/dev/null && \
  python3 -c "
import json
p = '$CONF'
cfg = json.load(open(p))
cfg['ssl_cert'] = '$RT_DIR/data/certs/panel/panel.crt'
cfg['ssl_key'] = '$RT_DIR/data/certs/panel/panel.key'
json.dump(cfg, open(p, 'w'), ensure_ascii=False, indent=2)
"
  systemctl restart "$SVC"
  echo "${GREEN}HTTPS 证书已生成并启用，请用 https:// 访问${RESET}"
}

do_info() {
  echo "${GREY}面板目录: $RT_DIR${RESET}"
  echo "${GREY}访问端口: $(get_port)${RESET}"
  echo "${GREY}安全入口: $(get_entrance)${RESET}"
  echo "${GREY}数据目录: $RT_DIR/data${RESET}"
  echo "${GREY}服务日志: journalctl -u $SVC -f${RESET}"
}

show_login() {
  echo "${GOLD}面板地址: http://服务器IP:$(get_port)/$(get_entrance)${RESET}"
  echo "${GREY}登录账号: 安装时网页初始化设置的管理员账号${RESET}"
}

case "$1" in
  status) rt_status ;;
  start) systemctl start "$SVC" && echo "${GREEN}已启动${RESET}" ;;
  stop) systemctl stop "$SVC" && echo "${GREEN}已停止${RESET}" ;;
  restart) do_restart ;;
  port) set_port ;;
  entrance) set_entrance ;;
  ssl) gen_ssl ;;
  info) do_info ;;
  help|-h|--help)
    echo "用法: rt [status|start|stop|restart|port|entrance|ssl|info|help]" ;;
  "") while true; do menu; done ;;
  *) echo "${RED}未知命令: $1（运行 rt 查看菜单）${RESET}" ;;
esac
