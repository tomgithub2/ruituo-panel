"""网站管理：静态站点 / 反向代理 / PHP，生成 Nginx 或 Caddy 配置。"""
import os
import re
import shutil
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from ..audit import audit
from ..auth import get_client_ip, require_feature, require_perm
from ..config import BACKUP_DIR, WWWROOT_DIR
from ..database import execute, now, query
from ..ownership import assert_touch, owner_where
from ..utils.exec_utils import IS_WIN, run_cmd

router = APIRouter(prefix='/api/websites', tags=['websites'],
                   dependencies=[Depends(require_feature('websites'))])


# 一键部署应用目录（官方稳定下载源，URL 固定不可由用户输入）
SITE_APPS = {
    'wordpress': {'name': 'WordPress', 'desc': '全球最流行的博客与建站程序（需 PHP+MySQL）',
                  'url': 'https://wordpress.org/latest.zip', 'kind': 'zip',
                  'php': True, 'db': True},
    'wp-zh': {'name': 'WordPress 中文版', 'desc': 'WordPress 官方简体中文版（需 PHP+MySQL）',
              'url': 'https://cn.wordpress.org/latest-zh_CN.zip', 'kind': 'zip',
              'php': True, 'db': True},
    'typecho': {'name': 'Typecho', 'desc': '轻量高效的开源博客程序（需 PHP+MySQL）',
                'url': 'https://github.com/typecho/typecho/releases/download/v1.2.1/1.2.1.tar.gz',
                'kind': 'targz', 'php': True, 'db': True},
}


def _php_fpm_sock() -> str:
    """探测本机 PHP-FPM socket；找不到返回空串（应用照常部署，仅提示 PHP 暂不可解析）。"""
    if IS_WIN:
        return ''
    import glob as _glob
    for sock in _glob.glob('/run/php/*.sock') + _glob.glob('/var/run/php/*.sock'):
        if os.path.exists(sock):
            return sock
    return ''


# 站点目录绝对不能指向这些位置（nginx 会以 root 读取并对外提供）
_FORBIDDEN_ROOT_DIRS = ('/etc', '/root', '/proc', '/sys', '/dev', '/boot', '/var/lib', '/usr')


def _safe_site_root(value: object) -> str:
    """站点根目录校验（P-08）。

    原实现只做字符黑名单：`{"root":"/"}` 能通过，于是启用站点后**未认证**就能
    读 `/etc/passwd`、面板 `backend/data/secret.key`（与 P-01 同一条链）。
    现在强制落在 WWWROOT_DIR 内，并显式拒绝系统目录。
    """
    raw = str(value or '').strip()
    if not raw:
        raise HTTPException(status_code=400, detail='站点目录不能为空')
    if any(ch in raw for ch in ('\x00', '\n', '\r', '\t', '\v', '\f', '$', ';', '{', '}', '"', "'")):
        raise HTTPException(status_code=400, detail='站点目录包含不安全字符')
    # 相对路径按 WWWROOT 解析（前端允许只填目录名），绝对路径原样校验
    candidate = raw if os.path.isabs(raw) else os.path.join(WWWROOT_DIR, raw)
    root = os.path.realpath(os.path.abspath(candidate))
    base = os.path.realpath(WWWROOT_DIR)
    for bad in _FORBIDDEN_ROOT_DIRS:
        if root == bad or root.startswith(bad + os.sep):
            raise HTTPException(status_code=400, detail=f'站点目录不能位于 {bad}')
    try:
        inside = os.path.commonpath([base, root]) == base
    except ValueError:
        inside = False
    if not inside:
        raise HTTPException(status_code=400, detail=f'站点目录必须位于 {base} 内')
    return root


PROXY_TARGET_RE = re.compile(
    r'^https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[^\s\'"{};$,]*)?$')


def _safe_proxy_target(value: object) -> str:
    """反向代理目标白名单（P-09）。

    原来只挡 ; { } " ' 与空白，`$` 能过 —— 而 nginx 会展开变量：
    `proxy_pass http://$http_host/` 让任意客户端用 Host 头把服务器变成 SSRF/开放代理
    （打内网、打云元数据 169.254.169.254、回环探面板自身端口都行，且利用阶段无需凭据）。
    """
    target = str(value or '').strip()
    parsed = urlparse(target)
    if (parsed.scheme not in ('http', 'https') or not parsed.netloc or
            any(ch.isspace() for ch in target) or any(ch in target for ch in (';', '{', '}', '"', "'", '$'))):
        raise HTTPException(status_code=400, detail='反向代理地址必须为有效的 HTTP(S) URL')
    if not PROXY_TARGET_RE.match(target):
        raise HTTPException(status_code=400, detail='反向代理地址包含不允许的字符')
    host = (parsed.hostname or '').strip()
    if not host:
        raise HTTPException(status_code=400, detail='反向代理地址缺少主机名')
    # 禁止指向内网/回环/链路本地（域名先解析再判定）
    import ipaddress
    import socket
    candidates = []
    try:
        candidates.append(ipaddress.ip_address(host))
    except ValueError:
        try:
            for info in socket.getaddrinfo(host, None):
                candidates.append(ipaddress.ip_address(info[4][0]))
        except Exception:
            pass
    for ip in candidates:
        if (not ip.is_global) or ip.is_loopback or ip.is_link_local or ip.is_private:
            raise HTTPException(status_code=400,
                                detail=f'反向代理目标不能指向内网/本机地址：{ip}')
    return target


def _find_engine() -> str:
    for name, cmd in (('nginx', 'nginx -v 2>&1'), ('caddy', 'caddy version'),
                      ('apache', 'httpd -v 2>&1 || apache2 -v 2>&1')):
        r = run_cmd(cmd, timeout=10, shell=True)
        if r['code'] == 0 or 'nginx' in (r['stderr'] + r['stdout']).lower():
            if name == 'nginx':
                return 'nginx'
            return name if r['code'] == 0 else ''
    return ''


def _nginx_log_path(logtype: str, domain: str = '') -> str:
    """定位 Nginx 访问/错误日志文件（跨平台）；带域名时按站点独立日志。"""
    if IS_WIN:
        roots = [r'C:\Tengine\logs', r'C:\nginx\logs',
                 os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Tengine', 'logs'),
                 os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'nginx', 'logs')]
        base = next((d for d in roots if os.path.isdir(d)), roots[0])
    else:
        base = '/var/log/nginx'
    fname = f'{domain}.{logtype}.log' if domain else f'{logtype}.log'
    return os.path.join(base, fname)


def _tail_file(path: str, n: int) -> str:
    """自研文件尾部读取：seek 到末尾按块倒读，避免加载超大日志。"""
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return ''
            block = 8192
            data = b''
            pos = size
            while pos > 0 and data.count(b'\n') < n:
                step = min(block, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
            return data.decode('utf-8', 'ignore')
    except Exception:
        return ''


@router.get('/list')
def site_list(user: dict = Depends(require_perm('websites:view'))):
    # P-25h：非管理员只看自己创建的站点（历史无主站点保持可见）
    _w, _p = owner_where(user)
    wzList = query(f'SELECT * FROM websites WHERE {_w} ORDER BY id DESC', tuple(_p))
    for oneSite in wzList:
        oneSite['running'] = _site_running(oneSite)
    return {'list': wzList, 'engine': _find_engine()}


def _site_running(site: dict) -> bool:
    if site['engine'] == 'nginx' and site['type'] == 'static':
        # 拿 nginx -T 全文 grep 判断站点在不在跑，土但好用
        # return bool(os.popen('pgrep nginx').read())  # 已弃用（换机器误报），保留参考
        domain = str(site.get('domain') or '')
        if not re.match(r'^[a-z0-9\.\-\*]+$', domain):
            return False
        # §0.2：`nginx -T | grep -q` 改成取回配置文本后在 Python 里判断
        chk = run_cmd(['nginx', '-T'], timeout=20, shell=False)
        return f'server_name {domain};' in ((chk['stdout'] or '') + (chk['stderr'] or ''))
    return False


@router.get('/env')
def site_env(user: dict = Depends(require_perm('websites:view'))):
    """建站环境检测：MySQL/FTP 是否可用（不可用则前端禁用对应一键创建选项）。"""
    from .databases import _mysql_cmd
    mysql_ok = run_cmd(_mysql_cmd('-e "SELECT VERSION();"'), timeout=10)['code'] == 0
    ftp_ok = run_cmd('vsftpd -version 2>&1', timeout=10, shell=True)['code'] == 0
    nginx_ok = run_cmd('nginx -v 2>&1', timeout=10, shell=True)['code'] == 0
    return {'mysql': mysql_ok, 'ftp': ftp_ok, 'nginx': nginx_ok,
            'mysql_msg': '' if mysql_ok else '未安装 MySQL，请先在「软件商店」安装后可勾选',
            'ftp_msg': '' if ftp_ok else '未安装 FTP 服务，请先在「软件商店」安装后可勾选',
            'nginx_msg': '' if nginx_ok else '未检测到 Nginx，网站配置将无法生效'}


@router.post('/create')
def site_create(body: dict, request: Request, user: dict = Depends(require_perm('websites:manage'))):
    domain = str(body.get('domain', '')).strip().lower()
    stype = str(body.get('type', 'static'))
    engine = str(body.get('engine', 'nginx'))
    port = int(body.get('port', 80))
    root = str(body.get('root', '')).strip()
    if not re.match(r'^[a-z0-9\.\-\*]+$', domain):
        raise HTTPException(status_code=400, detail='域名无效')
    if query('SELECT id FROM websites WHERE domain=?', (domain,), one=True):
        raise HTTPException(status_code=409, detail='该域名已存在')
    if not root:
        root = os.path.join(WWWROOT_DIR, domain)
    root = _safe_site_root(root)
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail='端口无效')
    if stype not in ('static', 'proxy', 'php') or engine not in ('nginx', 'caddy', 'apache'):
        raise HTTPException(status_code=400, detail='站点类型或 Web 引擎无效')
    os.makedirs(root, exist_ok=True)
    # 静态站点生成默认首页
    index = os.path.join(root, 'index.html')
    if not os.path.isfile(index):
        with open(index, 'w', encoding='utf-8') as f:
            f.write(f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{domain}</title>
<style>body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui;background:#0f1420;color:#dfe6f5}}h1{{font-weight:500}}
span{{color:#409eff}}</style></head><body><h1>欢迎访问 <span>{domain}</span></h1>
<p style="position:fixed;bottom:16px;color:#5b6b85">由 云枢面板 运维面板托管</p></body></html>''')
    target = _safe_proxy_target(body.get('target', '')) if stype == 'proxy' else ''
    # 一键建站：可选同时创建同名 MySQL 数据库 + FTP 账号
    db_info = None
    if body.get('with_db'):
        db_info = _auto_create_db(domain, body.get('db_name', ''))
    ftp_info = None
    if body.get('with_ftp'):
        ftp_info = _auto_create_ftp(domain, root, body.get('ftp_user', ''))
    sid = execute(
        'INSERT INTO websites (domain,root,port,type,engine,config,status,created_at) '
        'VALUES (?,?,?,?,?,?,?,?)',
        (domain, root, port, stype, engine,
         target if stype == 'proxy' else '', 0, now()))
    execute('UPDATE websites SET owner_id=? WHERE id=(SELECT MAX(id) FROM websites)', (user['id'],))   # P-25h：记录归属
    _render_nginx()
    audit(user['username'], get_client_ip(request), 'website_create', f'创建网站 {domain} ({stype})')
    return {'id': sid, 'db': db_info, 'ftp': ftp_info}


# ---------------------------------------------------------------- 一键部署
@router.get('/apps')
def site_apps(user: dict = Depends(require_perm('websites:view'))):
    return {'apps': [{'key': k, **v} for k, v in SITE_APPS.items()]}


@router.post('/deploy-app')
def site_deploy_app(body: dict, request: Request,
                    user: dict = Depends(require_perm('websites:manage'))):
    """一键部署：选程序 → 填域名 → 自动下载/安全解压/建站/建库/建 FTP。"""
    import urllib.request as _urllib
    from .files import _extract_tar_safely, _extract_zip_safely
    domain = str(body.get('domain', '')).strip().lower()
    app_key = str(body.get('app', '')).strip()
    port = int(body.get('port', 80))
    app = SITE_APPS.get(app_key)
    if not re.match(r'^[a-z0-9\.\-\*]+$', domain):
        raise HTTPException(status_code=400, detail='域名无效')
    if not app:
        raise HTTPException(status_code=400, detail='未知应用')
    if query('SELECT id FROM websites WHERE domain=?', (domain,), one=True):
        raise HTTPException(status_code=409, detail='该域名已存在')
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail='端口无效')
    root = os.path.join(WWWROOT_DIR, domain)
    os.makedirs(root, exist_ok=True)

    # 1. 下载（固定目录 URL，用户不可控）
    from ..config import TMP_DIR
    ts = str(int(now()))
    tmp_pkg = os.path.join(TMP_DIR, f'app_{app_key}_{ts}.'
                            + ('zip' if app['kind'] == 'zip' else 'tar.gz'))
    tmp_ext = os.path.join(TMP_DIR, f'app_x_{ts}')
    req = _urllib.request.Request(app['url'], headers={'User-Agent': 'RTPanel-Deploy/1.0'})
    try:
        with _urllib.request.urlopen(req, timeout=180) as resp, open(tmp_pkg, 'wb') as fh:
            shutil.copyfileobj(resp, fh)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'应用下载失败: {e}')

    # 2. 安全解压（防穿越/符号链接，复用文件管理安全解压器）
    os.makedirs(tmp_ext, exist_ok=True)
    try:
        if app['kind'] == 'zip':
            _extract_zip_safely(tmp_pkg, tmp_ext)
        else:
            _extract_tar_safely(tmp_pkg, tmp_ext, 'r:gz')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'解压失败: {e}')

    # 3. 包内单目录上移（wordpress/typecho 均包一个顶层目录）
    children = [p for p in os.listdir(tmp_ext) if not p.startswith('.')]
    if len(children) == 1 and os.path.isdir(os.path.join(tmp_ext, children[0])):
        inner = os.path.join(tmp_ext, children[0])
        for item in os.listdir(inner):
            shutil.move(os.path.join(inner, item), os.path.join(root, item))
    else:
        for item in children:
            shutil.move(os.path.join(tmp_ext, item), os.path.join(root, item))

    # 4. 一键建库/建 FTP（可选）
    db_info = ftp_info = None
    if body.get('with_db') and app.get('db'):
        db_info = _auto_create_db(domain, body.get('db_name', ''))
    if body.get('with_ftp'):
        ftp_info = _auto_create_ftp(domain, root, body.get('ftp_user', ''))

    # 5. 建站（PHP 程序用 php 类型自动渲染 PHP-FPM 解析）
    stype = 'php' if app.get('php') else 'static'
    sid = execute(
        'INSERT INTO websites (domain,root,port,type,engine,config,status,created_at) '
        'VALUES (?,?,?,?,?,?,?,?)',
        (domain, root, port, stype, 'nginx', '', 0, now()))
    execute('UPDATE websites SET owner_id=? WHERE id=(SELECT MAX(id) FROM websites)', (user['id'],))   # P-25h：记录归属
    execute('INSERT OR IGNORE INTO site_settings (site_id) VALUES (?)', (sid,))
    _render_nginx()
    php_sock = _php_fpm_sock() if stype == 'php' else ''
    audit(user['username'], get_client_ip(request), 'website_deploy_app',
          f'一键部署 {app["name"]} → {domain}', 'warning')
    try:
        os.remove(tmp_pkg)
        shutil.rmtree(tmp_ext, ignore_errors=True)
    except Exception:
        pass
    return {'id': sid, 'db': db_info, 'ftp': ftp_info, 'php_sock': php_sock,
            'msg': f'{app["name"]} 部署完成'
                   + ('' if php_sock else '（未检测到 PHP-FPM，PHP 暂不可解析：请先安装 PHP）')}


# ---------------------------------------------------------------- 网站备份（一键备份）
@router.get('/backups')
def site_backups(user: dict = Depends(require_perm('websites:view'))):
    backup_dir = os.path.join(BACKUP_DIR, 'websites')
    if not os.path.isdir(backup_dir):
        return {'list': []}
    items = []
    for fn in sorted(os.listdir(backup_dir), reverse=True):
        fp = os.path.join(backup_dir, fn)
        if os.path.isfile(fp):
            items.append({'name': fn, 'size': os.path.getsize(fp),
                          'mtime': os.path.getmtime(fp)})
    return {'list': items}


@router.post('/{sid}/backup')
def site_backup(sid: int, request: Request,
                user: dict = Depends(require_perm('websites:manage'))):
    """一键备份网站目录为 zip（不走 shell，路径可含任意字符）。"""
    site = query('SELECT * FROM websites WHERE id=?', (sid,), one=True)
    assert_touch(user, site, '该站点')   # P-25h
    if not site:
        raise HTTPException(status_code=404, detail='网站不存在')
    root = os.path.realpath(site['root'])
    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail='站点目录不存在')
    backup_dir = os.path.join(BACKUP_DIR, 'websites')
    os.makedirs(backup_dir, exist_ok=True)
    name = f'{site["domain"]}_{time.strftime("%Y%m%d_%H%M%S")}.zip'
    out = os.path.join(backup_dir, name)
    import zipfile
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ('node_modules', '.git')]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                zf.write(fp, os.path.relpath(fp, root))
    audit(user['username'], get_client_ip(request), 'website_backup',
          f'备份网站 {site["domain"]}', 'warning')
    return {'ok': True, 'name': name, 'size': os.path.getsize(out)}


@router.get('/backups/{name}/download')
def site_backup_download(name: str, user: dict = Depends(require_perm('websites:view'))):
    from fastapi.responses import FileResponse
    if not re.match(r'^[a-zA-Z0-9_.\-]{1,200}$', name):
        raise HTTPException(status_code=400, detail='备份名无效')
    fp = os.path.join(BACKUP_DIR, 'websites', name)
    if not os.path.isfile(fp):
        raise HTTPException(status_code=404, detail='备份不存在')
    return FileResponse(fp, filename=name)


@router.delete('/backups/{name}')
def site_backup_delete(name: str, user: dict = Depends(require_perm('websites:manage'))):
    if not re.match(r'^[a-zA-Z0-9_.\-]{1,200}$', name):
        raise HTTPException(status_code=400, detail='备份名无效')
    fp = os.path.join(BACKUP_DIR, 'websites', name)
    if not os.path.isfile(fp):
        raise HTTPException(status_code=404, detail='备份不存在')
    os.remove(fp)
    return {'ok': True}


def _auto_create_db(domain: str, db_name: str = '') -> dict:
    """随建站自动创建同名 MySQL 数据库与账号；MySQL 不可用则返回错误说明。"""
    from .databases import _mysql_cmd
    import secrets as _secrets
    if db_name:
        dbname = re.sub(r'[^a-z0-9_]', '_', db_name.lower())[:40].strip('_')
    else:
        dbname = 'db_' + re.sub(r'[^a-z0-9_]', '_', domain)[:40].strip('_')
    if not dbname:
        dbname = 'db_' + re.sub(r'[^a-z0-9_]', '_', domain)[:40].strip('_')
    dbuser = dbname[:10] + '_' + _secrets.token_hex(2)
    dbpass = _secrets.token_hex(8)
    r = run_cmd(_mysql_cmd('-e "SELECT VERSION();"'), timeout=15)
    if r['code'] != 0:
        return {'ok': False, 'error': '未检测到可用 MySQL（请在「软件商店」安装）'}
    r1 = run_cmd(_mysql_cmd(f'-e "CREATE DATABASE IF NOT EXISTS `{dbname}` DEFAULT CHARACTER SET utf8mb4;"'),
                 timeout=30)
    if r1['code'] != 0:
        return {'ok': False, 'error': (r1['stderr'] or '创建数据库失败')[:200]}
    r2 = run_cmd(_mysql_cmd(
        f'-e "CREATE USER IF NOT EXISTS \'{dbuser}\'@\'localhost\' IDENTIFIED BY \'{dbpass}\';'
        f'GRANT ALL PRIVILEGES ON `{dbname}`.* TO \'{dbuser}\'@\'localhost\';FLUSH PRIVILEGES;"'),
        timeout=30)
    if r2['code'] != 0:
        return {'ok': False, 'error': (r2['stderr'] or '创建数据库账号失败')[:200]}
    return {'ok': True, 'db': dbname, 'user': dbuser, 'password': dbpass,
            'host': 'localhost'}


def _auto_create_ftp(domain: str, root: str, ftp_user: str = '') -> dict:
    """随建站自动创建 FTP 账号（vsftpd 系统用户，目录指向站点根目录）。"""
    import secrets as _secrets
    if IS_WIN:
        return {'ok': False, 'error': 'Windows 暂不支持自动创建 FTP（可在软件商店安装后手动配置）'}
    r = run_cmd('vsftpd -version 2>&1', timeout=10, shell=True)
    if r['code'] != 0 and 'vsftpd' not in (r['stdout'] + r['stderr']).lower():
        return {'ok': False, 'error': '未检测到 vsftpd（请在「软件商店」安装 FTP 服务）'}
    # 名字统一走 FTP 前缀（P-02：避免撞上 root/www-data 等系统账号）
    if ftp_user:
        user = re.sub(r'[^a-z0-9_]', '_', ftp_user.lower())[:20].strip('_') or \
            ('rtftp_' + re.sub(r'[^a-z0-9_]', '_', domain)[:14].strip('_'))
    else:
        user = 'rtftp_' + re.sub(r'[^a-z0-9_]', '_', domain)[:14].strip('_')
    if not user.startswith('rtftp_'):
        user = 'rtftp_' + user.lstrip('_')[:14]
    pwd = _secrets.token_hex(6)
    # 复用 FTP 模块的核心逻辑：系统账号占用检查 + useradd 返回码检查 + uid 复核都在那里，
    # 早先这里各写一遍（正是 P-02：可以借建站接口把 root 口令改掉并回显）。
    from .ftp import ftp_create_core
    created = ftp_create_core(user, root, pwd, note=f'建站自动创建（{domain}）')
    if not created.get('ok'):
        return {'ok': False, 'error': created.get('error', 'FTP 账号创建失败')}
    return {'ok': True, 'user': user, 'password': pwd, 'dir': root}


@router.post('/{sid}/action')
def site_action(sid: int, body: dict, request: Request,
                user: dict = Depends(require_perm('websites:manage'))):
    site = query('SELECT * FROM websites WHERE id=?', (sid,), one=True)
    assert_touch(user, site, '该站点')   # P-25h
    if not site:
        raise HTTPException(status_code=404, detail='网站不存在')
    action = body.get('action')
    if action == 'toggle':
        execute('UPDATE websites SET status=? WHERE id=?',
                (0 if site['status'] else 1, sid))
        _render_nginx()
        _reload_nginx()
    elif action == 'delete':
        execute('DELETE FROM websites WHERE id=?', (sid,))
        _render_nginx()
        _reload_nginx()
    elif action == 'reload':
        _reload_nginx()
    else:
        raise HTTPException(status_code=400, detail='未知操作')
    audit(user['username'], get_client_ip(request), 'website_action',
          f'{action} 网站 {site["domain"]}', 'warning' if action == 'delete' else 'info')
    return {'ok': True}


@router.put('/{sid}')
def site_update(sid: int, body: dict, request: Request,
                user: dict = Depends(require_perm('websites:manage'))):
    site = query('SELECT * FROM websites WHERE id=?', (sid,), one=True)
    assert_touch(user, site, '该站点')   # P-25h
    if not site:
        raise HTTPException(status_code=404, detail='网站不存在')
    root = _safe_site_root(body.get('root', site['root']))
    config = _safe_proxy_target(body.get('config', site['config'])) if site['type'] == 'proxy' else ''
    port = int(body.get('port', site['port']))
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail='端口无效')
    execute('UPDATE websites SET root=?, config=?, port=? WHERE id=?', (root, config, port, sid))
    _render_with_verify()
    _reload_nginx()
    audit(user['username'], get_client_ip(request), 'website_update', f'修改网站 {site["domain"]}')
    return {'ok': True}


@router.get('/{sid}')
def site_detail(sid: int, user: dict = Depends(require_perm('websites:view'))):
    """网站详情（二级管理页数据源）。"""
    site = query('SELECT * FROM websites WHERE id=?', (sid,), one=True)
    assert_touch(user, site, '该站点')   # P-25h
    if not site:
        raise HTTPException(status_code=404, detail='网站不存在')
    site = site or {}  # 双保险：上面已经判过空了，习惯性再兜一下
    st = query('SELECT * FROM site_settings WHERE site_id=?', (sid,), one=True) or {}
    site['settings'] = st
    return {'site': site}
@router.get('/{sid}/config')
def site_config(sid: int, user: dict = Depends(require_perm('websites:view'))):
    site = query('SELECT * FROM websites WHERE id=?', (sid,), one=True)
    assert_touch(user, site, '该站点')   # P-25h
    if not site:
        raise HTTPException(status_code=404, detail='网站不存在')
    conf = _render_single(site)
    return {'config': conf}
@router.get('/{sid}/logs')
def site_logs(sid: int, type: str = 'access', lines: int = 200,
              user: dict = Depends(require_perm('websites:view'))):
    """网站访问/错误日志查看（Nginx 日志尾部）。"""
    wzRow = query('SELECT * FROM websites WHERE id=?', (sid,), one=True)
    assert_touch(user, wzRow, '该站点')   # P-25h
    if not wzRow:
        raise HTTPException(status_code=404, detail='网站不存在')
    if type not in ('access', 'error'):
        raise HTTPException(status_code=400, detail='日志类型无效（access/error）')
    lines = min(max(int(lines), 1), 2000)
    logPath = _nginx_log_path(type, wzRow['domain'])
    if not os.path.isfile(logPath):
        return {'path': logPath, 'text': '', 'domain': wzRow['domain'],
                'error': '日志文件不存在（Nginx 未安装或未启用访问日志）'}
    rawTxt = _tail_file(logPath, lines)
    tailRows = rawTxt.splitlines()[-lines:]
    return {'path': logPath, 'text': '\n'.join(tailRows),
            'lines': len(tailRows), 'domain': wzRow['domain']}


@router.get('/{sid}/stats')
def site_stats(sid: int, user: dict = Depends(require_perm('websites:view'))):
    """流量统计：今日 PV/UV/流量 + 近 7 天趋势 + 今日 TOP 访问。"""
    import datetime as _dt
    site = query('SELECT * FROM websites WHERE id=?', (sid,), one=True)
    assert_touch(user, site, '该站点')   # P-25h
    if not site:
        raise HTTPException(status_code=404, detail='网站不存在')
    log_path = _nginx_log_path('access', site['domain'])
    today = {'pv': 0, 'uv': 0, 'bytes': 0}
    days = []
    top = []
    available = os.path.isfile(log_path)
    if available:
        line_re = re.compile(
            r'^(\S+) \S+ \S+ \[(\d{2})/(\w{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) [^\]]+\] '
            r'"(\S+) ([^"]*)" (\d{3}) (\d+|-)')
        now_ts = time.time()
        today_ips = set()
        day_pv = {}
        uri_cnt = {}
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    m = line_re.match(line)
                    if not m:
                        continue
                    ip, dd, mon, yy, hh, mm, ss, method, uri, status, bts = m.groups()
                    try:
                        line_ts = time.mktime(_dt.datetime.strptime(
                            f'{dd} {mon} {yy} {hh}:{mm}:{ss}', '%d %b %Y %H:%M:%S').timetuple())
                    except ValueError:
                        continue
                    dstr = _dt.datetime.fromtimestamp(line_ts).strftime('%m-%d')
                    day_pv[dstr] = day_pv.get(dstr, 0) + 1
                    if line_ts >= now_ts - 86400:
                        today['pv'] += 1
                        today_ips.add(ip)
                        if bts != '-':
                            today['bytes'] += int(bts)
                        uri_cnt[f'{method} {uri}'] = uri_cnt.get(f'{method} {uri}', 0) + 1
        except Exception:
            pass
        today['uv'] = len(today_ips)
        for i in range(6, -1, -1):
            d = _dt.datetime.fromtimestamp(now_ts - i * 86400).strftime('%m-%d')
            days.append({'date': d, 'pv': day_pv.get(d, 0)})
        top = [{'uri': k, 'count': v} for k, v in sorted(uri_cnt.items(), key=lambda x: -x[1])[:10]]
    return {'today': today, 'days': days, 'top': top, 'log': log_path, 'available': available}


@router.post('/import')
async def site_import(zipfile: UploadFile = File(...), domain: str = Form(''),
                      port: int = Form(80),
                      user: dict = Depends(require_perm('websites:manage'))):
    """一键搬家：上传网站 zip 备份 → 自动安全解压并建站。"""
    from .files import _extract_zip_safely
    from ..config import TMP_DIR
    domain = str(domain or '').strip().lower()
    if not re.match(r'^[a-z0-9\.\-\*]+$', domain):
        raise HTTPException(status_code=400, detail='域名无效')
    if query('SELECT id FROM websites WHERE domain=?', (domain,), one=True):
        raise HTTPException(status_code=409, detail='该域名已存在')
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail='端口无效')
    ts = str(int(now()))
    tmp_pkg = os.path.join(TMP_DIR, f'import_{ts}.zip')
    tmp_ext = os.path.join(TMP_DIR, f'import_x_{ts}')
    data = await zipfile.read()
    if len(data) < 1024:
        raise HTTPException(status_code=400, detail='压缩包内容异常')
    with open(tmp_pkg, 'wb') as fh:
        fh.write(data)
    os.makedirs(tmp_ext, exist_ok=True)
    try:
        _extract_zip_safely(tmp_pkg, tmp_ext)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'解压失败: {e}')
    root = os.path.join(WWWROOT_DIR, domain)
    os.makedirs(root, exist_ok=True)
    children = [p for p in os.listdir(tmp_ext) if not p.startswith('.')]
    if len(children) == 1 and os.path.isdir(os.path.join(tmp_ext, children[0])):
        inner = os.path.join(tmp_ext, children[0])
        for item in os.listdir(inner):
            shutil.move(os.path.join(inner, item), os.path.join(root, item))
    else:
        for item in children:
            shutil.move(os.path.join(tmp_ext, item), os.path.join(root, item))
    sid = execute(
        'INSERT INTO websites (domain,root,port,type,engine,config,status,created_at) '
        'VALUES (?,?,?,?,?,?,?,?)',
        (domain, root, port, 'static', 'nginx', '', 0, now()))
    execute('UPDATE websites SET owner_id=? WHERE id=(SELECT MAX(id) FROM websites)', (user['id'],))   # P-25h：记录归属
    execute('INSERT OR IGNORE INTO site_settings (site_id) VALUES (?)', (sid,))
    _render_nginx()
    audit(user['username'], get_client_ip(request), 'website_import',
          f'导入网站 {domain}', 'warning')
    try:
        os.remove(tmp_pkg)
        shutil.rmtree(tmp_ext, ignore_errors=True)
    except Exception:
        pass
    return {'ok': True, 'id': sid, 'msg': f'网站 {domain} 导入完成'}


# ---------------------------------------------------------------- 网站高级设置（伪静态/重定向/密码/防盗链）
# 自研伪静态预设库（常见程序规则，渲染为 Nginx 配置）
PSEUDO_RULES = {
    '': {'name': '无（默认）', 'rules': ''},
    'wordpress': {'name': 'WordPress', 'rules': 'try_files $uri $uri/ /index.php?$args;'},
    'typecho': {'name': 'Typecho', 'rules': "if (!-e $request_filename) {{ rewrite ^(.*)$ /index.php$1 last; }}"},
    'thinkphp': {'name': 'ThinkPHP', 'rules': "if (!-e $request_filename) {{ rewrite ^(.*)$ /index.php?s=$1 last; }}"},
    'laravel': {'name': 'Laravel', 'rules': 'try_files $uri $uri/ /index.php?$query_string;'},
    'discuz': {'name': 'Discuz', 'rules': "rewrite ^([^\\.]*)/topic-(.+)\\.html$ $1/portal.php?mod=topic&topic=$2 last;"},
    'zblog': {'name': 'Z-Blog', 'rules': "if (!-e $request_filename) {{ rewrite ^(.*)$ /index.php$1 last; }}"},
    'empire': {'name': '帝国 CMS', 'rules': "rewrite ^([^\\.]*)/list-([0-9]+)-([0-9]+)\\.html$ $1/e/action/ListInfo/index.php?classid=$2&page=$3 last;"},
    'custom': {'name': '自定义（下方填写）', 'rules': ''},
}


@router.get('/{sid}/settings')
def site_get_settings(sid: int, user: dict = Depends(require_perm('websites:view'))):
    site = query('SELECT * FROM websites WHERE id=?', (sid,), one=True)
    assert_touch(user, site, '该站点')   # P-25h
    if not site:
        raise HTTPException(status_code=404, detail='网站不存在')
    st = query('SELECT * FROM site_settings WHERE site_id=?', (sid,), one=True) or {}
    return {'settings': st, 'pseudo_presets': [
        {'key': k, 'name': v['name']} for k, v in PSEUDO_RULES.items()]}


@router.put('/{sid}/settings')
def site_put_settings(sid: int, body: dict, request: Request,
                      user: dict = Depends(require_perm('websites:manage'))):
    site = query('SELECT * FROM websites WHERE id=?', (sid,), one=True)
    assert_touch(user, site, '该站点')   # P-25h
    if not site:
        raise HTTPException(status_code=404, detail='网站不存在')
    pseudo = str(body.get('pseudo', ''))[:20]
    # P-06：这三项会进 nginx 配置，必须过白名单（原来只做长度截断/简单前缀判断）
    redirect = _validate_redirect(str(body.get('redirect', '')).strip()[:300])
    auth_user = str(body.get('auth_user', '')).strip()[:50]
    auth_pass = str(body.get('auth_pass', ''))
    hotlink = _validate_hotlink(str(body.get('hotlink', '')).strip()[:300])
    custom_pseudo = _validate_custom_pseudo(str(body.get('custom_pseudo', '')).strip()[:500])
    # 多域名绑定 / 强制 HTTPS / 默认文档
    domains = str(body.get('domains', '')).strip()[:500]
    force_https = 1 if body.get('force_https') else 0
    index_doc = str(body.get('index_doc', '')).strip()[:200]
    if domains:
        for d in domains.replace('\n', ' ').split():
            if not re.match(r'^[a-z0-9\.\-\*]+$', d.strip().lower()):
                raise HTTPException(status_code=400, detail=f'绑定域名无效：{d}')
    if index_doc and not re.match(r'^[a-zA-Z0-9\._ -]+$', index_doc):
        raise HTTPException(status_code=400, detail='默认文档无效')
    if redirect and not redirect.startswith(('http://', 'https://', '/')):
        raise HTTPException(status_code=400, detail='重定向地址需以 http(s):// 或 / 开头')
    if auth_user and not re.match(r'^[A-Za-z0-9_.-]{1,50}$', auth_user):
        raise HTTPException(status_code=400, detail='目录认证用户名仅支持字母、数字、点、下划线和连字符')
    auth_hash = ''
    if auth_user and auth_pass:
        # 密码经 stdin 传递，不能拼接进 shell 命令（否则引号可导致命令注入）。
        r = run_cmd(['openssl', 'passwd', '-apr1', '-stdin'], timeout=10,
                    shell=False, input_text=auth_pass)
        if r['code'] != 0:
            raise HTTPException(status_code=400, detail='密码加密失败（需安装 openssl）')
        auth_hash = r['stdout'].strip()
        # 写 htpasswd 文件供 auth_basic_user_file 使用
        try:
            os.makedirs('/etc/nginx', exist_ok=True)
            with open(f'/etc/nginx/rt-auth-{sid}', 'w', encoding='utf-8') as f:
                f.write(f'{auth_user}:{auth_hash}\n')
        except Exception:
            pass
    elif auth_user and not auth_pass:
        raise HTTPException(status_code=400, detail='请设置目录密码')
    existing = query('SELECT site_id FROM site_settings WHERE site_id=?', (sid,), one=True)
    if existing:
        execute('UPDATE site_settings SET pseudo=?, redirect=?, auth_user=?, auth_hash=?, hotlink=?, '
                'domains=?, force_https=?, index_doc=? WHERE site_id=?',
                (pseudo, redirect, auth_user, auth_hash, hotlink, domains, force_https, index_doc, sid))
    else:
        execute('INSERT INTO site_settings (site_id, pseudo, redirect, auth_user, auth_hash, hotlink, '
                'domains, force_https, index_doc) VALUES (?,?,?,?,?,?,?,?,?)',
                (sid, pseudo, redirect, auth_user, auth_hash, hotlink, domains, force_https, index_doc))
    if pseudo == 'custom':
        execute('UPDATE site_settings SET pseudo=? WHERE site_id=?',
                ('custom::' + custom_pseudo, sid))
    _render_with_verify()
    _reload_nginx()
    audit(user['username'], get_client_ip(request), 'website_settings',
          f'修改网站 {site["domain"]} 高级设置（伪静态/重定向/密码/防盗链/多域名/HTTPS）', 'warning')
    return {'ok': True}



# ---------------- P-06：nginx 配置注入防护 ----------------
# 进 nginx 配置的用户输入必须过白名单：nginx 的词法与行无关，一个 `;` 就能提前结束当前指令，
# 一个 `}` 就能跳出 location/server 块，所以"只转义换行"远远不够。
NGINX_CONF_FILE = '/etc/nginx/conf.d/云枢面板.conf'
_DOMAIN_TOKEN_RE = re.compile(r'^[A-Za-z0-9.*_-]{1,253}$')
_REDIRECT_BAD = set(';{}#\n\r$')
_PSEUDO_BAD = set('{}')
_PSEUDO_FORBIDDEN = ('location', 'include', 'server', 'proxy_pass', 'alias',
                     'upstream', 'root', 'fastcgi_pass', 'return', 'rewrite_log')


def _validate_hotlink(hotlink: str) -> str:
    """防盗链域名列表：空格分隔，逐个走域名白名单。"""
    if not hotlink:
        return ''
    tokens = hotlink.replace('\n', ' ').split()
    if len(tokens) > 20:
        raise HTTPException(status_code=400, detail='防盗链域名过多（最多 20 个）')
    for t in tokens:
        if not _DOMAIN_TOKEN_RE.match(t):
            raise HTTPException(status_code=400, detail=f'防盗链域名无效：{t}')
    return ' '.join(tokens)


def _validate_redirect(redirect: str) -> str:
    if not redirect:
        return ''
    if not redirect.startswith(('http://', 'https://', '/')):
        raise HTTPException(status_code=400, detail='重定向地址需以 http(s):// 或 / 开头')
    if any(ch in _REDIRECT_BAD for ch in redirect) or any(ch.isspace() for ch in redirect):
        raise HTTPException(status_code=400, detail='重定向地址包含非法字符（; { } # $ 空白）')
    if not re.match(r'^[A-Za-z0-9\-._~:/?#\[\]@!&\'()*+,=%]+$', redirect):
        raise HTTPException(status_code=400, detail='重定向地址包含不允许的字符')
    return redirect


def _validate_custom_pseudo(text: str) -> str:
    """自定义伪静态片段：允许 nginx 指令，但禁止任何能改变配置结构的内容。"""
    if not text:
        return ''
    if any(ch in _PSEUDO_BAD for ch in text):
        raise HTTPException(status_code=400, detail='伪静态规则不能包含 { 或 }')
    low = text.lower()
    for kw in _PSEUDO_FORBIDDEN:
        if re.search(r'(^|[^a-z0-9_])' + kw + r'([^a-z0-9_]|$)', low):
            raise HTTPException(status_code=400, detail=f'伪静态规则不允许使用 {kw} 指令')
    if len(text) > 500:
        raise HTTPException(status_code=400, detail='伪静态规则过长（最多 500 字符）')
    return text


def _nginx_available() -> bool:
    import shutil
    return shutil.which('nginx') is not None


def _render_with_verify():
    """渲染站点配置后跑 nginx -t；不通过就回滚文件并 400（避免坏配置留在磁盘上全站起不来）。"""
    prev = None
    had = os.path.isfile(NGINX_CONF_FILE)
    if had:
        try:
            with open(NGINX_CONF_FILE, 'rb') as f:
                prev = f.read()
        except Exception:
            prev = None
    _render_nginx()
    if not _nginx_available():
        return          # 本机没装 nginx（如 Windows 开发机）：跳过校验
    r = run_cmd('nginx -t 2>&1', timeout=30, shell=True)
    if r['code'] == 0:
        return
    detail = (r['stderr'] or r['stdout'] or '')[-300:]
    try:
        if prev is not None:
            with open(NGINX_CONF_FILE, 'wb') as f:
                f.write(prev)
        elif had:
            os.remove(NGINX_CONF_FILE)
    except Exception:
        pass
    raise HTTPException(status_code=400, detail=f'nginx 配置校验失败，已回滚：{detail}')

def _render_single(site: dict) -> str:
    from ..waf_core import render_waf_block
    waf = render_waf_block()
    domain = site['domain']
    st = query('SELECT * FROM site_settings WHERE site_id=?', (site['id'],), one=True) or {}
    # 该域名已有有效证书 → 自动生成 443 HTTPS server 块 + 80 自动跳转
    ssl_cert = query("SELECT * FROM ssl_certs WHERE domain=? AND cert_path!='' ORDER BY id DESC",
                     (domain,), one=True)
    has_ssl = bool(ssl_cert and os.path.isfile(ssl_cert['cert_path']))
    # 多域名绑定
    names = [domain]
    for d in (st.get('domains') or '').replace('\n', ' ').split():
        d = d.strip().lower()
        if d and d not in names:
            names.append(d)
    server_name = ' '.join(names)
    extra = ''
    if st.get('force_https') or has_ssl:
        extra += ('\n    # 强制 HTTPS（已部署证书自动开启）\n'
                  '    if ($scheme = http) { return 301 https://$host$request_uri; }\n')
    if st.get('redirect'):
        extra += f'\n    # 301 重定向\n    return 301 {st["redirect"]};\n'
    if st.get('auth_user') and st.get('auth_hash'):
        extra += (f'\n    # 目录密码保护\n    auth_basic "Site Auth";\n'
                  f'    auth_basic_user_file /etc/nginx/rt-auth-{site["id"]};\n')
    hotlink = st.get('hotlink') or ''
    if hotlink:
        domains = ' '.join(d.strip() for d in hotlink.replace('\n', ' ').split(' ') if d.strip())
        extra += (f'\n    # 防盗链（允许来源）\n    valid_referers none blocked {domains};\n'
                  f'    if ($invalid_referer) {{ return 403; }}\n')
    pseudo = st.get('pseudo') or ''
    pseudo_rules = ''
    if pseudo.startswith('custom::'):
        pseudo_rules = pseudo.split('::', 1)[1]
    elif pseudo in PSEUDO_RULES:
        pseudo_rules = PSEUDO_RULES[pseudo]['rules']
    if pseudo_rules:
        extra += f'\n    # 伪静态规则\n    location / {{\n        {pseudo_rules}\n    }}\n'
    index_doc = (st.get('index_doc') or '').strip()
    index_line = f'    index {index_doc};' if index_doc else '    index index.html index.htm index.php;'
    # PHP 站点：自动探测 PHP-FPM socket（未探测到用默认路径，装了 PHP 后即生效）
    php_upstream = (_php_fpm_sock() or '/run/php/php-fpm.sock')
    # 站点独立访问/错误日志（目录不存在则跳过，避免 nginx reload 失败）
    log_lines = ''
    log_dir = os.path.dirname(_nginx_log_path('access', domain))
    if os.path.isdir(log_dir):
        log_lines = (f'    access_log {os.path.join(log_dir, domain + ".access.log").replace(chr(92), "/")};\n'
                     f'    error_log {os.path.join(log_dir, domain + ".error.log").replace(chr(92), "/")};\n')
    if site['type'] == 'proxy':
        target = site['config']
        base = f'''server {{
    listen {site['port']};
    listen [::]:{site['port']};
    server_name {server_name};
{log_lines}{waf}{extra}
    location / {{
        proxy_pass {target};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }}
}}'''
    else:
        base = f'''server {{
    listen {site['port']};
    listen [::]:{site['port']};
    server_name {server_name};
{log_lines}{waf}{extra}
    root {site['root']};
{index_line}

    location / {{
        try_files $uri $uri/ =404;
    }}

    location ~ \\.php$ {{
        try_files $uri =404;
        fastcgi_pass unix:{php_upstream};
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    location ~ /\\.(?!well-known).* {{
        deny all;
    }}
}}'''
    # 域名已部署证书 → 自动追加 443 HTTPS server 块（SSL 整合进网站管理）
    if has_ssl:
        cert_path = ssl_cert['cert_path'].replace('\\', '/')
        key_path = ssl_cert['key_path'].replace('\\', '/')
        if site['type'] == 'proxy':
            target = site['config']
            https_block = f'''

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {server_name};
    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
{waf}
    location / {{
        proxy_pass {target};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}'''
        else:
            https_block = f'''

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {server_name};
    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
{waf}
    root {site['root']};
{index_line}
    location / {{
        try_files $uri $uri/ =404;
    }}
}}'''
        return base + https_block
    return base


def _render_nginx():
    sites = query('SELECT * FROM websites WHERE status=1')
    out = []
    # WAF CC 限流 zone 定义（http 上下文，需在所有 server 块之前）
    if query("SELECT id FROM waf_rules WHERE enabled=1 AND kind='cc'", one=True):
        out.append('limit_req_zone $binary_remote_addr zone=rtwaf:10m rate=10r/s;')
    for s in sites:
        out.append(_render_single(s))
    conf_dir = '/etc/nginx/conf.d'
    os.makedirs(conf_dir, exist_ok=True)
    try:
        with open(os.path.join(conf_dir, '云枢面板.conf'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(out))
    except PermissionError:
        pass  # 无权限时仅面板内生效


def _reload_nginx():
    run_cmd('nginx -t 2>&1 && nginx -s reload 2>&1', timeout=30, shell=True)
