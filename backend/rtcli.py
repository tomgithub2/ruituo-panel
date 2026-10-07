#!/usr/bin/env python3
# Created by 小杜 on 2026/09
"""云枢面板 命令行管理器（rt）。

用法：
    rt                 进入交互菜单（列表式）
    rt status          查看状态（版本/进程/端口/绑定）
    rt check           检查官网是否有新版本
    rt update          立即更新（复用面板内置更新逻辑，绕开界面）
    rt rollback        回滚到上一个版本
    rt restart         重启面板
    rt start / stop    启动 / 停止面板
    rt logs [n]        查看最近 n 行日志（默认 50）
    rt password        重置管理员密码（交互输入）
    rt where           显示面板安装目录与运行方式
    rt help            帮助

设计要点：
  · 更新逻辑**直接调用 backend/app/routers/update.py 里的实现**，不重复造轮子，
    因此界面更新失效时本命令仍可完成升级（这正是 rc2 里「立即更新」报 422 时的自救通道）。
  · Linux 用 systemd（rt-panel）或直接进程；Windows 用信号/进程方式，均自动探测。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DEPS = os.path.join(HERE, ".deps")
if os.path.isdir(DEPS):
    sys.path.insert(0, DEPS)

SERVICE = "rt-panel"
BOLD, DIM, GREEN, YELLOW, RED, CYAN, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m")


def _c(text, color):
    return f"{color}{text}{RESET}" if sys.stdout.isatty() else str(text)


def _config():
    try:
        from app.config import PANEL_VERSION, get_config
        return PANEL_VERSION, get_config() or {}
    except Exception as e:
        return None, {'_error': str(e)}


def _is_linux():
    return sys.platform.startswith("linux")


def _systemd_active() -> str:
    if not _is_linux():
        return ""
    try:
        r = subprocess.run(["systemctl", "is-active", SERVICE], capture_output=True, text=True, timeout=8)
        return r.stdout.strip()
    except Exception:
        return ""


def _port_listening(port: int) -> bool:
    try:
        if _is_linux():
            r = subprocess.run(["ss", "-ltn"], capture_output=True, text=True, timeout=8)
            return f":{port} " in r.stdout or f":{port}\n" in r.stdout
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue) -ne $null"],
                           capture_output=True, text=True, timeout=15)
        return "True" in r.stdout
    except Exception:
        return False


def _binding():
    try:
        from app import binding
        st = binding.status()
        return st if isinstance(st, dict) else {}
    except Exception as e:
        return {'error': str(e)}


# ---------------- 各子命令 ----------------

def cmd_status(_args):
    ver, cfg = _config()
    print(_c("云枢面板 状态", BOLD))
    print(f"  版本      : {ver or _c('读取失败', RED)}")
    print(f"  安装目录  : {HERE}")
    print(f"  监听端口  : {cfg.get('port', 8000)}（{'监听中' if _port_listening(int(cfg.get('port', 8000))) else '未监听'}）")
    if _is_linux():
        print(f"  systemd   : {SERVICE} = {_systemd_active() or '未安装为服务'}")
    print(f"  官网地址  : {cfg.get('account_server', '')}")
    b = _binding()
    if b:
        print(f"  绑定状态  : {b.get('account') or '未绑定'}"
              f"{'（' + str(b.get('plan')) + '）' if b.get('plan') else ''}"
              f"{'  密钥: ' + ('已领取' if b.get('rolling_secret') else '未领取') if 'rolling_secret' in b else ''}")
        if b.get('error'):
            print(f"              {_c(str(b['error']), YELLOW)}")
    return 0


def _site_check():
    """调用官网更新接口（只读，不需要登录）。"""
    from app.routers import update as upd
    try:
        return upd.check({'username': 'cli', 'role': 'admin'})
    except TypeError:
        return upd.check()
    except Exception as e:
        return {'has_update': False, 'message': f'检查失败: {e}'}


def cmd_check(_args):
    info = _site_check()
    print(_c("检查更新", BOLD))
    if info.get('has_update'):
        print(f"  发现新版本: {_c(info.get('version'), GREEN)}"
              f"（当前 {info.get('current_version')}，{info.get('size', 0)} 字节）")
        if info.get('notes'):
            print(f"  更新说明  : {str(info['notes'])[:200]}")
        print("  执行更新  : " + _c("rt update", CYAN))
    else:
        print(f"  已是最新版本（{info.get('current_version')}）{('：' + str(info.get('message'))) if info.get('message') else ''}")
    return 0


def cmd_update(_args):
    from app.routers import update as upd
    info = _site_check()
    if not info.get('has_update'):
        print("  已是最新版本，无需更新。")
        return 0
    ver = info.get('version')
    print(f"  正在更新到 {_c(ver, GREEN)} …（下载→校验→替换→重启）")
    try:
        upd._apply_impl(info)          # 复用面板内置更新实现
        try:
            upd._ack_push(info)
        except Exception:
            pass
        print(_c(f"  更新完成，请稍候面板自动重启（版本 {ver}）。", GREEN))
        return 0
    except Exception as e:
        print(_c(f"  更新失败: {e}", RED))
        print("  可执行 rt rollback 回滚，或查看 rt logs。")
        return 1


def cmd_rollback(_args):
    from app.routers import update as upd
    try:
        fn = getattr(upd, '_rollback_impl', None)
        if fn is None:
            print(_c("  当前版本不支持命令行回滚，请在面板界面操作。", YELLOW))
            return 1
        fn()
        print(_c("  已回滚，面板将自动重启。", GREEN))
        return 0
    except Exception as e:
        print(_c(f"  回滚失败: {e}", RED))
        return 1


def _service(action):
    if _is_linux():
        if _systemd_active():
            r = subprocess.run(["systemctl", action, SERVICE], capture_output=True, text=True, timeout=60)
            print(f"  systemctl {action} {SERVICE}: {r.stdout.strip() or r.stderr.strip() or 'ok'}")
            return r.returncode
        print(_c("  未检测到 systemd 服务，直接操作进程。", YELLOW))
    # 直接进程方式
    if action == "stop":
        if _is_linux():
            subprocess.run(["pkill", "-f", "run.py"], timeout=15)
        else:
            pid = _win_pid()
            if pid:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], timeout=15)
        print("  已停止")
        return 0
    if action == "start":
        if _is_linux():
            subprocess.Popen(["nohup", "python3", os.path.join(HERE, "run.py")],
                             stdout=open(os.path.join(HERE, "data", "cli_start.log"), "a"),
                             stderr=subprocess.STDOUT, start_new_session=True)
        else:
            subprocess.Popen([sys.executable, os.path.join(HERE, "run.py")], cwd=HERE,
                             creationflags=0x00000008,  # DETACHED_PROCESS
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("  已启动（稍候用 rt status 确认）")
        return 0
    return 0


def _win_pid():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue"
                            " | Select-Object -First 1).OwningProcess"],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""


def cmd_restart(_args):
    if _is_linux() and _systemd_active():
        return _service("restart")
    _service("stop")
    import time
    time.sleep(2)
    return _service("start")


def cmd_logs(args):
    n = 50
    if args:
        try:
            n = max(1, int(args[0]))
        except Exception:
            pass
    cands = [os.path.join(HERE, "data", "logs", "panel.log"),
             os.path.join(HERE, "data", "logs", "app.log"),
             "/var/log/rt-panel.log"]
    log = next((p for p in cands if os.path.isfile(p)), None)
    if not log:
        print(_c("  未找到日志文件，尝试 systemd 日志：", YELLOW))
        if _is_linux():
            subprocess.run(["journalctl", "-u", SERVICE, "-n", str(n), "--no-pager"])
        return 0
    print(_c(f"  {log} 最后 {n} 行", DIM))
    with open(log, encoding="utf-8", errors="replace") as f:
        for line in f.read().splitlines()[-n:]:
            print("  " + line)
    return 0


def cmd_password(_args):
    import getpass
    from app.auth import hash_password, password_policy_error
    from app.database import execute, query
    u = input("  用户名 [admin]: ").strip() or "admin"
    p1 = getpass.getpass("  新密码: ")
    p2 = getpass.getpass("  再输一次: ")
    if p1 != p2:
        print(_c("  两次输入不一致。", RED))
        return 1
    err = password_policy_error(p1)
    if err:
        print(_c(f"  密码不符合要求：{err}", RED))
        return 1
    if not query("SELECT id FROM users WHERE username=?", (u,), one=True):
        print(_c(f"  用户 {u} 不存在。", RED))
        return 1
    execute("UPDATE users SET password_hash=? WHERE username=?", (hash_password(p1), u))
    print(_c(f"  已重置 {u} 的密码。", GREEN))
    return 0


def cmd_where(_args):
    print(f"  安装目录: {HERE}")
    print(f"  启动文件: {os.path.join(HERE, 'run.py')}")
    print(f"  数据目录: {os.path.join(HERE, 'data')}")
    print(f"  依赖目录: {DEPS if os.path.isdir(DEPS) else '（系统环境）'}")
    print(f"  运行方式: {'systemd ' + SERVICE if _is_linux() and _systemd_active() else '直接进程'}")
    return 0


MENU = [
    ("status", "查看面板状态", "版本 / 进程 / 端口 / 绑定"),
    ("check", "检查更新（查询官网）", "只查询，不改动"),
    ("update", "立即更新（命令行自救通道）", "下载→校验→替换→重启"),
    ("rollback", "回滚到上一个版本", "更新出问题时使用"),
    ("restart", "重启面板", ""),
    ("start", "启动面板", ""),
    ("stop", "停止面板", ""),
    ("logs", "查看日志", "rt logs 200 可指定行数"),
    ("password", "重置管理员密码", "交互输入新密码"),
    ("where", "显示安装路径与运行方式", ""),
    ("help", "显示帮助", ""),
]

CMDS = {
    "status": cmd_status, "check": cmd_check, "update": cmd_update, "rollback": cmd_rollback,
    "restart": cmd_restart, "start": lambda a: _service("start"), "stop": lambda a: _service("stop"),
    "logs": cmd_logs, "password": cmd_password, "where": cmd_where,
}


def show_help():
    ver, _ = _config()
    print(_c("云枢面板 命令行管理器", BOLD) + f"  （面板版本 {ver or '?'}）")
    print("  用法: rt <命令> [参数]    不带命令则进入交互菜单")
    print()
    for i, (name, title, note) in enumerate(MENU, 1):
        print(f"  {i:>2}. {name:<9} {title}{('  — ' + note) if note else ''}")
    print()
    print("  例: rt status | rt check | rt update | rt logs 100 | rt password")
    return 0


def menu():
    while True:
        ver, cfg = _config()
        print()
        print(_c("=" * 60, DIM))
        print(_c("  云枢面板 命令行管理器", BOLD) +
              f"   版本 {ver or '?'}   端口 {cfg.get('port', 8000)}"
              f"   {'运行中' if _port_listening(int(cfg.get('port', 8000))) else '未运行'}")
        print(_c("=" * 60, DIM))
        for i, (name, title, _note) in enumerate(MENU, 1):
            print(f"  {_c(str(i).rjust(2), CYAN)}. {title}  {_c('(' + name + ')', DIM)}")
        print(f"   {_c(' 0', CYAN)}. 退出")
        try:
            choice = input(_c("  请输入编号: ", BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in ("0", "q", "quit", "exit"):
            return 0
        if choice.isdigit() and 1 <= int(choice) <= len(MENU):
            name = MENU[int(choice) - 1][0]
            try:
                CMDS[name]([])
            except Exception as e:
                print(_c(f"  执行失败: {e}", RED))
            try:
                input(_c("  回车继续…", DIM))
            except (EOFError, KeyboardInterrupt):
                return 0
        else:
            print(_c("  无效编号。", YELLOW))


def main(argv):
    if not argv:
        return menu()
    cmd = argv[0].lower()
    if cmd in ("-h", "--help", "help"):
        return show_help()
    if cmd in ("-v", "--version", "version"):
        ver, _ = _config()
        print(ver or "unknown")
        return 0
    fn = CMDS.get(cmd)
    if not fn:
        # 代理给旧版脚本（rt.sh 里还有 port/entrance/ssl 等子命令，避免功能丢失）
        legacy = os.path.join(HERE, "rt.sh")
        if os.path.isfile(legacy):
            return subprocess.call(["bash", legacy] + argv)
        print(_c(f"  未知命令: {cmd}", RED))
        return show_help() or 1
    try:
        return fn(argv[1:]) or 0
    except KeyboardInterrupt:
        print()
        return 130
    except Exception as e:
        print(_c(f"  执行失败: {e}", RED))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
