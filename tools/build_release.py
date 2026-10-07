# Created by 小杜 on 2026/08

"""发布打包工具：生成 Linux tar.gz 与 Windows installer.exe。

用法:
    python tools/build_release.py

产出:
    release/dist/rt-panel-2.0.0-rc3.tar.gz   (Linux 一键安装包)
    release/dist/rt-panel-setup-1.0.0.exe (Windows 安装程序)
"""
import os
import shutil
import subprocess
import sys
import tarfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE = os.path.join(BASE, 'release')
DIST = os.path.join(RELEASE, 'dist')
VERSION = '2.0.0-rc3'

# 面板分发包内容（仅用户部署所需的客户端文件；官网/工具不随包分发）
# 注：公钥 backend/app/license_public.pem 随 backend/app 目录整体拷贝
CONTENT = {
    'backend/run.py': 'backend/run.py',
    'backend/requirements.txt': 'backend/requirements.txt',
    'backend/app': 'backend/app',
    'backend/integrity_manifest.json': 'backend/integrity_manifest.json',
    'frontend/dist': 'frontend/dist',
    'start.bat': 'start.bat',
    'start.sh': 'start.sh',
    'README.md': 'README.md',
    'LICENSE': 'LICENSE',
    'THIRD-PARTY-NOTICES.txt': 'THIRD-PARTY-NOTICES.txt',
}

EXCLUDE_DIRS = {'__pycache__', '.deps', 'venv', 'node_modules', 'data', '.npm-cache'}
EXCLUDE_FILES = {'opspanel.db', 'binding.json', 'config.json', 'secret.key',
                 'license.json', '.pyc'}


def _copytree(src: str, dst: str):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
        for f in files:
            if any(f.endswith(x) or f in EXCLUDE_FILES for x in ['.pyc', '.db', '.log']):
                continue
            if f in EXCLUDE_FILES:
                continue
            rel = os.path.relpath(root, src)
            outdir = os.path.join(dst, rel)
            os.makedirs(outdir, exist_ok=True)
            shutil.copy2(os.path.join(root, f), os.path.join(outdir, f))


def stage_panel(stage_dir: str):
    panel_dir = os.path.join(stage_dir, 'panel')
    for src_rel, dst_rel in CONTENT.items():
        src = os.path.join(BASE, src_rel)
        dst = os.path.join(panel_dir, dst_rel)
        if not os.path.exists(src):
            print(f'[!] 跳过缺失路径: {src_rel}')
            continue
        if os.path.isdir(src):
            _copytree(src, dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
    return panel_dir


def build_linux(panel_dir: str):
    """tar.gz：install.sh 与 panel/ 平级。"""
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f'rt-panel-{VERSION}.tar.gz')
    install_src = os.path.join(RELEASE, 'linux', 'rt-panel-2.0.0-rc3', 'install_panel.sh')
    with tarfile.open(out, 'w:gz') as tf:
        tf.add(install_src, arcname='install_panel.sh')
        for root, dirs, files in os.walk(panel_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                fp = os.path.join(root, f)
                tf.add(fp, arcname=os.path.relpath(fp, os.path.dirname(panel_dir)))
    size = os.path.getsize(out) / 1024 / 1024
    print(f'[OK] Linux 安装包: {out} ({size:.1f} MB)')
    return out


def build_site_tarball():
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f'rt-site-{VERSION}.tar.gz')
    install_src = os.path.join(RELEASE, 'site', 'rt-site-1.0.0', 'install.sh')
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
    with tarfile.open(out, 'w:gz') as tf:
        tf.add(install_src, arcname='install.sh')
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f.endswith('.pyc') or f in EXCLUDE_FILES:
                    continue
                fp = os.path.join(root, f)
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
        # 随包附带合规文件
        for f in ('LICENSE', 'THIRD-PARTY-NOTICES.txt'):
            fp = os.path.join(BASE, f)
            if os.path.isfile(fp):
                tf.add(fp, arcname=f)
    size = os.path.getsize(out) / 1024 / 1024
    print(f'[OK] 官网部署包: {out} ({size:.1f} MB)')
    return out


def build_windows(panel_dir: str):
    """C# 自解压安装器：stub.exe + 尾部载荷 → installer.exe。

    双击 → UAC 提权 → 解压到临时目录 → 启动黑金主题 HTA 安装向导。
    （不再依赖 iexpress，兼容性更强）
    """
    import struct
    import tempfile

    os.makedirs(DIST, exist_ok=True)
    stage = os.path.join(RELEASE, 'win', 'stage')
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)
    panel_dst = os.path.join(stage, 'panel')
    shutil.copytree(panel_dir, panel_dst)
    for f in ('setup.hta', 'install-core.ps1', 'setup.cmd', 'rt.cmd',
              'logo.png', 'preview.png', 'panel.ico'):
        src = os.path.join(RELEASE, 'win', f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(stage, f))
        else:
            print(f'[!] 缺少安装向导随包文件: {f}')

    # ---------- 1. 构建自定义载荷格式 ----------
    # [marker 9B][count 4B][nameLen 4B][name][dataLen 8B][data]...
    entries = []
    for root, dirs, files in os.walk(stage):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, stage).replace('\\', '/')
            with open(fp, 'rb') as fh:
                entries.append((rel, fh.read()))
    payload = b'RTPAYLOAD1' + struct.pack('<I', len(entries))
    for rel, data in entries:
        name_b = rel.encode('utf-8')
        payload += struct.pack('<I', len(name_b)) + name_b
        payload += struct.pack('<Q', len(data)) + data

    # ---------- 2. 编译 C# 存根 ----------
    csc = None
    for cand in (r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe',
                 r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe'):
        if os.path.isfile(cand):
            csc = cand
            break
    if not csc:
        print('[!] 未找到 csc.exe，无法构建 installer.exe')
        sys.exit(1)
    stub_src = os.path.join(RELEASE, 'win', 'stub.cs')
    manifest = os.path.join(RELEASE, 'win', 'app.manifest')
    stub_out = os.path.join(stage, '..', 'stub_tmp.exe')
    stub_out = os.path.normpath(os.path.join(RELEASE, 'win', 'stub_build.exe'))
    print('[*] 编译安装器存根（csc）...')
    # 显式引用 WinForms：存根出错时要弹窗提示，不能像以前那样静默失败
    # /win32icon：资源管理器里显示 RT 品牌图标（找不到图标文件也不影响编译）
    icon = os.path.join(RELEASE, 'win', 'panel.ico')
    args = [csc, '/nologo', '/target:winexe', '/optimize+',
            '/r:System.Windows.Forms.dll',
            f'/win32manifest:{manifest}', f'/out:{stub_out}', stub_src]
    if os.path.isfile(icon):
        args.insert(-1, f'/win32icon:{icon}')
    r = subprocess.run(args, capture_output=True, timeout=120)
    if r.returncode != 0:
        print('[!] csc 编译失败:', r.stdout.decode('gbk', 'ignore')[-500:])
        sys.exit(1)

    # ---------- 3. 拼接 stub + 载荷 → installer.exe ----------
    out_path = os.path.join(DIST, f'rt-panel-setup-{VERSION}.exe')
    with open(stub_out, 'rb') as f:
        stub_bytes = f.read()
    with open(out_path, 'wb') as f:
        f.write(stub_bytes)
        f.write(payload)
    os.remove(stub_out)
    size = os.path.getsize(out_path) / 1024 / 1024
    print(f'[OK] Windows 安装程序: {out_path} ({size:.1f} MB)')
    return out_path


def deploy_site_files():
# [官网相关路径已脱敏：官网不开源，内部结构不公开]

    官网部署后即可直接访问：
      https://www.rt888.icu/install_panel.sh        Linux 一键安装入口
      https://www.rt888.icu/rt-panel-2.0.0-rc3.tar.gz   安装脚本自动下载的包
      https://www.rt888.icu/rt-panel-setup-1.0.0.exe Windows 安装程序（下载页）
      https://www.rt888.icu/update/latest.json      面板一键更新（build_update_pkg.py 生成）
    """
# [官网相关路径已脱敏：官网不开源，内部结构不公开]
    os.makedirs(site_dist, exist_ok=True)
    install_src = os.path.join(RELEASE, 'linux', 'rt-panel-2.0.0-rc3', 'install_panel.sh')
    copies = [
        (install_src, os.path.join(site_dist, 'install_panel.sh')),
        (os.path.join(DIST, f'rt-panel-{VERSION}.tar.gz'),
         os.path.join(site_dist, f'rt-panel-{VERSION}.tar.gz')),
        (os.path.join(DIST, f'rt-panel-setup-{VERSION}.exe'),
         os.path.join(site_dist, f'rt-panel-setup-{VERSION}.exe')),
    ]
    for src, dst in copies:
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            print(f'[OK] 官网分发: site/dist/{os.path.basename(dst)}')
        else:
            print(f'[!] 缺少分发文件: {src}')


def main():
    print('=' * 56)
    print('  云枢面板 发布打包工具')
    print('=' * 56)
    stage = os.path.join(RELEASE, 'staging')
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    print('[*] 收集发布文件...')
    panel_dir = stage_panel(stage)
    n = sum(len(fs) for _, _, fs in os.walk(panel_dir))
    print(f'[OK] 共 {n} 个文件')
    if not os.path.isfile(os.path.join(panel_dir, 'backend', 'integrity_manifest.json')):
        print('[!] 警告: 未找到完整性清单，请先运行 python tools/build_manifest.py')
    linux = build_linux(panel_dir)
    win = build_windows(panel_dir)
    # 安装包分发文件配置到官网根目录（含官网部署包内）
    deploy_site_files()
    site = build_site_tarball()
    print('=' * 56)
    print(f'  Linux 面板 : {os.path.basename(linux)}')
    print(f'  官网部署包 : {os.path.basename(site)}')
    print(f'  Win 安装包 : {os.path.basename(win)}')
    print('=' * 56)


if __name__ == '__main__':
    main()
