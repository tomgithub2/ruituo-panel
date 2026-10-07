"""厂商工具：构建面板更新包（热更新/一键更新）。

用法:
    python tools/build_update_pkg.py [版本号]

产出（上传到官网 /update/ 目录）:
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
"""
import base64
import hashlib
import json
import os
import sys
import time
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'backend', '.deps'))

VERSION = sys.argv[1] if len(sys.argv) > 1 else '1.1.0'

# 与 tools/build_manifest.py 的 PANEL_SCOPE 保持一致
PANEL_SCOPE = ['backend/app', 'backend/run.py', 'backend/requirements.txt',
               'frontend/dist/js', 'frontend/dist/css', 'frontend/dist/index.html',
               'frontend/dist/vendor', 'frontend/dist/app.js',
               'start.bat', 'start.sh']
EXCLUDE_DIRS = {'__pycache__', '.deps', 'venv', 'node_modules', 'data'}
EXCLUDE_EXT = {'.pyc', '.log', '.db', '.sqlite'}

# [官网相关路径已脱敏：官网不开源，内部结构不公开]


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode('utf-8')


def collect() -> dict:
    files = {}
    for scope in PANEL_SCOPE:
        sp = os.path.join(BASE, scope)
        if not os.path.exists(sp):
            continue
        targets = [sp] if os.path.isfile(sp) else []
        if os.path.isdir(sp):
            for r, d, fs in os.walk(sp):
                d[:] = [x for x in d if x not in EXCLUDE_DIRS]
                for f in fs:
                    if os.path.splitext(f)[1] in EXCLUDE_EXT:
                        continue
                    targets.append(os.path.join(r, f))
        for fp in targets:
            h = hashlib.sha256()
            with open(fp, 'rb') as fh:
                for chunk in iter(lambda: fh.read(65536), b''):
                    h.update(chunk)
            files[os.path.relpath(fp, BASE).replace('\\', '/')] = h.hexdigest()
    return files


def main():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key_path = os.path.join(BASE, 'keys', 'ops_private.pem')
    if not os.path.isfile(key_path):
        print('[!] 未找到私钥，请先运行: python tools/gen_keys.py')
        sys.exit(1)
    with open(key_path, 'rb') as f:
        key = serialization.load_pem_private_key(f.read(), password=None)

    files = collect()
    os.makedirs(OUT_DIR, exist_ok=True)

    # 更新包
    zip_name = f'rt-panel-update-{VERSION}.zip'
    zip_path = os.path.join(OUT_DIR, zip_name)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(os.path.join(BASE, rel.replace('/', os.sep)), rel)

    # 签名清单：签名覆盖「除 signature 外的全部字段」。
    # 早先只签 files，导致 version/url/size 可被改（P-10：强制降级 + url 未签可做 SSRF），
    # 面板侧已同步改为校验整份清单，这里必须一致，否则新旧不兼容。
    manifest = {
        'product': '芮拓面板',
        'version': VERSION,
        'generated_at': int(time.time()),
        'files': files,
    }
    sig = key.sign(canonical(manifest), padding.PKCS1v15(), hashes.SHA256())
    manifest['signature'] = base64.b64encode(sig).decode()

    # latest.json
    latest = {
        'version': VERSION,
        'notes': sys.argv[2] if len(sys.argv) > 2 else f'芮拓面板 v{VERSION} 更新',
        'url': f'/update/{zip_name}',
        'size': os.path.getsize(zip_path),
        'manifest': manifest,
    }
    with open(os.path.join(OUT_DIR, 'latest.json'), 'w', encoding='utf-8') as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)

    print(f'[OK] 更新包: {zip_path} ({os.path.getsize(zip_path) / 1024 / 1024:.1f} MB)')
    print(f'[OK] 更新清单: {os.path.join(OUT_DIR, "latest.json")}')
    print(f'[OK] 共 {len(files)} 个文件 | 发布: 将 update/ 目录上传到官网根目录即可')


if __name__ == '__main__':
    main()
