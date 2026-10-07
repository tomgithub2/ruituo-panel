# Created by 小杜 on 2026/08

"""仪表盘：实时概览 + WebSocket 实时指标推送。"""
import asyncio
import json
import time

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..auth import decode_token, get_current_user
from ..config import PANEL_VERSION, get_config
from ..database import now, query
from ..rbac import role_permissions
from ..utils import sysinfo

router = APIRouter(prefix='/api/dashboard', tags=['dashboard'])

# 实时推送频率（秒）：太密会刷爆前端，太疏没实时感
_WS_TICK = 2
# 告警只按最近一天算，跨天不重复计
_TODAY_WINDOW = 86400


def _ws_origin_ok(ws) -> bool:
    """校验 WebSocket 来源与访问 Host 一致，防止跨站 WebSocket 劫持（CSWSH）。"""
    origin = ws.headers.get('origin', '')
    host = ws.headers.get('host', '')
    if not origin or not host:
        return True  # 非浏览器客户端（脚本/工具）不强制
    try:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        return parsed.scheme in ('http', 'https') and parsed.netloc == host
    except Exception:
        return False


@router.get('/overview')
def overview(user: dict = Depends(get_current_user)):
    data = sysinfo.overview()
    if not data:
        data = {}
    data['panel'] = {
        'version': PANEL_VERSION,
        'site_name': get_config().get('site_name', '芮拓面板'),
        'started_at': getattr(router, '_started_at', now()),
        'is_admin': user['role'] == 'admin',
        'elevated': True,
    }
    data['counts'] = {
        'users': query('SELECT COUNT(*) c FROM users', one=True)['c'],
        'cron_jobs': query('SELECT COUNT(*) c FROM cron_jobs WHERE enabled=1', one=True)['c'],
        'websites': query('SELECT COUNT(*) c FROM websites', one=True)['c'],
        'backup_tasks': query('SELECT COUNT(*) c FROM backup_tasks', one=True)['c'],
        'alerts_today': query("SELECT COUNT(*) c FROM alert_history WHERE ts > ?",
                              (now() - _TODAY_WINDOW, ), one=True)['c'],
    }
    return data
@router.get('/sparkline')
def sparkline(minutes: int = 30, user: dict = Depends(get_current_user)):
    """仪表盘迷你曲线数据（原始采样）。"""
    sinceTs = now() - minutes * 60
    rowsList = query(
        'SELECT ts,cpu,mem,net_rx,net_tx FROM metric_raw WHERE ts>? ORDER BY ts ASC',
        (sinceTs,))
    return {'list': rowsList}


@router.websocket('/ws/realtime')
async def ws_realtime(ws: WebSocket):
    """实时推送：每 2 秒发送经过认证的 CPU、内存和网络速率。"""
    # 浏览器 WebSocket 无法携带 Authorization 头，令牌由前端以查询参数传入。
    # 认证必须在 accept 前完成，避免匿名客户端订阅主机实时状态。
    if not _ws_origin_ok(ws):
        await ws.close(code=1008, reason='Origin rejected')
        return
    token = ws.query_params.get('token', '')
    try:
        payload = decode_token(token)
        user = query('SELECT id,role FROM users WHERE id=? AND status=1',
                     (payload['uid'],), one=True)
        if not user or (user['role'] != 'admin' and
                        'dashboard:view' not in role_permissions(user['role'])):
            raise ValueError('user disabled')
    except Exception:
        await ws.close(code=1008, reason='Unauthorized')
        return

    await ws.accept()
    previous_net = None
    previous_ts = None
    try:
        while True:
            try:
                memInfo = sysinfo.psutil.virtual_memory()
                netIo = sysinfo.psutil.net_io_counters()
                current_ts = time.time()
                if previous_net is None or previous_ts is None:
                    rx_rate = tx_rate = 0
                else:
                    elapsed = max(current_ts - previous_ts, 0.001)
                    rx_rate = max(0, (netIo.bytes_recv - previous_net.bytes_recv) / elapsed)
                    tx_rate = max(0, (netIo.bytes_sent - previous_net.bytes_sent) / elapsed)
                previous_net, previous_ts = netIo, current_ts
                loadAvg = sysinfo.os.getloadavg() if hasattr(sysinfo.os, 'getloadavg') else (0, 0, 0)
                pushBody = {
                    'ts': current_ts,
                    'cpu': sysinfo.psutil.cpu_percent(interval=None),
                    'mem': memInfo.percent,
                    'net_rx': rx_rate,
                    'net_tx': tx_rate,
                    'load1': loadAvg[0] if loadAvg else 0,
                }
                await ws.send_text(json.dumps(pushBody))
            except Exception:
                break
            # 卧槽，不加这个延时前端 chart 会被推刷到卡死，先这样顶着
            await asyncio.sleep(_WS_TICK)
    except WebSocketDisconnect:
        pass
