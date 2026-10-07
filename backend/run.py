"""芮拓面板 启动入口。
开发环境依赖安装在 backend/.deps（sys.path 注入），
目标机器部署时依赖装在系统/虚拟环境中，requirements.txt 由安装脚本处理。
Windows 下若非管理员运行，将自动请求 UAC 提权后重启自身。
"""
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
DEPS_DIR = os.path.join(BASE_DIR, '.deps')
if os.path.isdir(DEPS_DIR):
    sys.path.insert(0, DEPS_DIR)

import uvicorn  # noqa: E402


def is_admin() -> bool:
    if sys.platform != 'win32':
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return True


def ensure_windows_elevation() -> bool:
    """Windows：非管理员时通过 UAC 弹窗提权重启自身。
    返回 True 表示当前进程可继续运行；False 表示已发起提权，当前进程应退出。
    环境变量 RT_NO_ELEVATE=1 可跳过（调试用）。
    """
    if sys.platform != 'win32' or is_admin():
        return True
    if os.environ.get('RT_NO_ELEVATE') == '1':
        print('[!] 提示: 当前以普通权限运行（RT_NO_ELEVATE=1），部分功能可能受限')
        return True
    print('[*] 检测到未以管理员运行，正在请求 UAC 提权（请在弹出的窗口点击"是"）...')
    try:
        script = (
            "Start-Process -FilePath '{}' -ArgumentList '{}' -Verb RunAs "
            "-WorkingDirectory '{}'"
        ).format(sys.executable, os.path.abspath(__file__), os.getcwd())
        subprocess.Popen(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-Command', script],
            creationflags=0x08000000 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
        return False
    except Exception as e:
        print(f'[!] 提权请求失败（{e}），将以普通权限运行，部分功能可能受限')
        return True


def main():
    from app.config import get_config

    cfg = get_config()
    host = cfg.get('bind_host', '0.0.0.0')
    port = int(cfg.get('port', 9988))
    ssl_kwargs = {}
    if cfg.get('ssl_cert') and cfg.get('ssl_key') \
            and os.path.isfile(cfg['ssl_cert']) and os.path.isfile(cfg['ssl_key']):
        ssl_kwargs = {'ssl_certfile': cfg['ssl_cert'], 'ssl_keyfile': cfg['ssl_key']}
        print(f'[*] 芮拓面板 启动: https://127.0.0.1:{port} （HTTPS 已启用）')
    else:
        print(f'[*] 芮拓面板 启动: http://127.0.0.1:{port}')
    uvicorn.run('app.main:app', host=host, port=port, log_level='info', **ssl_kwargs)


if __name__ == '__main__':
    if ensure_windows_elevation():
        main()
