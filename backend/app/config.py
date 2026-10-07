# Created by 小杜 on 2026/08

"""云枢面板 全局配置（JSON 持久化）。"""
import json
import os
import secrets
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
# 数据目录：支持 RT_DATA_DIR 环境变量迁移（默认 backend/data）
DATA_DIR = os.environ.get('RT_DATA_DIR') or os.path.join(BASE_DIR, 'data')
CERT_DIR = os.path.join(DATA_DIR, 'certs')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
WWWROOT_DIR = os.path.join(DATA_DIR, 'wwwroot')
LOG_DIR = os.path.join(DATA_DIR, 'logs')
TMP_DIR = os.path.join(DATA_DIR, 'tmp')

for d in (DATA_DIR, CERT_DIR, BACKUP_DIR, WWWROOT_DIR, LOG_DIR, TMP_DIR):
    os.makedirs(d, exist_ok=True)
    # P-01：面板数据目录收紧到 0700（里面是密钥、库、绑定与配置）
    try:
        os.chmod(d, 0o700)
    except Exception:
        pass

CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
SECRET_FILE = os.path.join(DATA_DIR, 'secret.key')

_lock = threading.RLock()

DEFAULTS = {
    'port': 8000,
    'bind_host': '0.0.0.0',
    'site_name': '云枢面板',
    'account_server': 'https://www.rt888.icu',
    'language': 'zh-CN',
    'theme': 'lightgold',
    'waf_crowd': True,
    'waf_telemetry': False,
    'session_hours': 24,
    'max_login_fails': 5,
    'lock_minutes': 10,
    'sample_interval': 5,
    'keep_raw_hours': 24,
    'keep_history_days': 90,
    'cpu_alert': 90,
    'mem_alert': 90,
    'disk_alert': 90,
    'allow_registration': False,
    'login_ip_whitelist': '',
    # 只有请求来源本身在此列表中时才解析 X-Forwarded-For，防止直连客户端伪造来源 IP。
    'trusted_proxies': '',
    'login_notify': 0,
    'hidden_menus': '',
    'security_entrance': '',
    'ssl_cert': '',
    'ssl_key': '',
    'panel_domain': '',
    'initialized': False,
}


def get_config() -> dict:
    with _lock:
        cfg = dict(DEFAULTS)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg.update(json.load(f))
            except Exception:
                pass
        # 官网地址/更新源锁定为官方域名（www.rt888.icu），面板内禁止修改；
        # 忽略配置文件中的旧值，仅厂商内部可用 RT_ACCOUNT_SERVER 环境变量覆盖（开发联调）
        cfg['account_server'] = os.environ.get(
            'RT_ACCOUNT_SERVER', DEFAULTS['account_server']).rstrip('/')
        return cfg


def save_config(updates: dict) -> dict:
    with _lock:
        cfg = get_config()
        cfg.update({k: v for k, v in updates.items() if k in DEFAULTS})
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return cfg


def get_jwt_secret() -> str:
    """JWT 签名密钥（0600，且修 P-01 时强制轮换一次）。

    旧实现用普通 open() 写文件：umask 0022 下是 0644，本机任何用户（含面板自建 FTP 用户、
    被入侵站点的 www-data）都能读到；叠加文件管理接口可远程读取 → 伪造管理员令牌。
    这里：① 用 os.open(..., 0o600) 创建；② 若发现密钥文件权限过宽或轮换标记缺失，
    直接重新生成（已泄露的密钥必须作废，代价是用户重新登录一次）。
    """
    marker = os.path.join(DATA_DIR, 'secret.rotated')
    with _lock:
        need_new = not os.path.exists(SECRET_FILE)
        if not need_new:
            # 权限位只在 POSIX 上有意义：Windows 的 st_mode 恒为 0o666，
            # 照搬判断会导致每次调用都重新生成密钥（用户反复被登出）。
            if os.name == 'posix':
                try:
                    mode = os.stat(SECRET_FILE).st_mode & 0o777
                    if mode & 0o077:
                        need_new = True
                except Exception:
                    pass
            # 一次性轮换：修 P-01 之前写下的密钥可能已被读走，首次启动后作废重签
            if not os.path.exists(marker):
                need_new = True
        if need_new:
            fd = os.open(SECRET_FILE, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(secrets.token_hex(32))
            try:
                os.chmod(SECRET_FILE, 0o600)
                with open(marker, 'w', encoding='utf-8') as f:
                    f.write('rotated')
            except Exception:
                pass
        with open(SECRET_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()


PANEL_VERSION = '2.0.0-rc3'
