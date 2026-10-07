<div align="center">

# 🛡️ 锐同面板（Ruitong Panel）

**跨平台服务器运维面板 · 开源版**　|　**Cross-platform Server Operations Panel · Open Source Edition**

![License](https://img.shields.io/badge/License-AGPL%20v3-blue)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-blue)
![AI](https://img.shields.io/badge/AI-44%20Tools-brightgreen)
![Version](https://img.shields.io/badge/Version-1.0--beta-orange)

**原作者（Original Author）**：小杜（XiaoDu）　·　**官网（Website）**：https://www.rt888.icu

</div>

---

## 📖 简介 Introduction

锐同面板是一款**完全自研**的跨平台服务器运维面板，功能覆盖服务器运维全场景，支持 Windows 与 Linux 双平台，提供白金 / 亮色专业 / 银黑三大主题（默认白金）。

Ruitong Panel is a **fully self-developed** cross-platform server operations panel with features that match and exceed similar products. It supports Windows and Linux with three built-in themes (Platinum default / Light-Pro / Silver-Black).

## ✨ 核心特性 Features

- **一键建站 One-click Site Creation** — 自动创建同名数据库与 FTP / auto-creates database & FTP with the same name
- **SSL 证书 SSL Certificates** — 从已有网站一键签发、续期、自动部署 / one-click issuance, renewal & auto-deploy from existing sites
- **WAF 防火墙 WAF Firewall** — 预设防护库与实时仪表盘 / preset protection library & live dashboard
- **AI 智能助手 AI Assistant** — 44 个工具，兼容任意 OpenAI API，一句话目标→AI计划→一键执行→自动总结 / 44 tools, any OpenAI-compatible API
- **安全 Security** — 登录锁定、两步验证、安全中心、木马扫描 / login lockout, 2FA, security center, malware scan
- **服务管理 Service Management** — SSH / FTP / DNS / Swap / 软件商店（17 款软件）/ software store (17 apps)
- **计划任务 Scheduled Tasks** — Shell / URL / @once 一次性任务 / one-shot tasks
- **rt 命令行 rt CLI** — Linux + Windows 双平台命令行管理，安装时自动配置 PATH / CLI management with auto PATH setup
- **全部功能免费，WAF 高级防护为 VIP 专属** — All features free; WAF advanced protection is VIP-exclusive

## 📁 目录结构 Structure

```
backend/   面板后端业务源码（安全模块已移除） Panel backend source (security modules removed)
frontend/  面板前端页面源码（安全页面已移除） Panel frontend pages (security pages removed)
tools/     6 个构建工具                       6 build tools
release/   Linux / Windows 安装器源码        Installer source
LICENSE · NOTICE · AUTHORS · OPEN-SOURCE-NOTICE.txt · THIRD-PARTY-NOTICES.txt
```

## 📜 许可与署名 License & Attribution

本仓库全部代码采用 **GNU Affero 通用公共许可证 v3.0（AGPL-3.0）** 授权，协议全文见 [LICENSE](LICENSE)。

All code in this repository is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. Full text: [LICENSE](LICENSE).

| 行为 Action | 是否允许 Allowed | 依据 Basis |
| --- | --- | --- |
| 使用 / 学习 / 修改 Use, learn, modify | ✅ 自由 freely | AGPL §0–§2 |
| 分发原版或修改版 Distribute original or modified | ✅ 但**必须以 AGPL-3.0 开源全部对应源码** must release all corresponding source under AGPL-3.0 | AGPL §5 |
| **部署为网络服务（SaaS / 托管 / 改版上线）Run as a network service** | ✅ 但**必须向使用者提供完整对应源码** must offer the complete corresponding source to users | **AGPL §13** |
| 商业使用 Commercial use | ✅ 允许（AGPL 不限制用途）allowed, no field-of-use restriction | AGPL |
| 保留版权与许可声明 Keep copyright & license notices | ⚠️ **必须** required | AGPL §4–§5 |
| 移除 / 隐藏作者署名 Remove or hide attribution | ❌ 禁止 prohibited | AGPL §4–§5 |
| 闭源二次分发（专有化）Closed-source redistribution | ❌ 禁止 prohibited | AGPL §5 |

> **AGPL §13 是本许可最关键的一条**：只要你把本软件（或其修改版）**部署成网络服务**给别人用，就必须向这些使用者提供**对应的完整源码**。
> **The §13 network clause**: if you run this software (or a modified version) as a network service, you must offer the complete corresponding source to its users.

原作者署名 / Original author：**小杜（XiaoDu, https://www.rt888.icu）** —— 任何分发都必须保留版权与许可声明，详见 [AUTHORS](AUTHORS) 与 [NOTICE](NOTICE)。

> 历史说明：本仓库早期发行版曾以 AGPL-3.0 发布；**自本次更新起，仓库代码统一改为 AGPL-3.0**，旧的 CC 声明仅对历史发行版有效。AGPL-3.0 是 OSI 认可的自由软件许可，**不再有"禁止商用 / 禁止演绎"的限制**，改为"用了就必须开源"。
> Historical note: early releases used AGPL-3.0; from this update on the repository is licensed under **AGPL-3.0**. The old CC notice applies only to historical releases.

## 🔒 开源范围 Scope

**开源（Open-sourced）**：面板端业务代码（backend 除安全模块 / frontend 除安全页面）、构建工具、安装器源码、许可与署名文件。

**不开源（NOT open-sourced）**：
1. 官网系统（website/，源码与内部结构不公开） Official website system (source & internal structure not disclosed)
2. 安全相关模块（防攻击者利用） Security modules (to prevent abuse)
3. 厂商内部文件（私钥、运行数据、内部脚本） Vendor internal files (keys, runtime data, internal scripts)

详见 [OPEN-SOURCE-NOTICE.txt](OPEN-SOURCE-NOTICE.txt)。

## ⚠️ 重要说明 Important

- 本仓库**不含入口文件与安全模块，不可直接运行**，仅供代码审阅与学习。
  This repository has **no entry files or security modules and is NOT directly runnable**; it is provided for code review and learning.
- 借鉴、参考、移植前请先联系原作者取得书面同意。
  Contact the original author for prior written consent before borrowing, referencing or porting any code.
- 完整可运行版请到官网 https://www.rt888.icu 获取。
  The complete runnable version is available at the official website.

## 📦 发行版 Release

**v1.0-beta** — 首个公开测试版（安装包见本仓库 Releases 页签 / installers in the Releases tab）：

| 平台 Platform | 安装包 Installer |
| --- | --- |
| Linux | `rt-panel-1.0-beta.tar.gz`（解压运行 `install_panel.sh`）|
| Windows | `rt-panel-setup-1.0-beta.exe`（双击安装，终端输入 `rt` 管理）|

## 📅 更新日志 Changelog

**v1.0-beta**（2026-08-15）
- 首个公开测试版发布 First public beta release
- 一键建站 / SSL / WAF / AI 助手（44 工具）/ 三大主题 / rt CLI / Windows + Linux 双平台

## 📮 联系 Contact

| 方式 Method | 地址 Address |
| --- | --- |
| QQ | 3557529776 |
| 邮箱 Email | xd8881313113@163.com |
| 官网 Website | https://www.rt888.icu |

## ⚖️ 免责声明 Disclaimer

本软件按「现状」提供，作者不承担任何明示或默示的保证责任，使用本软件产生的任何后果由使用者自行承担。

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. USE AT YOUR OWN RISK.

---

<div align="center">© 2026 小杜（锐同面板官方） · https://www.rt888.icu</div>
