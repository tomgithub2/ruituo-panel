# Created by 小杜 on 2026/08
# 云枢面板 Windows 安装核心逻辑（由 setup.hta 图形向导调用，也可静默运行）
#
# 约定：凡是要中止的失败分支，都必须先打 ##RT-FAIL## 哨兵再 exit。
# 原因：图形向导靠 ASCII 哨兵判断成败 —— 日志里的中文在不同读取编码下会匹配不上，
#       之前向导因此永远停在进度条上，看不到任何失败提示。
param(
    [string]$InstallDir = "$env:ProgramFiles\RTPanel",
    [string]$LogFile = "$env:TEMP\rt-install.log",
    [string]$AccountServer = "https://www.rt888.icu",
    [int]$Port = 8000
)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 日志固定 UTF-16LE：向导用 FSO(TristateTrue) 读，两边编码必须对齐，否则中文全是乱码
Set-Content -Path $LogFile -Value '' -Encoding Unicode

$encNoBom = New-Object System.Text.UTF8Encoding($false)   # 配置/启动器都要求不带 BOM
$encAscii = New-Object System.Text.ASCIIEncoding

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line -Encoding Unicode
}
function Step($tag, $msg) {
    Log $msg
    Log "[STEP]$tag"
}
function Warn($msg) {
    Log "警告: $msg"
    Log '##RT-WARN##'
}
function Fail($msg) {
    Log "错误: $msg"
    Log '##RT-FAIL##'
    exit 1
}

# Python 检测：必须实跑一次拿版本号才算数（只判断"命令存在"会把商店占位壳也算通过）。
# 注意：不能按路径里有没有 WindowsApps 一刀切跳过 —— 微软商店版 Python 就装在那里，
# 但它自带 pip、完全可用（实测 3.13 + pip 26），跳过它等于人为判定"没有 Python"。
function Test-Python($exe) {
    if (-not $exe) { return $null }
    try {
        $out = & $exe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0) { return $null }
    $v = ("$out").Trim()
    if ($v -notmatch '^\d+\.\d+$') { return $null }
    return $v
}

# 取可直接执行的解释器路径：商店版 python 是"应用执行别名"（0 字节跳转），
# sys.executable 指向的 Program Files\WindowsApps 真实路径普通权限会被拒（实测 Access denied），
# 所以要先真跑一次确认，跑不通就保留能用的别名路径。
function Resolve-PythonReal($exe) {
    try {
        $real = (& $exe -c "import sys;print(sys.executable)" 2>$null | Select-Object -First 1)
        $real = ("$real").Trim()
        if ($real -and (Test-Path $real) -and ($real -ne $exe)) {
            & $real -c "import sys" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $real }
        }
    } catch { }
    return $exe
}

# 端口校验：无效则回退默认 8000（必须放在 Log 定义之后，否则日志函数还不存在）
if ($Port -lt 1 -or $Port -gt 65535) {
    Log "端口 $Port 无效，使用默认端口 8000"
    $Port = 8000
}

# ---------- 1. 管理员权限 ----------
Log '检查管理员权限…'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Fail '需要管理员权限，请右键安装程序选择"以管理员身份运行"'
}
Step 'admin-ok' '管理员权限 OK'

# ---------- 2. 复制文件 ----------
Log "复制面板文件到 $InstallDir …"
try {
    $src = Join-Path $PSScriptRoot 'panel'
    if (-not (Test-Path $src)) { throw "未找到 panel 目录（$src）" }
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Copy-Item -Path (Join-Path $src '*') -Destination $InstallDir -Recurse -Force
} catch {
    Fail "文件复制失败: $($_.Exception.Message)"
}
$backendDir = Join-Path $InstallDir 'backend'
$dataDir = Join-Path $backendDir 'data'
Step 'copy-done' '文件复制完成'

# ---------- 3. 安装系统运行环境（VC++ 运行库） ----------
Log '安装系统运行环境（VC++ Redistributable）…'
try {
    $vcredist = "$env:TEMP\vc_redist.x64.exe"
    # 已安装则跳过
    $vcInstalled = $false
    $vcKey = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
    if (Test-Path $vcKey) {
        $v = Get-ItemProperty $vcKey -ErrorAction SilentlyContinue
        if ($v -and $v.Installed -eq 1) { $vcInstalled = $true }
    }
    if (-not $vcInstalled) {
        Log '下载 VC++ 2015-2022 运行库（约 25MB）…'
        Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile $vcredist -UseBasicParsing
        Log '静默安装 VC++ 运行库…'
        Start-Process -FilePath $vcredist -ArgumentList '/install','/quiet','/norestart' -Wait
        Remove-Item $vcredist -Force -ErrorAction SilentlyContinue
        Log 'VC++ 运行库安装完成'
    } else {
        Log 'VC++ 运行库已存在，跳过'
    }
} catch {
    Log "警告: VC++ 运行库安装失败（$($_.Exception.Message)），不影响面板运行"
}

# ---------- 4. 检测/安装 Python ----------
Log '检测 Python 环境…'
$pyCmd = $null
$pyVer = ''
foreach ($cand in @('py', 'python', 'python3')) {
    $c = Get-Command $cand -ErrorAction SilentlyContinue
    if (-not $c -or -not $c.Source) { continue }
    $v = Test-Python $c.Source
    if ($v) { $pyCmd = $c.Source; $pyVer = $v; break }
}
if (-not $pyCmd) {
    Log '未检测到可用的 Python，尝试 winget 安装 Python 3.13（约 2-5 分钟）…'
    $w = Get-Command winget -ErrorAction SilentlyContinue
    if ($w) {
        & winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
        # winget 刚装完，当前进程的 PATH 还是旧的，从注册表重新拼一次
        try {
            $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
        } catch { }
        foreach ($cand in @('py', 'python')) {
            $c = Get-Command $cand -ErrorAction SilentlyContinue
            if (-not $c -or -not $c.Source) { continue }
            $v = Test-Python $c.Source
            if ($v) { $pyCmd = $c.Source; $pyVer = $v; break }
        }
        # 再兜底扫常见安装位置（PATH 没刷新时最后的办法）
        if (-not $pyCmd) {
            $globs = @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                       "$env:ProgramFiles\Python3*\python.exe",
                       "$env:SystemDrive\Python3*\python.exe")
            foreach ($g in $globs) {
                $hits = Get-ChildItem $g -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
                foreach ($h in $hits) {
                    $v = Test-Python $h.FullName
                    if ($v) { $pyCmd = $h.FullName; $pyVer = $v; break }
                }
                if ($pyCmd) { break }
            }
        }
    }
    if (-not $pyCmd) {
        Fail '未检测到 Python 且自动安装失败：请手动安装 Python 3.8+（安装时勾选 Add Python to PATH）后重新运行安装程序'
    }
    Step 'py-installed' "Python $pyVer 安装完成: $pyCmd"
} else {
    Step 'py-ok' "Python 已就绪: $pyCmd ($pyVer)"
}
if ($pyVer -match '^(\d+)\.(\d+)$') {
    if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 8)) {
        Warn "Python 版本偏低（$pyVer），面板要求 3.8+，建议升级后再使用"
    }
}

# 解析真实解释器路径（商店版别名在 SYSTEM 计划任务里可能解析不了），并确认 pip 可用
$pyReal = Resolve-PythonReal $pyCmd
if ($pyReal -and $pyReal -ne $pyCmd) {
    Log "已解析真实解释器路径: $pyReal"
    $pyCmd = $pyReal
}
& $pyCmd -m pip --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Log '未检测到 pip，尝试自举（ensurepip）…'
    & $pyCmd -m ensurepip --upgrade 2>&1 | Out-Null
    & $pyCmd -m pip --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail 'Python 缺少 pip：请安装官方版 Python（https://www.python.org/downloads/，勾选 Add Python to PATH）后重试'
    }
}

# ---------- 5. 安装面板依赖 ----------
Log '检查面板依赖…'
$depsDir = Join-Path $backendDir '.deps'
$depsOk = $false
if (Test-Path (Join-Path $depsDir 'fastapi')) {
    & $pyCmd -c "import sys;sys.path.insert(0,r'$depsDir');import fastapi,uvicorn" 2>$null
    if ($LASTEXITCODE -eq 0) { $depsOk = $true } else { Log '警告: 已有依赖不完整，重新安装' }
}
if (-not $depsOk) {
    Log '安装面板依赖（首次约 1-2 分钟，走清华镜像）…'
    Push-Location $backendDir
    & $pyCmd -m pip install -r requirements.txt --target .deps --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
    if ($LASTEXITCODE -ne 0) {
        Log '镜像源安装失败，改用官方源重试…'
        & $pyCmd -m pip install -r requirements.txt --target .deps --disable-pip-version-check --quiet
    }
    Pop-Location
    if (Test-Path (Join-Path $depsDir 'fastapi')) {
        # 装了不代表能用（镜像给错架构轮子时目录也在），必须真的 import 一次
        & $pyCmd -c "import sys;sys.path.insert(0,r'$depsDir');import fastapi,uvicorn" 2>$null
        if ($LASTEXITCODE -eq 0) { $depsOk = $true }
    }
    if (-not $depsOk) {
        Fail '依赖安装失败：请检查网络或代理后重新运行安装程序'
    }
}
Step 'deps-done' '依赖安装完成'

# ---------- 6. 写入配置 ----------
Log "写入面板配置（端口 $Port）…"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$cfg = [ordered]@{
    port = $Port
    bind_host = '0.0.0.0'
    site_name = '云枢面板'
    account_server = $AccountServer
    theme = 'blackgold'
} | ConvertTo-Json
# 不写 BOM：Python 侧按 utf-8 读，带 BOM 会让配置被整体忽略（回落到默认值）
# 注意：PS 5.1 解析器不接受把 (Join-Path …) 直接当 .NET 方法实参，路径必须先落变量
$cfgPath = Join-Path $dataDir 'config.json'
[System.IO.File]::WriteAllText($cfgPath, $cfg, $encNoBom)

# 生成网页初始化令牌（安装完成后在浏览器完成管理员账号 + 官网账户配置）
$tokenBytes = New-Object byte[] 8
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($tokenBytes)
$setupToken = ($tokenBytes | ForEach-Object { $_.ToString('x2') }) -join ''
$tokenPath = Join-Path $dataDir 'setup_token.txt'
[System.IO.File]::WriteAllText($tokenPath, $setupToken, $encAscii)
Log "初始化令牌: $setupToken（仅用于首次网页初始化，用完即焚）"
Log "SETUP-TOKEN: $setupToken"

# ---------- 7. 启动器 ----------
Log '创建启动器…'
$launcher = Join-Path $InstallDir 'start-panel.cmd'
# 启动器整体保持 ASCII 且 CRLF、不带 BOM：cmd.exe 对 BOM 和多字节行都很敏感
$launcherText = (@(
    '@echo off',
    'chcp 65001 >nul',
    'title Yunshu Panel',
    'cd /d "' + $backendDir + '"',
    'set "PY=' + $pyCmd + '"',
    'if not exist "%PY%" set "PY=python"',
    '"%PY%" run.py >> "data\panel.log" 2>&1'
) -join "`r`n") + "`r`n"
[System.IO.File]::WriteAllText($launcher, $launcherText, $encNoBom)

# rt 命令行管理工具
$rtSrc = Join-Path $PSScriptRoot 'rt.cmd'
if (Test-Path $rtSrc) {
    Copy-Item -Path $rtSrc -Destination (Join-Path $InstallDir 'rt.cmd') -Force
    Log 'rt 命令行工具已部署（rt.cmd）'
    # 自动加入系统 PATH，使 rt 命令全局可用
    try {
        $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        if ($machinePath -notlike "*$InstallDir*") {
            [Environment]::SetEnvironmentVariable('Path', "$machinePath;$InstallDir", 'Machine')
            Log "rt 命令已加入系统 PATH（$InstallDir，新开终端即可使用 rt）"
        } else {
            Log 'rt 命令已在系统 PATH 中'
        }
    } catch {
        Log "警告: 写入系统 PATH 失败（$($_.Exception.Message)），可手动添加 $InstallDir"
    }
}

# ---------- 8. 开机自启 ----------
Log '注册开机自启（计划任务）…'
$taskName = 'RTPanel'
& schtasks /create /tn $taskName /tr "`"$launcher`"" /sc onstart /ru SYSTEM /rl highest /f 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Step 'autostart-done' '开机自启注册成功'
} else {
    Log '警告: 开机自启注册失败（不影响使用，可在任务计划程序中手动创建）'
}

# ---------- 9. 快捷方式 ----------
Log '创建桌面/开始菜单快捷方式…'
# 品牌图标随包附带：先装到安装目录，快捷方式引用它（.cmd 本身带不了图标）
$iconSrc = Join-Path $PSScriptRoot 'panel.ico'
$iconDst = Join-Path $InstallDir 'panel.ico'
if (Test-Path $iconSrc) {
    try {
        Copy-Item -Path $iconSrc -Destination $iconDst -Force
        Log '品牌图标已部署（panel.ico）'
    } catch {
        Log "警告: 图标复制失败（$($_.Exception.Message)）"
    }
}
try {
    $ws = New-Object -ComObject WScript.Shell
    $desktop = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\云枢面板.lnk')
    $desktop.TargetPath = $launcher
    $desktop.WorkingDirectory = $InstallDir
    $desktop.Description = '云枢面板 - 高端服务器运维面板'
    if (Test-Path $iconDst) { $desktop.IconLocation = "$iconDst,0" }
    $desktop.Save()

    $smDir = [Environment]::GetFolderPath('StartMenu') + '\Programs\云枢面板'
    New-Item -ItemType Directory -Force -Path $smDir | Out-Null
    $sm = $ws.CreateShortcut("$smDir\云枢面板.lnk")
    $sm.TargetPath = $launcher
    $sm.WorkingDirectory = $InstallDir
    if (Test-Path $iconDst) { $sm.IconLocation = "$iconDst,0" }
    $sm.Save()
    Step 'shortcut-done' '快捷方式创建完成'
} catch {
    Log "警告: 快捷方式创建失败（$($_.Exception.Message)）"
}

# ---------- 10. 启动面板并确认端口真的起来了 ----------
Log '启动面板服务…'
& schtasks /run /tn $taskName 2>&1 | Out-Null
$url = "http://127.0.0.1:$Port"
$up = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $up = $true; break }
    } catch { }
}
if ($up) {
    Log "面板已启动: $url"
} else {
    Warn "面板端口 $Port 暂未响应：可以稍等 10 秒再访问 $url；若一直打不开，请查看 $backendDir\data\panel.log"
}
Log "安装流程全部完成。访问 $url 输入初始化令牌 $setupToken 完成网页初始化"
Log '##RT-DONE##'
exit 0
