# Created by 小杜 on 2026/08

"""通知渠道：邮件 / Webhook / 钉钉 / 企业微信 / 飞书。"""
import json
import smtplib
import urllib.request
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from ..database import query

CHANNELS = ['email', 'webhook', 'dingtalk', 'wecom', 'feishu']


def _cfg(channel: str) -> dict:
    row = query('SELECT config FROM notifications WHERE channel=?', (channel,), one=True)
    if not row:
        return {}
    try:
        return json.loads(row['config'])
    except Exception:
        return {}


# P-17：读取接口必须和写入接口一样掩码（原来 PUT 做了 ****** 掩码，GET 却明文回显口令）
_SENSITIVE_KEYS = ('password', 'passwd', 'secret', 'token', 'webhook_token', 'key')


def _mask_config(cfg: dict) -> dict:
    out = {}
    for k, v in (cfg or {}).items():
        if any(s in str(k).lower() for s in _SENSITIVE_KEYS) and v:
            out[k] = '******'
            out[k + '_set'] = True
        else:
            out[k] = v
    return out


def get_channels() -> list:
    out = []
    for ch in CHANNELS:
        row = query('SELECT enabled, config FROM notifications WHERE channel=?',
                    (ch,), one=True)
        raw = json.loads(row['config']) if row and row['config'] else {}
        out.append({'channel': ch, 'enabled': bool(row['enabled']) if row else False,
                    'config': _mask_config(raw)})
    return out


def send(title: str, content: str, only: list = None) -> dict:
    """向所有启用（或指定）的渠道发送告警。"""
    results = {}
    for ch in CHANNELS:
        if only and ch not in only:
            continue
        row = query('SELECT enabled FROM notifications WHERE channel=?', (ch,), one=True)
        if not row or not row['enabled']:
            continue
        cfg = _cfg(ch)
        try:
            if ch == 'email':
                results[ch] = _send_email(cfg, title, content)
            elif ch == 'webhook':
                results[ch] = _send_webhook(cfg, title, content)
            elif ch == 'dingtalk':
                results[ch] = _send_dingtalk(cfg, title, content)
            elif ch == 'wecom':
                results[ch] = _send_wecom(cfg, title, content)
            elif ch == 'feishu':
                results[ch] = _send_feishu(cfg, title, content)
        except Exception as e:
            results[ch] = {'ok': False, 'error': str(e)}
    return results


def _send_email(cfg: dict, title: str, content: str) -> dict:
    """邮件提醒：**由官网（厂商邮箱）代发**，用户只需填写自己的收件邮箱。

    设计：面板不保存任何 SMTP 口令，也不要求用户自建邮件服务；
    调用官网 `/api/v1/mail/send`（动态验证码认证）即可把提醒发到
    用户在面板里填写并**邮件确认过**的那个邮箱。
    兼容：若用户仍愿意自建 SMTP（老配置里有 host 且 password），则继续走本地发信。
    """
    host = str(cfg.get('host') or '').strip()
    password = str(cfg.get('password') or '')
    if host and password:
        # 兼容老配置：本地 SMTP 自建发信
        port = int(cfg.get('port', 465))
        user = cfg.get('user', '')
        to = cfg.get('to', '')
        ssl = bool(cfg.get('ssl', True))
        if not all([host, user, password, to]):
            return {'ok': False, 'error': '邮件配置不完整'}
        msg = MIMEText(content, 'plain', 'utf-8')
        msg['Subject'] = Header(title, 'utf-8')
        msg['From'] = formataddr(('锐同面板', user))
        msg['To'] = to
        if ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
        try:
            server.login(user, password)
            server.sendmail(user, to.split(','), msg.as_string())
        finally:
            server.quit()
        return {'ok': True}
    # 默认路径：官网代发（发件人是厂商邮箱，用户只填自己的收件邮箱）
    try:
        from ..site_mail import send_via_site
    except Exception as e:      # pragma: no cover
        return {'ok': False, 'error': f'代发模块不可用：{e}'}
    return send_via_site(title, content)


def _assert_public_url(url: str):
    """P-18：只允许 http(s) 且解析后必须是公网地址（挡内网/回环/云元数据/本机面板）。"""
    import ipaddress
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(str(url or '').strip())
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('通知地址必须是 http(s)')
    host = parsed.hostname or ''
    if not host:
        raise ValueError('通知地址缺少主机名')
    if parsed.port and parsed.port in (22, 25, 3306, 6379, 8000, 8800, 18888):
        raise ValueError('通知地址端口受限')
    ips = []
    try:
        ips.append(ipaddress.ip_address(host))
    except ValueError:
        try:
            for info in socket.getaddrinfo(host, None):
                ips.append(ipaddress.ip_address(info[4][0]))
        except Exception as e:
            raise ValueError(f'域名无法解析：{e}')
    for ip in ips:
        if (not ip.is_global) or ip.is_loopback or ip.is_private or ip.is_link_local:
            raise ValueError(f'通知地址不能指向内网/本机：{ip}')


def _http_post(url: str, payload: dict, headers: dict = None, timeout: int = 10) -> dict:
    try:
        _assert_public_url(url)
    except ValueError as e:
        return {'ok': False, 'error': str(e)}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/json',
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(4096).decode('utf-8', 'ignore')
    # P-18：响应体不再原样回显给调用方（避免把内网数据带出来），只给状态与长度
    return {'ok': True, 'bytes': len(body)}


def _send_webhook(cfg: dict, title: str, content: str) -> dict:
    url = cfg.get('url', '')
    if not url:
        return {'ok': False, 'error': 'URL 未配置'}
    return _http_post(url, {'title': title, 'content': content},
                      cfg.get('headers') or {})


def _send_dingtalk(cfg: dict, title: str, content: str) -> dict:
    token = cfg.get('token', '')
    secret = cfg.get('secret', '')
    if not token:
        return {'ok': False, 'error': 'access_token 未配置'}
    if secret:
        import hashlib
        import hmac
        import time
        import base64
        ts = str(round(time.time() * 1000))
        sign_str = f'{ts}\n{secret}'
        h = hmac.new(secret.encode(), sign_str.encode(), hashlib.sha256).digest()
        sign = base64.b64encode(h).decode()
        url = f'https://oapi.dingtalk.com/robot/send?access_token={token}&timestamp={ts}&sign={sign}'
    else:
        url = f'https://oapi.dingtalk.com/robot/send?access_token={token}'
    payload = {'msgtype': 'markdown',
               'markdown': {'title': title, 'text': f'### {title}\n\n{content}'}}
    return _http_post(url, payload)


def _send_wecom(cfg: dict, title: str, content: str) -> dict:
    key = cfg.get('key', '')
    if not key:
        return {'ok': False, 'error': '机器人 key 未配置'}
    url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}'
    payload = {'msgtype': 'markdown', 'markdown': {'content': f'**{title}**\n{content}'}}
    return _http_post(url, payload)


def _send_feishu(cfg: dict, title: str, content: str) -> dict:
    url = cfg.get('url', '')
    if not url:
        return {'ok': False, 'error': '飞书 webhook URL 未配置'}
    payload = {'msg_type': 'text', 'content': {'text': f'{title}\n{content}'}}
    return _http_post(url, payload)
