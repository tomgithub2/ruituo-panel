"""云枢面板 · 网页初始化向导。

安装完成后，首次在浏览器打开面板时完成：
1. 校验安装器打印的「初始化令牌」（防陌生人抢先初始化）；
2. 创建管理员账号（用户名 + 强密码，PBKDF2 存储）；
3. 可选：立即绑定官网账户（rt888.icu），核心功能免费、VIP 专属功能需兑换码升级。

安全设计：
- 令牌使用高强度随机值，由安装器生成写入 data/setup_token.txt 并打印；
  面板启动时若缺失会自动补生成（打印到控制台日志）。
- 初始化接口按 IP 限流：5 次失败锁定 10 分钟。
- 初始化完成后令牌文件立即销毁，接口返回 409。
"""
import os
import re
import secrets
import threading
import time

from fastapi import APIRouter, HTTPException, Request

from ..audit import audit
from ..auth import hash_password, password_policy_error
from ..binding import bind as binding_bind
from ..binding import server_url
from ..config import DATA_DIR
from ..database import execute, now, query
from ..hardware import machine_id

router = APIRouter(prefix='/api/setup', tags=['setup'])

TOKEN_FILE = os.path.join(DATA_DIR, 'setup_token.txt')

_lock = threading.Lock()
_fail_map = {}  # ip -> (count, ts)


def is_initialized() -> bool:
    """是否已完成初始化（存在至少一个用户）。"""
    try:
        return bool(query('SELECT id FROM users LIMIT 1', one=True))
    except Exception:
        return False


def setup_token() -> str:
    """读取或生成初始化令牌（仅未初始化时有效）。"""
    try:
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            tok = f.read().strip()
        if tok:
            return tok
    except OSError:
        pass
    tok = secrets.token_hex(32)
    try:
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(tok)
    except OSError:
        pass
    return tok


def clear_token():
    try:
        os.remove(TOKEN_FILE)
    except OSError:
        pass


def _locked(ip: str) -> bool:
    with _lock:
        count, ts = _fail_map.get(ip, (0, 0))
        if count >= 5 and (time.time() - ts) < 600:
            return True
    return False


def _fail(ip: str):
    with _lock:
        count, _ = _fail_map.get(ip, (0, 0))
        _fail_map[ip] = (count + 1, time.time())


def _reset(ip: str):
    with _lock:
        _fail_map.pop(ip, None)


@router.get('/status')
def status():
    """初始化状态（免鉴权，供登录页跳转判断）。"""
    init = is_initialized()
    return {
        'initialized': init,
        'need_token': not init,
        'site_url': server_url(),
        'machine_id': machine_id() if not init else '',
        'version': '1.0.0',
    }


@router.post('/init')
def do_init(body: dict, request: Request):
    """网页端完成初始配置：创建管理员 + 可选官网账户绑定。"""
    if is_initialized():
        raise HTTPException(status_code=409, detail='面板已完成初始化，请直接登录')
    ip = request.client.host if request.client else ''
    if _locked(ip):
        raise HTTPException(status_code=429, detail='尝试次数过多，请 10 分钟后再试')

    token = str(body.get('token', '')).strip()
    if not token or not secrets.compare_digest(token, setup_token()):
        _fail(ip)
        raise HTTPException(status_code=400, detail='初始化令牌错误')

    username = str(body.get('username', '')).strip()
    password = str(body.get('password', ''))
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]{2,31}$', username):
        raise HTTPException(status_code=400, detail='用户名需以字母开头，3-32 位字母、数字、下划线')
    policy_error = password_policy_error(password)
    if policy_error:
        raise HTTPException(status_code=400, detail=policy_error)

    pw_hash = hash_password(password)
    try:
        execute(
            'INSERT INTO users (username, password_hash, role, email, status, created_at) '
            'VALUES (?,?,?,?,?,?)',
            (username, pw_hash, 'admin', '', 1, now()))
    except Exception:
        raise HTTPException(status_code=409, detail='用户名已存在，请更换')

    audit(username, ip, 'setup_init', '网页初始化完成，创建管理员账号')

    # 可选：立即绑定官网账户（rt888.icu）
    bind_result = None
    if body.get('bind'):
        account = str(body.get('site_account', '')).strip()
        site_password = str(body.get('site_password', ''))
        if account and site_password:
            bind_result = binding_bind(account, site_password)

    clear_token()
    _reset(ip)
    return {'ok': True, 'username': username, 'bind': bind_result,
            'message': '初始化完成，请使用新账号登录'}
