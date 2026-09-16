# Oracle Free Tier 实例抢占脚本 — 说明与使用指南

> 项目目录：`/workspace/oracle-freetier-instance-creation`
> 上游仓库：https://github.com/mohankumarpaluru/oracle-freetier-instance-creation （本地克隆，`main.py` 已内置 Telegram 通知增强）

---

## 目录

1. [项目概述](#1-项目概述)
2. [运行环境](#2-运行环境)
3. [快速开始](#3-快速开始)
4. [凭证准备（三组）](#4-凭证准备三组)
5. [通知配置](#5-通知配置)
6. [执行流程与重试机制](#6-执行流程与重试机制)
7. [运行与运维](#7-运行与运维)
8. [日志解读](#8-日志解读)
9. [安全注意事项](#9-安全注意事项)
10. [已知限制](#10-已知限制)

---

## 1. 项目概述

**用途**：自动化创建 Oracle Cloud（OCI）免费层计算实例，规避人工反复点击控制台的操作。针对「免费层 ARM 实例资源紧张、经常报 Out of host capacity」的场景，脚本每 60 秒（可配置）调用一次 `launch_instance` API **自动重试，直到成功创建**。

**支持规格**：

| 规格 | OCPU | 内存 | 说明 |
|---|---|---|---|
| `VM.Standard.A1.Flex`（ARM） | 2 | 12 GB | 默认目标，免费层主力 |
| `VM.Standard.E2.1.Micro`（AMD） | 1 | 1 GB | 免费层第二规格 |

**核心价值**：无人值守抢注免费 ARM 实例；创建成功后自动写 `INSTANCE_CREATED` 文件，并按配置发送 Gmail / Discord / Telegram 通知。

> ⚠️ 注意：本脚本不自动分配公网 IP，创建成功后需在控制台手动为实例分配临时公网 IP（详见 [7.4](#74-抢到实例后的收尾必须人工)）。

---

## 2. 运行环境

| 项 | 要求 |
|---|---|
| 宿主机 OS | Debian / Ubuntu（或其他可运行 Python 3 的系统）|
| Python | 3.8+（本项目使用 venv，Python 3.12 验证通过）|
| 依赖 | `oci`、`paramiko`、`python-dotenv`、`requests`（见 requirements.txt）|
| 网络 | 需能访问 OCI API 与 Telegram/Discord API |

**两种运行场景**：

| 场景 | 要求 |
|---|---|
| 在 OCI Micro 实例（`VM.Standard.E2.1.Micro`）上运行 | `OCI_SUBNET_ID` 可留空，脚本自动探测子网 |
| **本地 / 其他服务器运行** | **`OCI_SUBNET_ID` 必填**，否则可能选到意外子网 |

---

## 3. 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/mohankumarpaluru/oracle-freetier-instance-creation.git
cd oracle-freetier-instance-creation

# 2. 安装依赖
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. 准备三组凭证（见第 4 章）：oci_config、oci_api_private_key.pem、oci.env
# 4. 启动（见第 7 章）
```

---

## 4. 凭证准备（三组）

启动前必须准备三组内容，缺一不可。其中第 1、2 组来自 **Oracle Cloud 控制台同一处操作**（API 密钥），第 3 组是运行参数。

### 4.1 ① OCI API 凭证（`oci_config`）

**获取位置**：Oracle Cloud 控制台 → 右上角头像 → **My Profile（用户设置/我的个人资料）** → **API Keys（API 密钥）** → **Add API Key（添加 API 密钥）** → **Generate API Key Pair（生成密钥对）**。

生成后会弹出 **Configuration Preview（配置预览）**，内容即此文件的 5 个字段：

```ini
[DEFAULT]
user=ocid1.user.oc1..<你的 user OCID>
fingerprint=2e:c0:... (60 位十六进制，冒号分隔)
tenancy=ocid1.tenancy.oc1..<你的 tenancy OCID>
region=ap-tokyo-1          # 你的 home region
key_file=/workspace/oracle-freetier-instance-creation/oci_api_private_key.pem
```

| 字段 | 说明 | 获取位置 |
|---|---|---|
| `user` | 用户 OCID | 配置文件预览 |
| `fingerprint` | 公钥指纹 | 配置文件预览 |
| `tenancy` | 租户 OCID | 配置文件预览 |
| `region` | 区域，如 `ap-tokyo-1` | 配置文件预览 |
| `key_file` | 私钥文件绝对路径 | 指向第 4.2 节的私钥文件 |

> ⚠️ **配置预览只显示一次**，生成后务必当场复制保存，关闭后不会完整显示。
> 注意：此文件**不能有空格**，格式与 `sample_oci_config` 完全一致，含 `[DEFAULT]` 段。

### 4.2 ② OCI API 私钥（`oci_api_private_key.pem`）

**获取位置**：与 4.1 同一次操作，点击「Generate API Key Pair」后**下载的私钥文件**（内容以 `-----BEGIN PRIVATE KEY-----` 开头）。

- 文件名可自定义，但 `oci_config` 中 `key_file` 必须指向其绝对路径；
- 当前用户需对该文件有读权限（建议 `chmod 600`）。

### 4.3 ③ 运行参数（`oci.env`）

`oci.env` 为项目根目录下的环境变量文件（参考仓库中的 `oci.env` 模板），核心字段：

```ini
OCI_CONFIG=/绝对路径/oci_config            # 必填
OCT_FREE_AD=AP-TOKYO-1-AD-1                # 必填：免费可用域，多个用逗号分隔
DISPLAY_NAME=my-arm-instance                # 实例名
OCI_COMPUTE_SHAPE=VM.Standard.A1.Flex      # 或 VM.Standard.E2.1.Micro
SECOND_MICRO_INSTANCE=False                 # 仅创建第二个 AMD Micro 时设 True
REQUEST_WAIT_TIME_SECS=60                   # 重试间隔（秒），<30 有被限流风险
SSH_AUTHORIZED_KEYS_FILE=/绝对路径/id_rsa.pub   # 不存在则自动生成密钥对
OCI_SUBNET_ID=ocid1.subnet.oc1...           # 本地运行必填
OCI_IMAGE_ID=                               # 留空按系统+版本自动匹配镜像
OPERATING_SYSTEM="Canonical Ubuntu"
OS_VERSION=22.04
ASSIGN_PUBLIC_IP=false                      # 创建后需手动配公网 IP
BOOT_VOLUME_SIZE=50                         # 引导卷大小，最小 50GB
```

| 关键字段 | 获取位置 / 说明 |
|---|---|
| `OCT_FREE_AD` | 实例创建页面选择可用域时标注 **Always Free 的可用域**（如 `AP-TOKYO-1-AD-1`）；多个以逗号分隔，脚本轮换重试 |
| `OCI_SUBNET_ID` | 控制台 → **Networking（网络）→ Virtual Cloud Networks（VCN）→ 选中 VCN → Subnets（子网）→ 子网详情** 中的 OCID。⚠️ 必须是 `ocid1.subnet.oc1...` 开头的**子网** OCID，`ocid1.vcn.oc1...` 是 VCN 不是子网 |
| `OPERATING_SYSTEM` / `OS_VERSION` | 镜像匹配条件，填写 OCI 中镜像的准确名称/版本（如 `Canonical Ubuntu` / `22.04`）；首次运行会把可用镜像写入 `images_list.json` 便于查阅 |

---

## 5. 通知配置

### 5.1 通知方式总览（触发时机 + 消息内容）

| 触发时机 | Gmail（main.py） | Discord（main.py） | Telegram（main.py 增强版） | WeChat ClawBot（main.py 增强版） |
|---|---|---|---|---|
| **启动** | — | 🚀 Starting up | 🚀 OCI 抢实例脚本已启动（规格 XX）。抢到实例后会自动通知你 | 🚀 同 Telegram |
| **创建成功** | ✅ HTML 邮件《OCI INSTANCE CREATED》，含实例详情 | 🎉 Success | 🎉 **实例详情**：Instance ID / Display Name / Availability Domain / Shape / State | 🎉 同 Telegram（含实例详情） |
| **未处理错误** | ✅ 邮件含错误内容 | 😱 错误 | 😱 错误详情 | 😱 错误详情 |

> 上游原版：Telegram 仅在 `setup_init.sh`（shell 层）实现，成功时只发一句「脚本结束」提示；本项目本地增强版在 `main.py` 中原生支持 Telegram 与 WeChat ClawBot 并推送实例详情。

### 5.2 Gmail 通知

`oci.env` 配置：

```ini
NOTIFY_EMAIL=True
EMAIL=你的邮箱@gmail.com
EMAIL_PASSWORD=16位应用专用密码
```

- 仅支持 Gmail，发送方与接收方均为 `EMAIL`；
- **密码必须使用「应用专用密码」**（App Password）：Google 账号 → 安全 → 开启两步验证 → 应用专用密码 → 生成 16 位密码；若账号未开两步验证也可用原始密码；
- 成功时邮件正文为 HTML 模板（`email_content.html`），包含实例 ID、名称、可用域、规格、状态。

### 5.3 Discord 通知

`oci.env` 配置：

```ini
DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
```

**获取位置**：Discord 服务器 → **Server Settings（服务器设置）→ Integrations（集成）→ Webhooks → New Webhook**，复制 Webhook URL 填入。

### 5.4 Telegram 通知

`oci.env` 配置：

```ini
TELEGRAM_TOKEN=1234567890:AAH...
TELEGRAM_USER_ID=6163032455
```

**配置步骤**：

1. **创建 Bot 拿 Token**：Telegram 搜索 `@BotFather` → 发送 `/newbot` → 设置 bot 名称与用户名（必须以 `bot` 结尾）→ BotFather 返回 **Bot Token**；
2. **获取用户 ID**：Telegram 搜索 `@userinfobot` 或 `@myidbot`，发送任意消息，返回的数字即你的用户 ID；
3. **先与 Bot 建立会话**：搜索你的 bot 用户名，点 **Start** 或发一条消息——Telegram 规定 bot 不能主动给从未对话的用户发消息，**必须先对话一次**，否则推送会静默失败；
4. 填写 `oci.env` 后启动脚本，启动时收到的 🚀 消息即链路自检。

### 5.5 WeChat ClawBot 通知（iLink 协议）

> 腾讯官方开放的微信个人 Bot API（iLink，`ilinkai.weixin.qq.com`），由 `main.py` 原生实现（v1.2.0 起），与 Telegram 平行的第三个时机推送。

`oci.env` 配置：

```ini
# WeChat ClawBot Notification (optional, Tencent iLink protocol)
WECHAT_CLAWBOT_TOKEN=
WECHAT_CLAWBOT_BASEURL=          # 可选，默认 https://ilinkai.weixin.qq.com
WECHAT_TO_USER_ID=
WECHAT_CTX_TOKEN=
```

**前置条件（双端会话型协议，不是纯 webhook）**：

1. **登录 ClawBot 拿 `bot_token`**：扫码登录一次——用腾讯官方 `@tencent-weixin/openclaw-weixin`（openclaw 插件）或 SiverKing `weixin-ClawBot-API` Python 客户端均可；登录后 `bot_token`（与可选 `baseurl`）获得；
2. **用户先给 ClawBot 发一条微信消息**：bot 侧从该入站消息取得 `to_user_id`（`xxx@im.wechat`）与 `context_token`——**之后才能主动推送**；
3. 将 4 个值填入 `oci.env` 后启动脚本，启动时收到的 🚀 消息即链路自检。

> ⚠️ 注意事项：
> - `context_token` 与具体会话绑定，可能随会话失效——若通知某天停止，给 bot 再发一条消息并更新 `context_token`；
> - `bot_token` 失效（返回 `-14`）需重新扫码登录；本脚本只记录日志不自动重登；
> - 4 个键均在 `oci.env`（gitignore）；任一必填键为空则微信通知**静默禁用**，不影响主流程。

---

## 6. 执行流程与重试机制

### 6.1 主流程

```
启动
 ├─ 1. 读取 oci.env 与 oci_config
 ├─ 2. 初始化 OCI 客户端（Identity / VirtualNetwork / Compute）
 ├─ 3. get_user → 得到 tenancy
 ├─ 4. list_availability_domains → 匹配 OCT_FREE_AD 指定可用域
 ├─ 5. 子网：优先 OCI_SUBNET_ID，为空取第一个子网
 ├─ 6. 镜像：优先 OCI_IMAGE_ID，为空按 OS + 版本匹配最新镜像，输出 images_list.json
 ├─ 7. SSH 公钥：不存在则自动生成密钥对（RSA 2048）
 ├─ 8. 检查已有同规格实例（RUNNING/PROVISIONING）→ 存在则写 INSTANCE_CREATED 并结束
 └─ 9. 循环：launch_instance → 成功则确认状态并写 INSTANCE_CREATED；
        失败则按错误码分类（可重试 → 睡眠后重试；致命 → 写 UNHANDLED_ERROR.log 并退出）
```

### 6.2 重试机制

**可重试错误**（无限循环重试，间隔 `REQUEST_WAIT_TIME_SECS`）：

| 类型 | 内容 |
|---|---|
| code | `TooManyRequests`、`Out of host capacity.`、`InternalError`、`RequestException` |
| status | 502 / 503 / 504 |
| message 含 | `Out of host capacity.`、`Bad Gateway`、`Max retries exceeded`、`ProxyError` 等 |

**不可重试错误**：写 `UNHANDLED_ERROR.log`，触发已配置的通知后退出。

---

## 7. 运行与运维

> **Docker 方式为当前默认运行方式**（v1.1.0 起）；裸进程方式保留供调试用。

### 7.1 启动（Docker，推荐）

```bash
cd <项目目录>
docker compose up -d --build
docker logs -f oracle-freetier     # 看启动与轮询
```

- 镜像 `oracle-freetier:latest` 仅含依赖，代码/配置/密钥通过 bind mount 提供；
- 项目目录以**宿主绝对路径**挂载进容器同路径（宿主侧 `/usr/local/deploy/hermes/workspace-data/oracle-freetier-instance-creation`），`oci.env` 里的绝对路径配置无需改动；
- 日志（`launch_instance.log` / `setup_and_info.log`）与成功标志 `INSTANCE_CREATED` 直接落在宿主项目目录；
- 启动后应收到 Telegram/Discord 启动消息（若配置）；`launch_instance.log` 出现重试记录即正常。

### 7.2 状态查看

```bash
docker ps --filter name=oracle-freetier        # 容器状态
tail -f launch_instance.log     # 创建过程实时日志
tail -f setup_and_info.log      # 参数 / 资源解析日志
cat INSTANCE_CREATED 2>/dev/null  # 成功标志文件（出现即成功，内容含实例详情）
```

### 7.3 停止与重启（Docker）

```bash
docker compose stop     # 停止
docker compose up -d    # 重启（镜像已构建，秒级）
```

> ⚠️ 抢到实例后脚本会退出，但 `restart: unless-stopped` 会拉起重跑。收到成功通知后请及时 `docker compose stop`，避免无意义重试。

### 7.3.1 裸进程方式（调试用）

```bash
cd <项目目录>
.venv/bin/python main.py > python_run.log 2>&1 &
kill <PID>      # 停止
```

### 7.4 抢到实例后的收尾（必须人工）

1. OCI 控制台 → 计算 → 实例 → 给新实例 **分配临时公网 IP**（当前默认 `ASSIGN_PUBLIC_IP=false`）；
2. SSH 登录：`ssh -i id_rsa_private ubuntu@<公网IP>`（密钥对自动生成于项目目录）；
3. （可选）删除临时占用的 `VM.Standard.E2.1.Micro` 实例；
4. 保存 `INSTANCE_CREATED` 中的实例信息。

---

## 8. 日志解读

| 日志内容 | 含义 | 处理 |
|---|---|---|
| `Out of host capacity.` (500) | 目标可用域暂无容量 | **正常**，自动重试，无需干预，可能持续数小时~数天 |
| `TooManyRequests` (429) | 请求过频被限流 | 正常，睡眠后重试；频繁可调大 `REQUEST_WAIT_TIME_SECS` |
| `LimitExceeded` | 触达租户服务限额 | 检查控制台是否已有实例 / 引导卷额度是否占满 |
| `ERROR_IN_CONFIG.log` | oci_config 格式或内容错误 | 对照 `sample_oci_config` 修正后重启 |
| `UNHANDLED_ERROR.log` | 不可重试异常 | 按内容排查，必要时携日志上报上游 issue |

---

## 9. 安全注意事项

1. **凭证保护**：`oci_config`、`oci_api_private_key.pem` 建议 `chmod 600`；
2. **不进版本库**：本项目 `.gitignore` 已排除 `oci_config`、`oci_api_private_key.pem`、`oci.env`（含通知凭据）、SSH 私钥、日志等，**切勿强制提交或推送**至公开远端；
3. **Telegram 前置条件**：bot 必须先与目标用户建立会话，否则推送静默失败；
4. **本仓库为上游克隆**：本地 commit/tag 仅作存档用途，不要 push 到上游。

---

## 10. 已知限制

- **公网 IP 不自动分配**（上游 TODO）：`ASSIGN_PUBLIC_IP=true` 可在重试时附带临时 IP，但需评估配额；默认 false，创建后手动分配；
- **免费层配额**：AMD Micro 与 ARM 配额相互独立，已有 2 个 AMD Micro 不影响 ARM 创建；ARM 默认 2 OCPU/12GB（免费额度最多 4 OCPU/24GB）；
- **镜像选择**：首次运行生成 `images_list.json`，可从中挑选后改用 `OCI_IMAGE_ID` 固定镜像；
- **容量等待时长不确定**：热门区域可能数小时到数天，期间保持进程运行即可。