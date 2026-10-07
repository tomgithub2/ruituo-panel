# Created by 小杜 on 2026/08

"""AI 助手（面板内置 Agent）—— 跨时代形态：一句话描述目标，自动生成执行计划并完成全部操作。

- 自研 Agent 逻辑：提示词工程 + 结构化 action 协议（无第三方 Agent 框架）
- 接入任意 OpenAI 兼容大模型（DeepSeek/通义/Kimi/GLM/GPT/Ollama…），API 由用户配置
- API Key 使用机器码派生密钥 Fernet 加密存储
- 全部工具走白名单 + 全量审计；危险操作需用户一次确认
"""
import base64
import hashlib
import io
import secrets
import json
import os
import re
import threading
import time
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Request

from ..audit import audit
from ..auth import get_client_ip, require_feature, require_perm
from ..config import DATA_DIR, PANEL_VERSION
from ..hardware import machine_id

router = APIRouter(prefix='/api/ai', tags=['ai'],
                   dependencies=[Depends(require_feature('ai'))])

CONFIG_FILE = os.path.join(DATA_DIR, 'ai_config.json')

# ================================================================
# 自研 Agent 协议：工具白名单（一句话目标 → 多步计划 → 逐个执行）
# ================================================================
TOOL_DEFS = """
你是 锐同面板 内置的跨时代运维智能体（Agent）。用户通常只说一句话描述目标，你需要：
1) 先在正文中用简短的步骤清单说明你的执行计划；
2) 然后在回复末尾为计划中的每一步输出一个 action 代码块（markdown），格式严格如下：
```action
{"tool": "工具名", "params": {...}}
```
一个目标可输出多个 action（按执行顺序排列）。无法确定的关键参数（如域名、端口）请先向用户提问，不要臆造。

可用工具清单：
【系统诊断】get_system_info(无参) · run_healthcheck(无参) · scan_bigfiles{path,top} · check_updates(无参)
【任意命令】run_shell_command{cmd}（执行任意 shell 命令，需用户授权，输出最多 4000 字符）
【文件】list_files{path} · read_file{path}
【软件】list_software(无参) · install_software{key}(git/nginx/node/python/docker/redis/mysql/postgresql/php/java/curl/wget/vim/certbot) · deploy_app{app,domain}(一键部署 wordpress/discuz/typecho/zblog)
【建站】create_site{domain,title,desc} · create_proxy{domain,port,target} · list_sites(无参) · delete_site{domain}
【SSL】issue_ssl{domain} · list_certs(无参)
【数据库】list_databases(无参) · create_database{kind,db} · query_db{kind,db,sql} · backup_database{kind,db}
【防火墙】open_port{port,protocol,name} · block_ip{ip}
【FTP】list_ftp_users(无参) · create_ftp_user{username,dir,password}
【SSH】ssh_status(无参)
【WAF】waf_status(无参) · list_waf_rules(无参)
【DNS】list_hosts(无参) · flush_dns(无参)
【计划任务】create_cron{name,schedule,command} · list_cron(无参)
【备份】create_backup_task{name,path} · run_backup{name} · list_backup_tasks(无参)
【Docker】docker_status(无参) · list_containers(无参) · docker_action{container,action}
【服务】list_services(无参) · service_action{name,action}
【进程守护】add_guardian{name,process,cmd} · list_guardians(无参)

危险操作（create_site/create_proxy/delete_site/install_software/deploy_app/issue_ssl/create_database/backup_database/open_port/block_ip/create_ftp_user/create_cron/create_backup_task/run_backup/docker_action/service_action/add_guardian）面板会要求用户确认后才执行；只读工具自动执行。
"""

DEFAULT_SYSTEM = (
    f'你是 锐同面板（高端服务器运维面板）内置的 AI 运维智能体，版本 v{PANEL_VERSION}。'
    '你精通 Linux/Windows 运维全栈：建站、Nginx、SSL、Docker、数据库、防火墙、备份、故障排查。'
    '回答简洁专业、使用中文、条理清晰。{tools}'
)

_HISTORY = []  # 兼容占位（实际已改为按用户持久化到 ai_conversations 表）
_lock = threading.Lock()
_msg_counters = {}  # user_id -> 未总结消息计数（触发自动知识沉淀）
_knowledge_dirty = threading.Event()

# 工具分类：危险工具需要确认
DANGEROUS = {
    'create_site', 'create_proxy', 'delete_site', 'install_software', 'deploy_app',
    'issue_ssl', 'create_database', 'backup_database', 'open_port', 'block_ip',
    'create_ftp_user', 'create_cron', 'create_backup_task', 'run_backup',
    'docker_action', 'service_action', 'add_guardian', 'run_shell_command',
}
TOOL_LABELS = {
    'get_system_info': '查看系统状态', 'run_healthcheck': '一键体检', 'scan_bigfiles': '大文件扫描',
    'check_updates': '检查更新', 'list_files': '查看目录', 'read_file': '读取文件',
    'list_software': '查看软件列表', 'install_software': '安装软件',
    'create_site': '一键建站', 'create_proxy': '创建反向代理', 'list_sites': '网站列表',
    'delete_site': '删除网站', 'issue_ssl': '签发SSL证书', 'list_certs': '证书列表',
    'list_databases': '数据库列表', 'create_database': '创建数据库', 'query_db': '数据库查询',
    'backup_database': '备份数据库', 'open_port': '开放端口', 'block_ip': '封禁IP',
    'create_cron': '创建计划任务', 'list_cron': '计划任务列表',
    'create_backup_task': '创建备份任务', 'run_backup': '执行备份', 'list_backup_tasks': '备份任务列表',
    'docker_status': 'Docker状态', 'list_containers': '容器列表', 'docker_action': '容器操作',
    'list_services': '服务列表', 'service_action': '服务操作',
    'add_guardian': '添加进程守护', 'list_guardians': '守护列表',
    'deploy_app': '一键部署源码', 'list_ftp_users': 'FTP用户列表',
    'create_ftp_user': '创建FTP账号', 'ssh_status': 'SSH安全状态',
    'waf_status': 'WAF防护状态', 'list_waf_rules': 'WAF规则列表',
    'list_hosts': 'hosts配置', 'flush_dns': '刷新DNS缓存',
    'run_shell_command': '执行任意命令',
}


AI_KEY_FILE = os.path.join(DATA_DIR, 'ai.key')


def _fernet():
    """P-25p：AI API Key 用**独立随机密钥**加密（0600 落盘），不再由 machine_id 派生。

    原实现 `sha256('rt-ai-key:' + machine_id())` —— machine_id 是硬件信息的哈希，
    任何能读到硬件信息（或知道 machine_id，机器码在多处接口可见）的人都能推出密钥、
    解开数据库里的第三方 API Key。
    """
    from cryptography.fernet import Fernet
    try:
        if os.path.isfile(AI_KEY_FILE):
            raw = io.open(AI_KEY_FILE, 'rb').read().strip()
            if raw:
                return Fernet(raw)
    except Exception:
        pass
    key = base64.urlsafe_b64encode(secrets.token_bytes(32))
    fd = os.open(AI_KEY_FILE, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    try:
        os.chmod(AI_KEY_FILE, 0o600)
    except Exception:
        pass
    return Fernet(key)


def _load_config() -> dict:
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg: dict):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _mask_key(key: str) -> str:
    if not key:
        return ''
    if len(key) <= 8:
        return '*' * len(key)
    return key[:4] + '*' * (len(key) - 8) + key[-4:]


def _decrypt_key(enc: str) -> str:
    if not enc:
        return ''
    try:
        return _fernet().decrypt(enc.encode()).decode()
    except Exception:
        return ''


def _ai_request(cfg: dict, messages: list) -> str:
    base = (cfg.get('base_url') or 'https://api.deepseek.com').rstrip('/')
    url = base if base.endswith('/chat/completions') else base + '/chat/completions'
    payload = {
        'model': cfg.get('model', 'deepseek-chat'),
        'messages': messages,
        'temperature': float(cfg.get('temperature', 0.7)),
        'stream': False,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'Authorization': 'Bearer ' + _decrypt_key(cfg.get('api_key_enc', ''))})
    with urllib.request.urlopen(req, timeout=int(cfg.get('timeout', 120))) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return data['choices'][0]['message']['content']


def _parse_actions(reply: str):
    actions = []
    for m in re.finditer(r'```action\s*\n(\{.*?\})\s*```', reply, re.S):
        try:
            actions.append(json.loads(m.group(1)))
        except Exception:
            continue
    clean = re.sub(r'```action\s*\n\{.*?\}\s*```', '', reply, flags=re.S).strip()
    return clean, actions


# ---------------- 配置 ----------------
@router.get('/config')
def get_config(user: dict = Depends(require_perm('settings:view'))):
    cfg = _load_config()
    return {
        'enabled': bool(cfg.get('enabled')),
        'base_url': cfg.get('base_url', ''),
        'model': cfg.get('model', ''),
        'api_key_masked': _mask_key(_decrypt_key(cfg.get('api_key_enc', ''))),
        'temperature': cfg.get('temperature', 0.7),
        'timeout': cfg.get('timeout', 120),
        'has_key': bool(cfg.get('api_key_enc')),
        # P-25q：知识库"上传到官网共享池"默认**关闭**（原默认开启 + 每 30 分钟自动外传）
    'upload_enabled': bool(cfg.get('upload_enabled', False)),
        'last_upload': cfg.get('last_upload', 0),
    }


@router.put('/config')
def save_config(body: dict, request: Request, user: dict = Depends(require_perm('settings:manage'))):
    cfg = _load_config()
    # 部分更新：只覆盖调用方提供的键（如知识库上传开关可单独切换）
    if 'base_url' in body:
        base_url = str(body.get('base_url', '')).strip()
        if base_url and not base_url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail='API 地址需以 http(s):// 开头')
        cfg['base_url'] = base_url
    if 'model' in body:
        cfg['model'] = str(body.get('model', '')).strip()
    if 'temperature' in body:
        cfg['temperature'] = float(body.get('temperature', 0.7))
    if 'timeout' in body:
        cfg['timeout'] = max(10, min(int(body.get('timeout', 120)), 600))
    if 'enabled' in body:
        cfg['enabled'] = bool(body.get('enabled'))
    elif 'base_url' in body:
        # 保存配置时自动判定：地址非空且（本次带新 key 或已有 key）→ 自动启用
        _new_key = str(body.get('api_key', '')).strip()
        _has_key = bool(cfg.get('api_key_enc')) or bool(_new_key and '*' not in _new_key)
        cfg['enabled'] = bool(base_url and _has_key)
    # 知识库是否上传官网（默认开启，用户可关）
    if 'upload_enabled' in body:
        cfg['upload_enabled'] = bool(body.get('upload_enabled'))
    else:
        cfg.setdefault('upload_enabled', False)   # P-25q：默认关闭
    if 'api_key' in body:
        new_key = str(body.get('api_key', '')).strip()
        if new_key and '*' not in new_key:
            cfg['api_key_enc'] = _fernet().encrypt(new_key.encode()).decode()
    _save_config(cfg)
    audit(user['username'], get_client_ip(request), 'ai_config', '更新 AI 助手配置')
    return {'ok': True, 'api_key_masked': _mask_key(_decrypt_key(cfg.get('api_key_enc', '')))}


@router.post('/test')
def test_connection(body: dict, user: dict = Depends(require_perm('settings:manage'))):
    cfg = _load_config()
    if body.get('base_url'):
        cfg['base_url'] = str(body['base_url']).strip()
    if body.get('model'):
        cfg['model'] = str(body['model']).strip()
    if body.get('api_key') and '*' not in str(body.get('api_key')):
        cfg['api_key_enc'] = _fernet().encrypt(str(body['api_key']).encode()).decode()
    try:
        reply = _ai_request(cfg, [{'role': 'user', 'content': '请只回复"连接成功"四个字'}])
        return {'ok': True, 'reply': reply[:50]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'连接失败: {e}')


# ---------------- 用户级知识库（快照） ----------------
def _user_history(user_id: int, limit: int = 30) -> list:
    from ..database import query as _q
    rows = _q('SELECT role, content FROM ai_conversations WHERE user_id=? '
              'ORDER BY id DESC LIMIT ?', (user_id, limit))
    return [{'role': r['role'], 'content': r['content']} for r in reversed(rows)]


def _knowledge_entries(user_id: int, limit: int = 15) -> list:
    from ..database import query as _q
    rows = _q('SELECT entry FROM ai_knowledge WHERE user_id=? '
              'ORDER BY id DESC LIMIT ?', (user_id, limit))
    return [r['entry'] for r in reversed(rows)]


def _add_knowledge(user_id: int, entry: str):
    from ..database import execute, query
    execute('INSERT INTO ai_knowledge (user_id, entry, created_at) VALUES (?,?,?)',
            (user_id, entry[:500], time.time()))
    # 只保留最近 50 条
    execute('DELETE FROM ai_knowledge WHERE user_id=? AND id NOT IN '
            '(SELECT id FROM ai_knowledge WHERE user_id=? ORDER BY id DESC LIMIT 50)',
            (user_id, user_id))
    _knowledge_dirty.set()


def _build_system(user_id: int, cfg: dict) -> str:
    system = (cfg.get('system_prompt') or DEFAULT_SYSTEM).replace('{tools}', TOOL_DEFS)
    entries = _knowledge_entries(user_id)
    if entries:
        system += '\n\n【你的长期记忆——已学习到的关于这台服务器与用户偏好的知识，回答时主动利用】\n'
        system += '\n'.join(f'- {e}' for e in entries)
    return system


def _maybe_summarize(user_id: int, cfg: dict):
    """每累计 8 轮对话，后台让 AI 沉淀 3-5 条知识到知识库。"""
    with _lock:
        count = _msg_counters.get(user_id, 0) + 1
        _msg_counters[user_id] = count
        if count < 8:
            return
        _msg_counters[user_id] = 0
    history = _user_history(user_id, 24)
    if len(history) < 8:
        return

    def _do():
        try:
            prompt = ('请阅读以下用户与运维AI的对话，提炼出 3-5 条关于该服务器环境、'
                      '用户目标、操作习惯的**知识条目**（每条不超过 50 字，用中文，'
                      '以"- "开头的列表输出，只输出列表本身）：\n\n' +
                      '\n'.join(f'{m["role"]}: {m["content"][:300]}' for m in history))
            reply = _ai_request(cfg, [{'role': 'user', 'content': prompt}])
            for line in reply.splitlines():
                line = line.strip()
                if line.startswith('- ') and len(line) > 3:
                    _add_knowledge(user_id, line[2:])
        except Exception:
            pass

    threading.Thread(target=_do, daemon=True).start()


# ---------------- 知识库上传官网 ----------------
def _scrub_entry(text: str) -> str:
    """P-25q：上传前脱敏 —— 去掉 IP、域名、绝对路径与疑似口令/密钥。

    知识条来自 AI 对话，可能夹带主机信息、路径甚至口令；上传到官网共享池前必须清洗。
    """
    import re as _re
    t = str(text or '')
    t = _re.sub(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', '<ip>', t)
    t = _re.sub(r'(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\b\s*[:=]\s*\S+',
                r'\1=<redacted>', t)
    t = _re.sub(r'/(?:home|root|www|var|etc|opt|usr)/\S*', '<path>', t)
    t = _re.sub(r'\b[A-Za-z0-9][A-Za-z0-9.-]*\.(?:com|cn|net|org|icu|io|top|xyz)\b', '<domain>', t)
    return t[:300]


def upload_knowledge() -> dict:
    """把全部用户的知识库上传到官网（绑定有效时）。"""
    from .. import binding
    from ..database import query as _q
    st = binding.status()
    if st['mode'] != 'bound':
        return {'ok': False, 'error': '未绑定官网账户，跳过上传'}
    data = binding._load()
    payload = {
        'token': data.get('token', ''),
        'binding_id': data.get('binding_id', ''),
        'machine_id': st.get('machine_id', ''),
        # P-25q：① 逐条脱敏；② 不再上报全局条数（避免泄露面板用户规模/活跃度）
    'entries': [{'entry': _scrub_entry(r['entry']), 'created_at': r['created_at']}
                    for r in _q('SELECT entry, created_at FROM ai_knowledge '
                                'ORDER BY id DESC LIMIT 50')],
        'summary': 'anonymized',
    }
    try:
        req = urllib.request.Request(
            binding.server_url().rstrip('/') + '/api/v1/knowledge/upload',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
        return result if isinstance(result, dict) else {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ---------------- 对话（计划生成） ----------------
@router.post('/chat')
def chat(body: dict, request: Request, user: dict = Depends(require_perm('ai:use'))):
    cfg = _load_config()
    if not cfg.get('enabled'):
        raise HTTPException(status_code=400, detail='AI 助手未配置，请先在设置中配置模型接口')
    if not cfg.get('api_key_enc'):
        raise HTTPException(status_code=400, detail='请先配置 API Key')
    message = str(body.get('message', '')).strip()
    if not message:
        raise HTTPException(status_code=400, detail='消息不能为空')
    if len(message) > 4000:
        raise HTTPException(status_code=400, detail='消息过长')
    from ..database import execute
    system = _build_system(user['id'], cfg)
    history = _user_history(user['id'], 30)
    messages = [{'role': 'system', 'content': system}] + history
    messages.append({'role': 'user', 'content': message})
    try:
        reply = _ai_request(cfg, messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'AI 请求失败: {e}')
    clean, actions = _parse_actions(reply)
    execute('INSERT INTO ai_conversations (user_id, role, content, ts) VALUES (?,?,?,?)',
            (user['id'], 'user', message, time.time()))
    execute('INSERT INTO ai_conversations (user_id, role, content, ts) VALUES (?,?,?,?)',
            (user['id'], 'assistant', clean, time.time()))
    # 自动知识沉淀
    _maybe_summarize(user['id'], cfg)
    audit(user['username'], get_client_ip(request), 'ai_chat', message[:200])
    return {
        'reply': clean,
        'actions': [{
            'tool': str(a.get('tool', '')),
            'params': a.get('params') or {},
            'confirm_required': str(a.get('tool', '')) in DANGEROUS,
            'label': TOOL_LABELS.get(str(a.get('tool', '')), str(a.get('tool', ''))),
        } for a in actions],
    }


@router.post('/clear')
def clear_history(user: dict = Depends(require_perm('ai:use'))):
    from ..database import execute
    execute('DELETE FROM ai_conversations WHERE user_id=?', (user['id'],))
    return {'ok': True}


# ---------------- 知识库管理 ----------------
@router.get('/knowledge')
def knowledge(user: dict = Depends(require_perm('ai:use'))):
    from ..database import query as _q
    cfg = _load_config()
    rows = _q('SELECT entry, created_at FROM ai_knowledge WHERE user_id=? '
              'ORDER BY id DESC LIMIT 100', (user['id'],))
    return {
        'entries': rows,
        'count': len(rows),
        'upload_enabled': bool(cfg.get('upload_enabled', True)),
        'last_upload': cfg.get('last_upload', 0),
    }


@router.post('/knowledge/upload')
def knowledge_upload(request: Request, user: dict = Depends(require_perm('ai:use'))):
    result = upload_knowledge()
    if result.get('ok'):
        cfg = _load_config()
        cfg['last_upload'] = time.time()
        _save_config(cfg)
        _knowledge_dirty.clear()
    audit(user['username'], get_client_ip(request), 'ai_knowledge_upload',
          '手动上传知识库' if result.get('ok') else f'上传失败: {result.get("error")}')
    return result


@router.post('/knowledge/clear')
def knowledge_clear(user: dict = Depends(require_perm('ai:use'))):
    from ..database import execute
    execute('DELETE FROM ai_knowledge WHERE user_id=?', (user['id'],))
    return {'ok': True}


# ---------------- 工具执行（白名单 + 审计） ----------------
@router.post('/execute')
def execute_action(body: dict, request: Request, user: dict = Depends(require_perm('ai:use'))):
    tool = str(body.get('tool', ''))
    params = body.get('params') or {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail='参数格式错误')
    result = _dispatch(tool, params, user)
    audit(user['username'], get_client_ip(request), 'ai_execute',
          f'{tool} {json.dumps(params, ensure_ascii=False)[:200]}',
          'warning' if tool in DANGEROUS else 'info')
    # 自动沉淀知识：记录执行事实（结果截断）
    try:
        _add_knowledge(user['id'],
                       f'执行了「{TOOL_LABELS.get(tool, tool)}」（参数 {json.dumps(params, ensure_ascii=False)[:120]}），'
                       f'结果：{result[:150]}')
    except Exception:
        pass
    return {'ok': True, 'tool': tool, 'result': result}


# ---------------- P-04：工具 → 所需权限 ----------------
# 根因：_dispatch 直接函数调用各路由函数，FastAPI 的 Depends(require_perm(...)) 不会执行，
# 所以必须在分发入口按表复检权限，否则光有 ai:use 就能调用 system:manage 级别的能力。
TOOL_PERM = {
    'get_system_info': 'dashboard:view', 'run_healthcheck': 'security:view',
    'scan_bigfiles': 'files:read', 'check_updates': 'settings:view',
    'list_files': 'files:read', 'read_file': 'files:read',
    'list_software': 'software:view', 'install_software': 'software:manage',
    'create_site': 'websites:manage', 'create_proxy': 'websites:manage',
    'list_sites': 'websites:view', 'delete_site': 'websites:manage',
    'issue_ssl': 'ssl:manage', 'list_certs': 'ssl:view',
    'list_databases': 'databases:view', 'create_database': 'databases:manage',
    'query_db': 'databases:view', 'backup_database': 'databases:manage',
    'open_port': 'firewall:manage', 'block_ip': 'firewall:manage',
    'create_cron': 'cron:manage', 'list_cron': 'cron:view',
    'create_backup_task': 'backups:manage', 'run_backup': 'backups:manage',
    'list_backup_tasks': 'backups:view',
    'docker_status': 'docker:view', 'list_containers': 'docker:view',
    'docker_action': 'docker:manage', 'service_action': 'services:manage',
    'create_ftp_user': 'ftp:manage', 'add_guardian': 'security:manage',
    'deploy_app': 'software:manage',
}


def _tool_allowed(tool: str, user: dict) -> bool:
    """按工具所属路由的权限复检（admin 直接放行）。"""
    from ..rbac import role_permissions
    need = TOOL_PERM.get(tool)
    if not need:
        return False          # 表里没有的工具一律不放行（含已被移除的 run_shell_command）
    if user.get('role') == 'admin':
        return True
    return need in role_permissions(user.get('role'))

def _dispatch(tool: str, p: dict, user: dict) -> str:
    # P-04：任意命令执行是 root 级别的后门，该工具直接下线（放在权限检查之前，给出明确原因）
    if tool == 'run_shell_command':
        return '出于安全考虑，AI 助手已不再提供任意命令执行能力；请使用软件商店/定时任务/文件管理等受控功能'
    # P-04：再做权限复检（分发是函数直调，路由上的 Depends 不会执行）
    if not _tool_allowed(tool, user):
        return f'无权执行该操作（{TOOL_LABELS.get(tool, tool)}），请让管理员在用户权限里开通'
    from ..utils import sysinfo
    if tool == 'get_system_info':
        o = sysinfo.overview()
        return (f"CPU {o['cpu']['percent']}%（{o['cpu']['cores']}核{o['cpu']['threads']}线程）｜"
                f"内存 {o['mem']['percent']}%（{o['mem']['used']}/{o['mem']['total']}GB）｜"
                f"磁盘分区 {len(o['disk']['partitions'])} 个｜"
                f"系统 {o['system']['system']} {o['system']['release']}｜"
                f"运行 {int(o['system']['uptime'] // 86400)} 天")
    if tool == 'run_healthcheck':
        from .health import run
        r = run(user)
        return (f"健康评分 {r['score']}（{r['level']}）：{r['passed']} 项通过，"
                f"{r['failed']} 项需关注。重点问题：" +
                '；'.join(c['item'] for c in r['checks'] if not c['ok'])[:300] or '无')
    if tool == 'scan_bigfiles':
        from .toolbox import scan_big
        path = str(p.get('path', '/'))
        r = scan_big({'path': path, 'top': min(int(p.get('top', 10)), 30)}, user)
        return '最大文件 TOP：\n' + '\n'.join(
            f"{x['size'] / 1048576:.1f}MB {x['path']}" for x in r['list'][:10]) or '未发现大文件'
    if tool == 'check_updates':
        from .update import check
        info = check(user)
        return (f"当前 v{info.get('current_version')}，" +
                (f"有新版本 v{info.get('version')}" if info.get('has_update') else '已是最新'))
    if tool == 'list_files':
        path = str(p.get('path', '.')).strip() or '.'
        if not os.path.isdir(path):
            return f'目录不存在: {path}'
        names = sorted(os.listdir(path))[:60]
        return f'{path} 共 {len(names)} 项：\n' + '\n'.join(names)
    if tool == 'read_file':
        path = str(p.get('path', '')).strip()
        if not os.path.isfile(path):
            return f'文件不存在: {path}'
        try:
            with open(path, 'rb') as f:
                data = f.read()
            if len(data) > 64 * 1024:
                return f'文件过大（{len(data) / 1024:.0f}KB），仅展示前 8KB'
            for enc in ('utf-8', 'gbk', 'latin-1'):
                try:
                    return data.decode(enc)[:8000]
                except UnicodeDecodeError:
                    continue
            return '二进制文件不可读'
        except PermissionError:
            return '无权限读取'
    if tool == 'list_software':
        from .software import CATALOG, _platform_key
        pk = _platform_key()
        return '可用软件：' + '、'.join(f"{k}（{'可装' if pk in v['install'] else '手动'}）"
                                        for k, v in CATALOG.items())
    if tool == 'install_software':
        from .software import CATALOG, _platform_key
        key = str(p.get('key', '')).strip()
        if key not in CATALOG:
            return f'未知软件: {key}'
        cmd = CATALOG[key]['install'].get(_platform_key())
        if not cmd:
            return '当前平台不支持自动安装'
        threading.Thread(target=run_cmd, args=(cmd,),
                         kwargs={'timeout': 1800, 'shell': True}, daemon=True).start()
        return f'{CATALOG[key]["name"]} 安装任务已启动（后台执行）'
    if tool == 'create_site':
        from .routers.websites import _render_nginx
        from ..config import WWWROOT_DIR
        domain = str(p.get('domain', '')).strip().lower()
        if not re.match(r'^[a-z0-9\.\-]+$', domain):
            return '域名无效'
        if query('SELECT id FROM websites WHERE domain=?', (domain,), one=True):
            return '该域名已存在'
        title = str(p.get('title', domain))[:100]
        desc = str(p.get('desc', '由 锐同面板 AI 智能体创建'))[:200]
        root = os.path.join(WWWROOT_DIR, domain)
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;
justify-content:center;font-family:system-ui,'Microsoft YaHei',sans-serif;
background:linear-gradient(160deg,#0a0a0d,#1a1408);color:#ece7db}}
h1{{background:linear-gradient(135deg,#f5d061,#d4af37);-webkit-background-clip:text;
background-clip:text;color:transparent;font-size:48px;margin:0 0 16px}}
p{{color:#8d8677;max-width:600px;line-height:1.9;padding:0 20px;text-align:center}}</style>
</head><body><h1>{title}</h1><p>{desc}</p></body></html>''')
        execute('INSERT INTO websites (domain,root,port,type,engine,status,created_at) '
                'VALUES (?,?,?,?,?,1,?)', (domain, root, 80, 'static', 'nginx', now()))
        _render_nginx()
        run_cmd(['nginx', '-t'], timeout=30, shell=False)
        run_cmd(['nginx', '-s', 'reload'], timeout=30, shell=False)
        return f'网站 {domain} 创建成功（目录 {root}），已生成首页'
    if tool == 'create_proxy':
        from .routers.websites import _render_nginx
        domain = str(p.get('domain', '')).strip().lower()
        port = int(p.get('port', 80))
        target = str(p.get('target', '')).strip()
        if not re.match(r'^[a-z0-9\.\-]+$', domain) or not target:
            return '参数无效'
        execute('INSERT INTO websites (domain,root,port,type,engine,config,status,created_at) '
                'VALUES (?,?,?,?,?,?,1,?)',
                (domain, '', port, 'proxy', 'nginx', target, now()))
        _render_nginx()
        run_cmd(['nginx', '-t'], timeout=30, shell=False)
        run_cmd(['nginx', '-s', 'reload'], timeout=30, shell=False)
        return f'反向代理 {domain} → {target} 创建成功'
    if tool == 'list_sites':
        rows = query('SELECT domain,type,port,status FROM websites ORDER BY id DESC')
        return '网站列表：\n' + '\n'.join(
            f"{r['domain']}（{'反代' if r['type'] == 'proxy' else '静态'}，端口 {r['port']}，"
            f"{'启用' if r['status'] else '停用'}）" for r in rows) or '暂无网站'
    if tool == 'delete_site':
        from .routers.websites import _render_nginx
        domain = str(p.get('domain', '')).strip()
        execute('DELETE FROM websites WHERE domain=?', (domain,))
        _render_nginx()
        run_cmd(['nginx', '-t'], timeout=30, shell=False)
        run_cmd(['nginx', '-s', 'reload'], timeout=30, shell=False)
        return f'网站 {domain} 已删除'
    if tool == 'issue_ssl':
        # P-03 同源：这里原本复刻了 ssl.py 的字符串拼接命令，现在直接复用已校验的实现
        from .ssl import _cert_meta, _valid_domain
        from ..config import CERT_DIR as _CERT_DIR
        try:
            domain = _valid_domain(p.get('domain', ''))
        except Exception:
            return '域名格式不正确'
        d = os.path.join(_CERT_DIR, domain)
        os.makedirs(d, exist_ok=True)
        key = os.path.join(d, 'privkey.pem')
        cert = os.path.join(d, 'fullchain.pem')
        r = run_cmd(['openssl', 'req', '-x509', '-newkey', 'rsa:2048',
                     '-keyout', key, '-out', cert, '-days', '365', '-nodes',
                     '-subj', f'/CN={domain}',
                     '-addext', f'subjectAltName=DNS:{domain}'],
                    timeout=120, shell=False)
        if r['code'] != 0:
            return '证书生成失败：' + (r['stderr'] or '')[:200]
        try:
            os.chmod(key, 0o600)
        except Exception:
            pass
        meta = _cert_meta(cert)
        execute('INSERT OR REPLACE INTO ssl_certs (domain,type,cert_path,key_path,expires,created_at) '
                'VALUES (?,?,?,?,?,?)',
                (domain, 'selfsigned', cert, key, meta.get('expires'), now()))
        return f'已为 {domain} 生成自签名证书（有效期至 {meta.get("expires")}）'
    if tool == 'list_certs':
        rows = query('SELECT domain,type,expires FROM ssl_certs ORDER BY id DESC')
        return '证书列表：\n' + '\n'.join(f"{r['domain']}（{r['type']}）" for r in rows) or '暂无证书'
    if tool == 'list_databases':
        from .routers.databases import servers
        s = servers(user)
        return '数据库服务器：\n' + '\n'.join(
            f"{x['type']}（{'已连接' if x.get('connected') else '未连接'}）" for x in s['list'])
    if tool == 'create_database':
        kind = str(p.get('kind', 'sqlite'))
        db = str(p.get('db', '')).strip()
        if not db.replace('_', '').isalnum():
            return '数据库名无效'
        if kind == 'sqlite':
            import sqlite3
            sqlite3.connect(os.path.join(DATA_DIR, db + '.db')).close()
            return f'SQLite 数据库 {db} 已创建'
        return '目前仅支持 SQLite 自动创建（MySQL/PostgreSQL 请到数据库页操作）'
    if tool == 'query_db':
        sql = str(p.get('sql', '')).strip()
        if not re.match(r'^\s*(select|show|pragma|explain)\b', sql, re.I):
            return 'AI 仅允许只读 SELECT 查询'
        import sqlite3
        db = str(p.get('db', ''))
        fp = os.path.join(DATA_DIR, db + '.db') if db else os.path.join(DATA_DIR, 'rtpanel.db')
        if not os.path.isfile(fp):
            return '数据库不存在'
        conn = sqlite3.connect(fp)
        conn.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in conn.execute(sql).fetchall()[:30]]
        finally:
            conn.close()
        return json.dumps(rows, ensure_ascii=False, default=str)[:3000] or '（无结果）'
    if tool == 'backup_database':
        from .routers.databases import dump_database
        db = str(p.get('db', '')).strip() or 'rtpanel'
        r = dump_database('sqlite', db, os.path.join(DATA_DIR, 'backups', 'database'),
                          f'{db}_{int(now())}')
        return r.get('error') or f'数据库 {db} 备份完成：{r.get("path")}'
    if tool == 'open_port':
        port = int(p.get('port', 0))
        protocol = str(p.get('protocol', 'tcp')).lower()
        if not 0 < port < 65536 or protocol not in ('tcp', 'udp'):
            return '参数无效'
        from ..utils.exec_utils import IS_WIN
        name = str(p.get('name', ''))[:64]
        if not re.match(r'^[A-Za-z0-9 _-]*$', name):
            name = f'RTPanel-AI-{port}'
        if IS_WIN:
            # §0.2：改 argv（port 已过整数/范围校验、protocol 有白名单、name 有正则兜底）
            _script = ("New-NetFirewallRule -DisplayName '" + name + "' -Direction Inbound "
                       '-Protocol ' + protocol.upper() + ' -LocalPort ' + str(port) + ' -Action Allow')
            r = run_cmd(['powershell', '-NoProfile', '-Command', _script], timeout=60, shell=False)
        else:
            r = run_cmd(['iptables', '-I', 'INPUT', '-p', protocol,
                         '--dport', str(port), '-j', 'ACCEPT'], timeout=30, shell=False)
        return (f'端口 {port}/{protocol} 已放行' if r['code'] == 0
                else '放行失败: ' + r['stderr'][:200])
    if tool == 'block_ip':
        ip = str(p.get('ip', '')).strip()
        if not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
            return 'IP 无效'
        from ..utils.exec_utils import IS_WIN
        if IS_WIN:
            _script2 = ("New-NetFirewallRule -DisplayName 'RTPanel-AI-Block-" + ip
                        + "' -Direction Inbound -RemoteAddress " + ip + ' -Action Block')
            run_cmd(['powershell', '-NoProfile', '-Command', _script2], timeout=60, shell=False)
        else:
            run_cmd(['iptables', '-I', 'INPUT', '-s', ip, '-j', 'DROP'],
                    timeout=30, shell=False)
        return f'IP {ip} 已封禁'
    if tool == 'create_cron':
        from ..scheduler import next_runs
        name = str(p.get('name', '')).strip()
        schedule = str(p.get('schedule', '')).strip()
        command = str(p.get('command', '')).strip()
        if not name or not schedule or not command:
            return '参数不完整'
        if not next_runs(schedule, 1):
            return 'cron 表达式无效'
        execute('INSERT INTO cron_jobs (name,schedule,command,enabled,created_at) '
                'VALUES (?,?,?,1,?)', (name, schedule, command, now()))
        return f'计划任务「{name}」已创建'
    if tool == 'list_cron':
        rows = query('SELECT name,schedule,enabled,last_status FROM cron_jobs ORDER BY id DESC')
        return '计划任务：\n' + '\n'.join(
            f"{r['name']}（{r['schedule']}，{'启用' if r['enabled'] else '停用'}，"
            f"上次: {r['last_status'] or '未执行'}）" for r in rows) or '暂无任务'
    if tool == 'create_backup_task':
        name = str(p.get('name', '')).strip()
        path = str(p.get('path', '')).strip()
        if not name or not os.path.isdir(path):
            return '参数无效（目录不存在）'
        execute('INSERT INTO backup_tasks (name,type,source,dest,schedule,keep,enabled,created_at) '
                "VALUES (?,?,?,?,?,7,1,?)",
                (name, 'dir', path, os.path.join(DATA_DIR, 'backups'), '@daily', now()))
        return f'备份任务「{name}」已创建（每日执行，保留 7 份）'
    if tool == 'run_backup':
        from ..scheduler import run_backup
        rows = query("SELECT id FROM backup_tasks WHERE name=? AND enabled=1 ORDER BY id DESC LIMIT 1",
                     (str(p.get('name', '')).strip(),), one=True)
        if not rows:
            return '备份任务不存在'
        r = run_backup(rows['id'])
        return r.get('error') or f'备份完成：{r.get("file")}'
    if tool == 'list_backup_tasks':
        rows = query('SELECT name,type,source,enabled,last_status FROM backup_tasks ORDER BY id DESC')
        return '备份任务：\n' + '\n'.join(
            f"{r['name']}（{'目录' if r['type'] == 'dir' else '数据库'} {r['source']}，"
            f"上次: {r['last_status'] or '未执行'}）" for r in rows) or '暂无任务'
    if tool == 'docker_status':
        r = run_cmd('docker info --format "{{.ServerVersion}}|{{.Containers}}|{{.ContainersRunning}}"',
                    timeout=15)
        if r['code'] != 0:
            return 'Docker 不可用'
        v, total, running = r['stdout'].strip().split('|')
        return f'Docker v{v}：{running}/{total} 容器运行中'
    if tool == 'list_containers':
        r = run_cmd('docker ps -a --format "{{.Names}}|{{.Image}}|{{.Status}}"', timeout=15)
        if r['code'] != 0:
            return 'Docker 不可用'
        return '容器列表：\n' + r['stdout'] or '无容器'
    if tool == 'docker_action':
        c = str(p.get('container', '')).strip()
        a = str(p.get('action', '')).strip()
        if a not in ('start', 'stop', 'restart', 'remove'):
            return '操作无效'
        from .docker import _docker_id
        c = _docker_id(c, '容器标识')
        r = run_cmd(['docker', a, c], timeout=120, shell=False)
        return (f'容器 {c} {a} 完成' if r['code'] == 0 else '操作失败: ' + r['stderr'][:200])
    if tool == 'list_services':
        from .routers.services import service_list
        s = service_list(user)
        return '服务列表（前 20）：\n' + '\n'.join(
            f"{x['name']}（{x['status']}）" for x in s['list'][:20])
    if tool == 'service_action':
        # P-05：复用正规路由的校验与参数形式（原来自己拼 shell，action/name 无白名单，
        # Windows 分支的单引号还能逃逸）
        from .services import _service_name
        from ..utils.exec_utils import IS_WIN as _IS_WIN
        try:
            name = _service_name(p.get('name', ''))
        except Exception:
            return '服务名称格式无效'
        a = str(p.get('action', '')).strip()
        if a not in ('start', 'stop', 'restart', 'reload', 'enable', 'disable'):
            return '不支持的服务操作'
        if _IS_WIN:
            script = (f"$s = Get-Service -Name '{name}' -ErrorAction Stop; "
                      + ('$s | Start-Service' if a == 'start' else
                         '$s | Stop-Service' if a == 'stop' else
                         '$s | Restart-Service' if a == 'restart' else
                         f"Set-Service -Name '{name}' -StartupType "
                         + ('Automatic' if a == 'enable' else 'Disabled')))
            cmd = ['powershell', '-NoProfile', '-Command', script]
            r = run_cmd(cmd, timeout=120, shell=False)
        else:
            r = run_cmd(['systemctl', a, name], timeout=120, shell=False)
        return (f'已{ a }服务 {name}：' + ('成功' if r['code'] == 0 else (r['stderr'] or r['stdout'])[:200]))
    if tool == 'add_guardian':
        name = str(p.get('name', '')).strip()
        process = str(p.get('process', '')).strip()
        cmd = str(p.get('cmd', '')).strip()
        if not name or not process or not cmd:
            return '参数不完整'
        execute('INSERT INTO guardians (name,process,cmd,max_restarts,enabled,created_at) '
                'VALUES (?,?,?,10,1,?)', (name, process, cmd, now()))
        return f'进程守护「{name}」已添加'
    if tool == 'list_guardians':
        rows = query('SELECT name,process,enabled,last_restart FROM guardians ORDER BY id DESC')
        return '进程守护：\n' + '\n'.join(f"{r['name']}（{r['process']}）" for r in rows) or '暂无'
    if tool == 'deploy_app':
        from .software import deploy_core
        app = str(p.get('app', '')).strip()
        domain = str(p.get('domain', '')).strip()
        r = deploy_core(app, domain)
        return (f"一键部署完成：{domain}（数据库 {r.get('db', {}).get('db', '')}）"
                if r.get('ok') else '部署失败: ' + str(r.get('error', ''))[:200])
    if tool == 'list_ftp_users':
        rows = query('SELECT username,dir,note FROM ftp_users ORDER BY id DESC')
        return 'FTP 用户：\n' + '\n'.join(f"{r['username']} → {r['dir']}" for r in rows) or '暂无'
    if tool == 'create_ftp_user':
        from .ftp import ftp_create_core
        r = ftp_create_core(str(p.get('username', '')), str(p.get('dir', '')),
                            str(p.get('password', '')), str(p.get('note', '')))
        return 'FTP 账号已创建' if r.get('ok') else '创建失败: ' + str(r.get('error', ''))[:200]
    if tool == 'ssh_status':
        from .ssh import ssh_status_core
        r = ssh_status_core()
        if not r.get('supported'):
            return '当前系统不支持 SSH 管理'
        c = r.get('config') or {}
        return (f"SSH 状态：端口 {c.get('port', 22)}，root 登录 "
                f"{'允许' if c.get('permit_root') == 'yes' else '禁止'}，"
                f"密码认证 {'允许' if c.get('password_auth') == 'yes' else '禁止'}")
    if tool == 'waf_status':
        from .waf import waf_status
        r = waf_status(user=user)
        return (f"WAF：生效 {r['rules_enabled']}/{r['rules_total']} 条规则，"
                f"封禁 {r['ip_banned']} 个 IP，今日拦截 {r.get('today_hits', 0)} 次")
    if tool == 'list_waf_rules':
        rows = query('SELECT kind,pattern,enabled FROM waf_rules ORDER BY id DESC')
        return 'WAF 规则：\n' + '\n'.join(
            f"[{'开' if r['enabled'] else '关'}] {r['kind']} {r['pattern'][:60]}" for r in rows) or '暂无'
    if tool == 'list_hosts':
        from .dns import read_hosts_core
        entries = read_hosts_core().get('list', [])
        return 'hosts 条目：\n' + '\n'.join(f"{e['ip']} {e['domain']}" for e in entries[:30]) or '暂无'
    if tool == 'flush_dns':
        from .dns import flush_dns_core
        ok, out = flush_dns_core()
        return 'DNS 缓存已刷新' if ok else '刷新失败: ' + out[:100]
        return f'退出码 {r["code"]}：\n{out}' if out else f'退出码 {r["code"]}（无输出）'
    return f'未知工具: {tool}'
