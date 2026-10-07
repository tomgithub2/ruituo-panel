# Created by 小杜 on 2026/08

"""厂商工具：构建源码完整性清单（SHA-256 + RSA 签名）。

用法:
    python tools/build_manifest.py

生成两份独立清单：
  backend/integrity_manifest.json   → 面板分发包（用户部署，面板自检用）
# [官网相关路径已脱敏：官网不开源，内部结构不公开]

面板与官网完全分离：面板包不含官网代码，官网包由厂商独占部署。
"""
import base64
import hashlib
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'backend', '.deps'))

# 面板清单范围（随面板分发包走）
PANEL_SCOPE = ['backend/app', 'backend/run.py', 'backend/requirements.txt',
               'frontend/dist/js', 'frontend/dist/css', 'frontend/dist/index.html',
               'frontend/dist/vendor',
               'frontend/dist/app.js',
               'start.bat', 'start.sh']

# 官网清单范围（仅厂商部署）
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
# [官网相关路径已脱敏：官网不开源，内部结构不公开]

EXCLUDE_DIRS = {'__pycache__', '.deps', 'venv', 'node_modules', 'data'}
EXCLUDE_EXT = {'.pyc', '.log', '.db', '.sqlite'}


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode('utf-8')


def collect(root: str, scope: list) -> dict:
    files = {}
    for s in scope:
        sp = os.path.join(root, s)
        if not os.path.exists(sp):
            print(f'[!] 跳过不存在的路径: {s}')
            continue
        targets = [sp] if os.path.isfile(sp) else []
        if os.path.isdir(sp):
            for dirpath, dirnames, filenames in os.walk(sp):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for fn in filenames:
                    if os.path.splitext(fn)[1] in EXCLUDE_EXT:
                        continue
                    targets.append(os.path.join(dirpath, fn))
        for fp in targets:
            h = hashlib.sha256()
            with open(fp, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    h.update(chunk)
            rel = os.path.relpath(fp, root).replace('\\', '/')
            files[rel] = h.hexdigest()
    return files


def build_manifest(key, scope: list, out_path: str, product: str):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    files = collect(BASE, scope)
    payload = {
        'product': product,
        'version': '1.0.0',
        'generated_at': int(time.time()),
        'files': files,
    }
    sig = key.sign(canonical(payload), padding.PKCS1v15(), hashes.SHA256())
    payload['signature'] = base64.b64encode(sig).decode()
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f'[OK] {os.path.basename(out_path)}: 登记 {len(files)} 个文件')
    return len(files)


def main():
    priv_path = os.path.join(BASE, 'keys', 'ops_private.pem')
    if not os.path.isfile(priv_path):
        print('[!] 未找到私钥，请先运行: python tools/gen_keys.py')
        sys.exit(1)
    from cryptography.hazmat.primitives import serialization

    with open(priv_path, 'rb') as f:
        key = serialization.load_pem_private_key(f.read(), password=None)

    n1 = build_manifest(key, PANEL_SCOPE,
                        os.path.join(BASE, 'backend', 'integrity_manifest.json'),
                        '锐同面板')
    n2 = build_manifest(key, SITE_SCOPE,
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
                        '锐同面板官网')


if __name__ == '__main__':
    main()
