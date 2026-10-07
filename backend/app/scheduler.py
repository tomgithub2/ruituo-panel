# Created by 小杜 on 2026/08

"""后台调度：指标采样/聚合、计划任务执行、备份任务、告警检查、SSL 续期。"""
import json
import os
import threading
import time
import traceback

import psutil

from .config import (BACKUP_DIR, CERT_DIR, get_config, save_config)
from .database import execute, now, query
from .utils import sysinfo
from .utils.notifier import send as send_notify

_stop = threading.Event()
_threads = []

# 采样兜底间隔（老机器上 psutil 偶尔抽风时用）
_FALLBACK_INTERVAL = 5
# 先留 5 秒缓冲给调度循环，懒得做精确对齐了
_ONCE_GRACE = 5


# ---------------------------------------------------------------- cron 解析
def _cron_field_ok(value: int, field: str) -> bool:
    if field == '*':
        return True
    for part in field.split(','):
        if part == '*':
            return True
        step = 1
        if '/' in part:
            part, step = part.split('/', 1)
            step = int(step)
        if '-' in part:
            lo, hi = part.split('-', 1)
            if int(lo) <= value <= int(hi) and (value - int(lo)) % step == 0:
                return True
        elif part.isdigit() and int(part) == value:
            return True
    return False


def cron_matches(schedule: str, dt) -> bool:
    """支持 5 段 cron 与 @every 30s/@hourly/@daily 等简化写法。"""
    schedule = schedule.strip()
    if schedule.startswith('@every'):
        return True  # 由 _should_run_every 单独处理
    if schedule == '@once':
        return True  # 执行一次：创建后立即运行（由 last_run 去重）
    if schedule == '@hourly':
        return dt.minute == 0
    if schedule == '@daily':
        return dt.hour == 0 and dt.minute == 0
    if schedule == '@weekly':
        return dt.weekday() == 0 and dt.hour == 0 and dt.minute == 0
    if schedule == '@monthly':
        return dt.day == 1 and dt.hour == 0 and dt.minute == 0
    timeParts = schedule.split()
    if not timeParts or len(timeParts) != 5:
        return False
    fen, shi, ri, yue, xingqi = timeParts
    return (_cron_field_ok(dt.minute, fen)
            and _cron_field_ok(dt.hour, shi)
           and _cron_field_ok(dt.day, ri)
            and _cron_field_ok(dt.month, yue)
            and _cron_field_ok((dt.weekday() + 1) % 7, xingqi))


def parse_every(schedule: str) -> int:
    """@every 语法 → 秒数；非 @every 返回 0。"""
    schedule = schedule.strip()
    if not schedule.startswith('@every'):
        return 0
    unitStr = schedule[6:].strip().lower()
    try:
        numVal = int(unitStr[:-1])
        unitCh = unitStr[-1]
    except (ValueError, IndexError):
        return 0
    beiLv = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}.get(unitCh, 0)
    return numVal * beiLv


def next_runs(schedule: str, count: int = 5) -> list:
    """计算未来执行时间（约算，@every 精确）。"""
    schedule = schedule.strip()
    if schedule == '@once':
        # 执行一次：下一次调度循环立即执行（10 秒内）
        return [int(time.time()) + _ONCE_GRACE]
    everySec = parse_every(schedule)
    if everySec:
        jiZhun = int(time.time()) // everySec * everySec
        return [jiZhun + everySec * i for i in range(1, count + 1)]
    import datetime
    out = []
    tsNow = int(time.time())
    for _ in range(count * 2880):  # 最多扫 10 天
        tsNow += 60
        dtObj = datetime.datetime.fromtimestamp(tsNow)
        if cron_matches(schedule, dtObj):
            out.append(tsNow)
            if len(out) >= count:
                break
    return out



# ================== 下面这块是采样和聚合，别乱动 ==================
# ---------------------------------------------------------------- 指标采样
def _sample_loop():
    cfg = get_config()
    interval = int(cfg.get('sample_interval', 5))
    raw_hours = int(cfg.get('keep_raw_hours', 24))
    while not _stop.is_set():
        # 采样间隔兜底：万一配置文件被改坏就按 5 秒来
        sleepSec = interval if interval > 0 else _FALLBACK_INTERVAL
        try:
            cpuPct = psutil.cpu_percent(interval=None)
            memInfo = psutil.virtual_memory()
            netIo = psutil.net_io_counters()
            diskIo = psutil.disk_io_counters()
            loadAvg = os.getloadavg() if hasattr(os, 'getloadavg') else (0, 0, 0)
            # ts_str = time.strftime('%Y-%m-%d %H:%M:%S')  # 已弃用（字符串排序会乱），保留参考
            execute(
                'INSERT INTO metric_raw (ts,cpu,mem,mem_used,mem_total,net_rx,net_tx,'
                'disk_read,disk_write,load1,load5,load15,proc_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (now(), cpuPct, memInfo.percent, memInfo.used, memInfo.total,
                 netIo.bytes_recv, netIo.bytes_sent,
                 diskIo.read_bytes if diskIo else 0, diskIo.write_bytes if diskIo else 0,
                 loadAvg[0] if len(loadAvg) > 0 else 0, loadAvg[1] if len(loadAvg) > 1 else 0,
                 loadAvg[2] if len(loadAvg) > 2 else 0, len(psutil.pids())))
        except Exception:
            pass
        try:
            execute('DELETE FROM metric_raw WHERE ts < ?', (now() - raw_hours * 3600,))
        except Exception:
            pass
        _stop.wait(sleepSec)


def _aggregate_loop():
    """每 10 分钟把超过 1 小时的原始采样聚合成 5 分钟粒度历史。"""
    hist_days = int(get_config().get('keep_history_days', 90))
    while not _stop.is_set():
        _stop.wait(600)
        if _stop.is_set():
            break
        try:
            cutoff = now() - 3600
            rows = query(
                'SELECT ts,cpu,mem,net_rx,net_tx,disk_read,disk_write,load1 FROM metric_raw WHERE ts < ?',
                (cutoff,))
            if not rows:
                continue
            buckets = {}
            for r in rows:
                key = int(r['ts'] // 300) * 300
                buckets.setdefault(key, []).append(r)
            for key, items in buckets.items():
                n = len(items)
                avg = lambda f: round(sum(x[f] for x in items) / n, 3)  # noqa: E731
                execute(
                    'INSERT INTO metric_history (ts,cpu,mem,net_rx,net_tx,disk_read,disk_write,load1) '
                    'VALUES (?,?,?,?,?,?,?,?)',
                    (key, avg('cpu'), avg('mem'), avg('net_rx'), avg('net_tx'),
                     avg('disk_read'), avg('disk_write'), avg('load1')))
            execute('DELETE FROM metric_raw WHERE ts < ?', (cutoff,))
            execute('DELETE FROM metric_history WHERE ts < ?',
                    (now() - hist_days * 86400,))
        except Exception:
            traceback.print_exc()


# ---------------------------------------------------------------- 告警检查
def _alert_loop():
    cfg = get_config()
    while not _stop.is_set():
        _stop.wait(30)
        if _stop.is_set():
            break
        try:
            _check_alerts()
        except Exception:
            pass


def _check_alerts():
    rules = query('SELECT * FROM alert_rules WHERE enabled=1')
    if not rules:
        return
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.1)
    rows = query('SELECT * FROM metric_raw ORDER BY ts DESC LIMIT 300')
    if not rows:
        return
    mem_pct = vm.percent
    values = {
        'cpu': cpu,
        'mem': mem_pct,
        'load1': rows[0]['load1'],
        'disk': _max_disk_pct(),
    }
    for rule in rules:
        metric = rule['metric']
        if metric not in values:
            continue
        v = values[metric]
        fired = v > rule['threshold'] if rule['operator'] in ('>', 'gt') else v < rule['threshold']
        if not fired:
            continue
        if rule['last_fired'] and (now() - rule['last_fired']) < 3600:
            continue  # 1 小时内不重复告警
        level = 'critical' if metric in ('mem', 'disk') else 'warning'
        msg = f'[{rule["metric"]}] 当前值 {v}，阈值 {rule["operator"]} {rule["threshold"]}'
        execute('UPDATE alert_rules SET last_fired=? WHERE id=?', (now(), rule['id']))
        execute('INSERT INTO alert_history (ts,metric,level,message,status) VALUES (?,?,?,?,?)',
                (now(), metric, level, msg, 'fired'))
        channels = [c for c in (rule['channels'] or '').split(',') if c]
        try:
            send_notify(f'芮拓面板 告警: {msg}', f'时间: {time.strftime("%Y-%m-%d %H:%M:%S")}\n{msg}',
                        only=channels or None)
        except Exception:
            pass


def _max_disk_pct() -> float:
    try:
        return max(p.percent for p in psutil.disk_partitions()
                   if psutil.disk_usage(p.mountpoint).percent > 0) if psutil.disk_partitions() else 0
    except Exception:
        return 0


# ---------------------------------------------------------------- 计划任务
def _cron_loop():
    while not _stop.is_set():
        _stop.wait(10)
        if _stop.is_set():
            break
        try:
            _run_due_jobs()
            _run_due_backups()
        except Exception:
            pass


def _run_due_jobs():
    import datetime
    jobs = query('SELECT * FROM cron_jobs WHERE enabled=1')
    dt_now = datetime.datetime.now()
    for job in jobs:
        every = parse_every(job['schedule'])
        due = False
        if every:
            last = job['last_run'] or 0
            due = (now() - last) >= every - 1
        elif job['schedule'] == '@once':
            # 执行一次：仅当从未执行过
            due = not job['last_run']
        else:
            due = cron_matches(job['schedule'], dt_now) and (
                not job['last_run'] or (now() - job['last_run']) >= 59)
        if due:
            run_job(job['id'])
        # @once 执行完成后自动删除（执行一次语义，需重查 DB 的 last_run）
        if job['schedule'] == '@once':
            fresh = query('SELECT last_run FROM cron_jobs WHERE id=?', (job['id'],), one=True)
            if fresh and fresh['last_run']:
                from .audit import audit
                audit('system', '', 'cron_once_done',
                      f'一次性任务 [{job["name"]}] 执行完成，已自动删除')
                execute('DELETE FROM cron_runs WHERE job_id=?', (job['id'],))
                execute('DELETE FROM cron_jobs WHERE id=?', (job['id'],))


def run_job(job_id: int) -> dict:
    job = query('SELECT * FROM cron_jobs WHERE id=?', (job_id,), one=True)
    if not job:
        return {'ok': False, 'error': '任务不存在'}
    from .utils.exec_utils import run_cmd
    t0 = time.time()
    # P-25a：URL 任务用 argv 形式执行（不再把 URL 交给 shell）；其余命令保持原样
    cmd = job['command'] or ''
    if cmd.startswith('url:'):
        r = run_cmd(['curl', '-fsS', '--max-time', '60', cmd[4:]], timeout=120, shell=False)
    else:
        r = run_cmd(cmd, timeout=int(job.get('timeout') or 3600), shell=True)
    duration = round(time.time() - t0, 2)
    output = (r['stdout'] + r['stderr'])[-4000:]
    code = r['code'] if r['code'] is not None else -1
    execute('INSERT INTO cron_runs (job_id,ts,exit_code,output,duration) VALUES (?,?,?,?,?)',
            (job_id, now(), code, output, duration))
    execute('UPDATE cron_jobs SET last_run=?, last_status=?, last_output=? WHERE id=?',
            (now(), 'success' if code == 0 else 'failed', output[:500], job_id))
    # 清理执行记录（保留最近 200 条）
    execute('DELETE FROM cron_runs WHERE job_id=? AND id NOT IN '
            '(SELECT id FROM cron_runs WHERE job_id=? ORDER BY id DESC LIMIT 200)',
            (job_id, job_id))
    if job['notify'] and code != 0:
        try:
            send_notify(f'计划任务失败: {job["name"]}',
                        f'命令: {job["command"]}\n输出:\n{output}')
        except Exception:
            pass
    from .audit import audit
    audit('system', '', 'cron_run', f'计划任务 [{job["name"]}] 执行完成 exit={code}')
    return {'ok': True, 'code': code, 'output': output, 'duration': duration}


# ---------------------------------------------------------------- 备份任务
def _run_due_backups():
    import datetime
    tasks = query('SELECT * FROM backup_tasks WHERE enabled=1')
    dt_now = datetime.datetime.now()
    for task in tasks:
        schedule = task['schedule']
        due = False
        if schedule.startswith('@every'):
            every = parse_every(schedule)
            last = task['last_run'] or 0
            due = every > 0 and (now() - last) >= every - 1
        elif schedule == '@daily':
            due = dt_now.hour == 3 and dt_now.minute < 10 and (
                not task['last_run'] or now() - task['last_run'] > 3600)
        elif schedule:
            due = cron_matches(schedule, dt_now) and (
                not task['last_run'] or now() - task['last_run'] > 59)
        if due:
            run_backup(task['id'])


def run_backup(task_id: int) -> dict:
    task = query('SELECT * FROM backup_tasks WHERE id=?', (task_id,), one=True)
    if not task:
        return {'ok': False, 'error': '任务不存在'}
    import datetime
    import shutil
    import zipfile
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = ''.join(c for c in task['name'] if c.isalnum() or c in '-_') or 'backup'
    dest_dir = os.path.join(BACKUP_DIR, safe_name)
    os.makedirs(dest_dir, exist_ok=True)
    try:
        if task['type'] == 'dir':
            zip_path = os.path.join(dest_dir, f'{safe_name}_{stamp}.zip')
            _zip_dir(task['source'], zip_path, exclude=(task['exclude'] or ''))
            result_file = zip_path
        elif task['type'] == 'db':
            from .routers.databases import dump_database
            kind, dbname = task['source'].split(':', 1)
            r = dump_database(kind, dbname, dest_dir, f'{dbname}_{stamp}')
            if not r.get('ok'):
                raise RuntimeError(r.get('error', '备份失败'))
            result_file = r['path']
        else:
            return {'ok': False, 'error': '未知备份类型'}
        execute('UPDATE backup_tasks SET last_run=?, last_status=? WHERE id=?',
                (now(), 'success', task_id))
        _cleanup_keep(dest_dir, int(task['keep']))
        if task['notify']:
            send_notify(f'备份完成: {task["name"]}', f'文件: {result_file}')
        from .audit import audit
        audit('system', '', 'backup_run', f'备份任务 [{task["name"]}] 完成 → {result_file}')
        return {'ok': True, 'file': result_file}
    except Exception as e:
        execute('UPDATE backup_tasks SET last_run=?, last_status=? WHERE id=?',
                (now(), 'failed: ' + str(e)[:200], task_id))
        return {'ok': False, 'error': str(e)}


def _zip_dir(src: str, dest: str, exclude: str = ''):
    import zipfile
    excludes = [e.strip() for e in exclude.split(',') if e.strip()]
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
        base = os.path.abspath(src)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not any(
                os.path.join(root, d).replace('\\', '/').find(e) >= 0 for e in excludes)]
            for f in files:
                fp = os.path.join(root, f)
                if any(fp.replace('\\', '/').find(e) >= 0 for e in excludes):
                    continue
                arc = os.path.relpath(fp, os.path.dirname(base))
                zf.write(fp, arc)


def _cleanup_keep(dest_dir: str, keep: int):
    files = sorted(
        (os.path.join(dest_dir, f) for f in os.listdir(dest_dir)),
        key=os.path.getmtime, reverse=True)
    for f in files[keep:]:
        try:
            os.remove(f)
        except Exception:
            pass


# ---------------------------------------------------------------- SSL 续期
def _ssl_renew_loop():
    while not _stop.is_set():
        _stop.wait(86400)
        try:
            certs = query('SELECT * FROM ssl_certs WHERE auto_renew=1')
            for c in certs:
                if c['expires'] and (c['expires'] - now()) < 86400 * 20:
                    from .routers.ssl import renew_cert
                    renew_cert(c['id'])
        except Exception:
            pass


# ---------------------------------------------------------------- 启动/停止
def start():
    if _threads:
        return
    cfg = get_config()
    if not cfg.get('initialized'):
        save_config({'initialized': True})
    loops = [_sample_loop, _aggregate_loop, _alert_loop, _cron_loop, _ssl_renew_loop,
             _guardian_loop, _ai_knowledge_loop, _waf_scan_loop, _waf_crowd_loop, _unban_loop,
             _waf_telemetry_loop]
    for fn in loops:
        t = threading.Thread(target=fn, daemon=True, name=f'ops-{fn.__name__}')
        t.start()
        _threads.append(t)


def _waf_scan_loop():
    """WAF 防御大屏：每 60 秒增量解析 Nginx 日志，归类拦截记录。"""
    while not _stop.is_set():
        _stop.wait(60)
        if _stop.is_set():
            break
        try:
            from .routers.waf import scan_waf_hits
            scan_waf_hits()
        except Exception:
            pass


def _unban_loop():
    """P-11：到期自动解封（自动封禁只封 30 分钟，不是永久）。"""
    while not _stop.is_set():
        _stop.wait(60)
        if _stop.is_set():
            break
        try:
            from .database import execute, now, query
            from .routers.firewall import unblock_ip_core
            rows = query("SELECT ip FROM ip_blocks WHERE expires_at IS NOT NULL AND expires_at<=?",
                         (now(),))
            for r in rows:
                if unblock_ip_core(r["ip"]):
                    execute("DELETE FROM ip_blocks WHERE ip=?", (r["ip"],))
        except Exception:
            pass


def _waf_crowd_loop():
    """多机辅助测试：每 45 秒尝试领取并执行一次其他机器的 WAF 测试任务。"""
    while not _stop.is_set():
        _stop.wait(45)
        if _stop.is_set():
            break
        try:
            from .waf_crowd import poll_once
            poll_once()
        except Exception:
            pass


def _waf_telemetry_loop():
    """多机遥测：开关开启时，每 60 分钟借用其他机器测一次本机站点（关闭则完全不动）。"""
    while not _stop.is_set():
        _stop.wait(600)
        if _stop.is_set():
            break
        try:
            cfg = get_config()
            if not cfg.get('waf_telemetry'):
                continue
            from .waf_crowd import telemetry_last, telemetry_run
            last = telemetry_last()
            if time.time() - float(last.get('ts') or 0) < 3600:
                continue
            telemetry_run()
        except Exception:
            pass


def _guardian_loop():
    """进程守护：每 30 秒检查并拉起挂掉的进程。"""
    while not _stop.is_set():
        _stop.wait(30)
        if _stop.is_set():
            break
        try:
            from .routers.guardian import _check_all
            _check_all()
        except Exception:
            pass


def _ai_knowledge_loop():
    """AI 知识库：每 30 分钟检测一次，有变更且开启上传且已绑定时同步到官网。"""
    while not _stop.is_set():
        _stop.wait(1800)
        if _stop.is_set():
            break
        try:
            from .routers.ai import _knowledge_dirty, upload_knowledge, _load_config
            if not _knowledge_dirty.is_set():
                continue
            cfg = _load_config()
            if not cfg.get('upload_enabled', False):   # P-25q：默认关闭（与 ai.py 保持一致）
                continue
            from . import binding
            if binding.status()['mode'] != 'bound':
                continue
            result = upload_knowledge()
            if result.get('ok'):
                _knowledge_dirty.clear()
                cfg['last_upload'] = time.time()
                _save_ai_cfg(cfg)
        except Exception:
            pass


def _save_ai_cfg(cfg):
    import json
    from .config import DATA_DIR
    try:
        with open(os.path.join(DATA_DIR, 'ai_config.json'), 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def stop():
    _stop.set()
