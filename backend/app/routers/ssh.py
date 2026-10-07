# Created by 小杜 on 2026/08

"""SSH 管理：sshd_config 解析、就地修改与安全加固（自研）。"""
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request

from ..audit import audit
from ..auth import get_client_ip, require_perm
from ..utils.exec_utils import IS_WIN, run_cmd

router = APIRouter(prefix='/api/ssh', tags=['ssh'])

SSHD_CONFIG = '/etc/ssh/sshd_config'

_PARSE_KEYS = ('Port', 'PermitRootLogin', 'PasswordAuthentication',
               'PubkeyAuthentication', 'ListenAddress')


def _read_sshd_config() -> str:
    try:
        with open(SSHD_CONFIG, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except Exception:
        return ''


def _parse_sshd(text: str) -> dict:
    """解析生效（未注释）的配置项。"""
    raw = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        m = re.match(r'^([A-Za-z][A-Za-z0-9]*)\s+(.*)$', s)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key in _PARSE_KEYS:
            raw[key] = val
    port = raw.get('Port', '22')
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 22
    return {
        'port': port,
        'permit_root': raw.get('PermitRootLogin', 'yes'),
        'password_auth': raw.get('PasswordAuthentication', 'yes'),
        'pubkey_auth': raw.get('PubkeyAuthentication', 'yes'),
        'listen_address': raw.get('ListenAddress', '0.0.0.0'),
    }


def _service_status() -> str:
    for svc in ('ssh', 'sshd'):
        r = run_cmd(['systemctl', 'is-active', svc], timeout=10, shell=False)
        if r['code'] == 0:
            return r['stdout'].strip()
    return 'inactive'



# ---------------- P-21：SSH 生效值读写 ----------------
DROPIN_DIR = '/etc/ssh/sshd_config.d'
DROPIN_FILE = os.path.join(DROPIN_DIR, '00-rtpanel.conf')


def _sshd_binary() -> str:
    import shutil as _sh
    return _sh.which('sshd') or '/usr/sbin/sshd'


def _sshd_effective() -> dict:
    """用 sshd -T 读**生效**配置（含 Include 与 Match 之后的结果）。"""
    r = run_cmd([_sshd_binary(), '-T'], timeout=30, shell=False)
    if r["code"] != 0:
        return {}
    out = {}
    for line in (r["stdout"] or "").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            out[parts[0].strip().lower()] = parts[1].strip()
    return out


def _sshd_has_include() -> bool:
    try:
        with open(SSHD_CONFIG, "r", encoding="utf-8", errors="replace") as fh:
            return any(l.strip().lower().startswith("include") for l in fh)
    except Exception:
        return False


def _write_dropin(changes) -> bool:
    """写面板专属 drop-in（00- 前缀在 Include 里排最前 → 优先级最高）。"""
    try:
        os.makedirs(DROPIN_DIR, exist_ok=True)
        body = ["# 云枢面板 SSH 加固（P-21：写在 drop-in 里才能真正生效）"]
        body += [f"{k} {v}" for k, v in changes]
        with open(DROPIN_FILE, "w", encoding="utf-8") as fh:
            fh.write("\n".join(body) + "\n")
        os.chmod(DROPIN_FILE, 0o600)
        return True
    except Exception:
        return False

def _restart_ssh() -> bool:
    for svc in ('ssh', 'sshd'):
        r = run_cmd(['systemctl', 'restart', svc], timeout=60, shell=False)
        if r['code'] == 0:
            return True
    return False


@router.get('/status')
def ssh_status(user: dict = Depends(require_perm('ssh:view'))):
    return ssh_status_core()


def ssh_status_core() -> dict:
    """SSH 状态核心（AI 智能体与路由共用）。"""
    if IS_WIN:
        return {'supported': False, 'service': 'unsupported', 'config': {},
                'message': 'Windows 暂不支持 SSH 管理'}
    text = _read_sshd_config()
    if not text:
        return {'supported': True, 'service': _service_status(), 'config': {},
                'error': '无法读取 /etc/ssh/sshd_config（可能未安装 OpenSSH）'}
    return {'supported': True, 'service': _service_status(), 'config': _parse_sshd(text)}


@router.put('/config')
def ssh_config_update(body: dict, request: Request,
                      user: dict = Depends(require_perm('ssh:manage'))):
    if IS_WIN:
        raise HTTPException(status_code=400, detail='Windows 暂不支持 SSH 管理')
    if not os.path.isfile(SSHD_CONFIG):
        raise HTTPException(status_code=400, detail='未找到 /etc/ssh/sshd_config（请先安装 OpenSSH）')
    try:
        port = int(body.get('port', 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='端口无效')
    if port < 22 or port > 65535:
        raise HTTPException(status_code=400, detail='端口需在 22-65535 之间')

    def _yn(key: str) -> str:
        v = str(body.get(key, 'yes')).strip().lower()
        if v not in ('yes', 'no'):
            raise HTTPException(status_code=400, detail=f'{key} 仅支持 yes/no')
        return v

    permit_root = _yn('permit_root')
    password_auth = _yn('password_auth')
    pubkey_auth = _yn('pubkey_auth')

    # 先备份，失败即止
    bak = SSHD_CONFIG + '.rtbak'
    try:
        import shutil
        shutil.copy2(SSHD_CONFIG, bak)
    except Exception:
        raise HTTPException(status_code=400, detail='备份 sshd_config 失败（需 root 权限）')

    # P-21：改成写 drop-in（00- 前缀 = Include 里最先被读到 = 优先级最高），
    # 否则我们追加到主文件末尾的值会被 drop-in 里的旧值压过去，"加固成功"是假的。
    changes = (('Port', str(port)), ('PermitRootLogin', permit_root),
               ('PasswordAuthentication', password_auth), ('PubkeyAuthentication', pubkey_auth))
    change_keys = {k for k, _ in changes}
    if not _sshd_has_include():
        raise HTTPException(status_code=400,
                            detail="sshd_config 缺少 Include 指令，无法用 drop-in 安全加固；请先确认 /etc/ssh/sshd_config 顶部包含 Include /etc/ssh/sshd_config.d/*.conf")
    if not _write_dropin(changes):
        raise HTTPException(status_code=400, detail="写入 SSH drop-in 失败（需 root 权限）")
    try:
        with open(SSHD_CONFIG, 'r', encoding='utf-8', errors='replace') as fh:
            lines = fh.read().splitlines()
        kept = []
        in_match = False
        for ln in lines:
            if re.match(r'^\s*Match\s', ln, re.I):
                in_match = True
            m = re.match(r'^\s*#?\s*([A-Za-z][A-Za-z0-9]*)\s+', ln)
            # Match 块内的同名键不动（那是按用户/来源的定向策略）
            if m and m.group(1) in change_keys and not in_match:
                continue
            kept.append(ln)
        with open(SSHD_CONFIG, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(kept) + '\n')
    except Exception as e:
        try:
            shutil.copy2(bak, SSHD_CONFIG)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f'改写 sshd_config 失败，已回滚: {e}')

    # sshd -t 校验；失败则恢复备份并 400
    import shutil as _shutil
    sshd_bin = _shutil.which('sshd') or '/usr/sbin/sshd'
    t = run_cmd([sshd_bin, '-t'], timeout=30, shell=False)
    if t['code'] != 0:
        try:
            shutil.copy2(bak, SSHD_CONFIG)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail='配置校验失败，已自动回滚：'
                            + ((t['stderr'] or t['stdout']) or '')[:200])

    restarted = _restart_ssh()
    # P-21：读**生效值**复核，只有真的生效才算成功（原实现只看"服务重启了"）
    eff = _sshd_effective()
    expect = {k.lower(): v for k, v in changes}
    mismatch = {k: (expect[k], eff.get(k)) for k in expect if eff and eff.get(k) != expect[k]}
    if mismatch:
        raise HTTPException(status_code=400,
                            detail=f"SSH 配置未真正生效（期望/实际）：{mismatch}。已保留 drop-in，请检查其它 drop-in 或 Match 块")
    audit(user['username'], get_client_ip(request), 'ssh_config',
          f'修改 SSH 配置：端口 {port}，Root登录 {permit_root}，'
          f'密码认证 {password_auth}，公钥认证 {pubkey_auth}', 'warning')
    if restarted:
        return {'ok': True, 'message': '已重启 SSH 服务', 'restarted': True}
    return {'ok': True, 'restarted': False,
            'message': '配置已保存并通过校验，但 SSH 服务重启失败，请手动重启'}


@router.get('/hardening')
def ssh_hardening(user: dict = Depends(require_perm('ssh:view'))):
    if IS_WIN:
        return {'supported': False, 'list': []}
    text = _read_sshd_config()
    cfg = _parse_sshd(text) if text else {
        'port': 22, 'permit_root': 'yes', 'password_auth': 'yes',
        'pubkey_auth': 'yes', 'listen_address': '0.0.0.0'}
    checks = []

    pr = str(cfg['permit_root']).lower()
    if pr == 'no':
        checks.append({'key': 'root_login', 'title': '禁止 Root 登录', 'status': 'ok',
                       'desc': 'PermitRootLogin=no', 'suggest': ''})
    elif pr in ('prohibit-password', 'without-password'):
        checks.append({'key': 'root_login', 'title': 'Root 仅密钥登录', 'status': 'ok',
                       'desc': f'PermitRootLogin={cfg["permit_root"]}', 'suggest': ''})
    else:
        checks.append({'key': 'root_login', 'title': 'Root 允许密码登录', 'status': 'danger',
                       'desc': f'PermitRootLogin={cfg["permit_root"]}',
                       'suggest': '建议设为 no 或 prohibit-password'})

    pa = str(cfg['password_auth']).lower()
    if pa == 'no':
        checks.append({'key': 'password_auth', 'title': '已关闭密码登录', 'status': 'ok',
                       'desc': '仅允许密钥登录，更安全', 'suggest': ''})
    else:
        checks.append({'key': 'password_auth', 'title': '开启密码登录', 'status': 'warn',
                       'desc': '存在暴力破解风险', 'suggest': '建议关闭并改用密钥登录'})

    pk = str(cfg['pubkey_auth']).lower()
    if pk == 'yes':
        checks.append({'key': 'pubkey_auth', 'title': '已启用公钥认证', 'status': 'ok',
                       'desc': '支持密钥登录', 'suggest': ''})
    else:
        checks.append({'key': 'pubkey_auth', 'title': '未启用公钥认证', 'status': 'warn',
                       'desc': '无法使用密钥登录', 'suggest': '建议开启公钥认证'})

    if cfg['port'] == 22:
        checks.append({'key': 'port', 'title': '使用默认端口 22', 'status': 'warn',
                       'desc': '易被端口扫描与爆破', 'suggest': '建议改为 10000-65535 间非常用端口'})
    else:
        checks.append({'key': 'port', 'title': '使用非默认端口', 'status': 'ok',
                       'desc': f'当前端口 {cfg["port"]}', 'suggest': ''})

    fb_installed = run_cmd('command -v fail2ban-client >/dev/null 2>&1',
                           timeout=10, shell=True)['code'] == 0
    if fb_installed:
        fb_active = run_cmd('systemctl is-active fail2ban 2>/dev/null',
                            timeout=10, shell=True)['stdout'].strip() == 'active'
        if fb_active:
            checks.append({'key': 'fail2ban', 'title': 'fail2ban 已启用', 'status': 'ok',
                           'desc': '自动封禁爆破来源 IP', 'suggest': ''})
        else:
            checks.append({'key': 'fail2ban', 'title': 'fail2ban 未运行', 'status': 'warn',
                           'desc': '已安装但服务未启动', 'suggest': '执行 systemctl enable --now fail2ban'})
    else:
        checks.append({'key': 'fail2ban', 'title': '未安装 fail2ban', 'status': 'info',
                       'desc': '缺少爆破防护', 'suggest': '建议安装 fail2ban 防 SSH 爆破'})

    la = str(cfg['listen_address']).strip()
    if la in ('0.0.0.0', '::', ''):
        checks.append({'key': 'listen_address', 'title': '监听所有地址', 'status': 'info',
                       'desc': f'ListenAddress={la or "默认"}',
                       'suggest': '若仅内网使用，可限制监听来源 IP'})
    else:
        checks.append({'key': 'listen_address', 'title': '已限制监听地址', 'status': 'ok',
                       'desc': f'ListenAddress={la}', 'suggest': ''})

    return {'supported': True, 'list': checks}
