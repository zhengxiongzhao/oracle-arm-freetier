# CHANGELOG

## [v1.3.8] - 2026-09-16

### Removed
- README 移除 hitrov/oci-arm-host-capacity 相关内容（PAYG 建议引注与致谢条目）

---

## [v1.3.7] - 2026-09-16

### Changed
- README.md 整体重构：统一中文、以 Docker 部署为主线（快速开始→裸进程备选→配置表格→通知渠道→日志→FAQ）；清除上游残留（badges/clone 地址指向原仓库）；配置项改为表格并补默认值；新增 SSH 公网 IP FAQ；保留主区域选区指南、PAYG 建议、Mermaid 流程图与上游致谢

---

## [v1.3.6] - 2026-09-16

### Changed
- README 新增「Home Region & Region Selection」章节：主区域永久锁定不可变更（换区唯一途径是注销重注册）、PAYG 升级不改变非主区域计费、热门永久免费区域对照表（亚太/北美/欧洲）与选区建议（稳妥拿 4C24G ARM 选美东）、hitrov/oci-arm-host-capacity 的 PAYG 优先创建建议；ARM 免费额度描述修正为 4 OCPU/24GB（原误写 2 OCPU/12GB）；Credits 补充 hitrov 项目与 Oracle 区域/FAQ 官方链接

---

## [v1.3.5] - 2026-09-16

### Changed
- 新增 `LOG_TO` 配置项（`oci.env` / 环境变量）控制日志输出目标：`stdout`（默认，标准输出，`docker logs` 直接可见）/ `file`（原文件行为）/ `both`（两者兼有）；容器 compose 同步注入 `PYTHONUNBUFFERED=1` 消除 Python stdout 块缓冲，修复此前容器运行数天而 `docker logs` 无任何实时输出、须到宿主文件查看日志的问题

---

## [v1.3.4] - 2026-09-03

### Fixed
- 修复 `handle_errors` 重试判定白名单遗漏 `CannotParseRequest`、未中实例时的 `LimitExceeded`、`ServiceUnavailable` 及 `Conflict` 等 OCI 临时状态码，避免 OCI 网关临时抖动或租户配额瞬时锁定时误报未处理错误并中断抢实例循环

---

## [v1.3.3] - 2026-09-03

### Fixed
- 修复 `launch_instance` 与 `execute_oci_command` 未捕获 `oci.exceptions.ConnectTimeout` / `requests.exceptions.RequestException` 等网络超时异常的问题（OCI Python SDK 中 `ConnectTimeout` 继承自 vendor requests 而非 `oci.exceptions.RequestException`），统一定义 `OCI_RETRYABLE_EXCEPTIONS` 纳入 `handle_errors` 自动退避重试，避免瞬时网络抖动触发未处理错误告警并导致容器崩溃重启

---

## [v1.3.2] - 2026-08-31

### Changed
- 容器时区统一为上海:服务加 `TZ=Asia/Shanghai` + `/usr/share/zoneinfo` 与 `/etc/localtime:ro` 挂载(alpine 等无 tzdata 镜像,TZ 单独无效须挂载 zoneinfo;scratch 镜像同时获益)

---


## [v1.3.1] - 2026-08-28

### Fixed

- `oci.env` 中 Telegram token 曾存为占位符 `***`（`bot***/sendMessage` 404）——已替换为真实 token（@OpenClawZxzBot，getMe 验证有效），Telegram 通知恢复，与微信网关并发推送验证通过

---

## [v1.3.0] - 2026-08-28

### Added

- **通知并发化**：新增 `notify_all()` 并发分发（`ThreadPoolExecutor`，上限 4），Gmail / Telegram / WeChat / Discord 四渠道**配置几个就并发发几个**，任一渠道失败只记日志不阻塞其他渠道；启动/成功/失败三时机统一走并发分发（实测 3 渠道耗时 1.2s，串行需 3.6s）
- **微信通知网关优先**：新增 `WECHAT_GATEWAY_URL` / `WECHAT_GATEWAY_API_KEY` / `WECHAT_GATEWAY_SECRET` 三配置，微信通知优先调用本地 ClawBot 加密网关（`POST /api/v1/send`，X-API-Key + X-Timestamp + HMAC-SHA256 签名），网关不可达或失败时自动降级直连 iLink API
- `docker-compose.yml` 加入 `gateway-net` external 网络：容器内可直接访问 `clawbot-gateway:8080`（微信通知网关）

### Fixed

- 修复 `send_wechat_message` 函数内 `import time` 导致 `UnboundLocalError: cannot access local variable 'time'`（函数内任意位置 import 使 `time` 整体变为局部变量）

### Changed

- README / docs/USAGE.md 通知章节补充并发通知说明与网关配置方式

---

## [v1.2.0] - 2026-08-28

### Added

- `main.py` 内置 **WeChat ClawBot 通知**（腾讯官方 iLink Bot 协议，`ilinkai.weixin.qq.com`）：启动 / 创建成功（含实例详情）/ 未处理错误三时机与 Telegram 并列推送；复用 `requests`，零新增依赖
- 微信配置四键：`WECHAT_CLAWBOT_TOKEN`（bot_token，扫码登录获取）、`WECHAT_CLAWBOT_BASEURL`（可选，默认官方域名）、`WECHAT_TO_USER_ID`、`WECHAT_CTX_TOKEN`（入站消息 context_token）——任一必填键为空则微信通知静默禁用
- 实现细节：`AuthorizationType: ilink_bot_token` + 随机 `X-WECHAT-UIN`（防重放）+ `iLink-App-Id/ClientVersion` 请求头；唯一 `client_id` 消息幂等；失败仅记日志不中断主流程

### Changed

- 请求载荷经本地 mock 端点验证通过（headers + body 结构符合 iLink 2.4.6 协议规范）
- README / docs/USAGE.md 通知章节补充微信 ClawBot 的配置、触发时机与前置条件（需先登录 ClawBot 会话 + 用户先发一条消息）

---

## [v1.1.0] - 2026-08-28

### Added

- 新增 Docker 部署方式：`Dockerfile`（python:3.12-alpine，仅装依赖）+ `docker-compose.yml`（restart: unless-stopped，抢到实例后需手动 stop）
- 容器以宿主绝对路径 bind mount 项目目录（宿主侧 `/usr/local/deploy/hermes/workspace-data/oracle-freetier-instance-creation`），oci.env/oci_config 的绝对路径配置无需改动，日志与 `INSTANCE_CREATED` 直接落在宿主项目目录

---

## [v1.0.2] - 2026-08-27

### Added
- 新增 `docs/USAGE.md`：项目说明与使用指南（项目概述、快速开始、三组凭证获取方式、通知配置与触发时机/消息内容、运维手册、日志解读）

### Removed
- 移除 `docs/session-runbook-2026-08-27.md`（会话记录型文档，会话过程/验证结果/存档记录等内容不再保留）

---

## [v1.0.1] - 2026-08-27

### Added
- 新增 `docs/session-runbook-2026-08-27.md`：完整技术文档（架构、配置、改动说明、验证结果、运维手册、日志解读、安全注意事项）

---

## [v1.0.0] - 2026-08-27

### Added
- `main.py` 内置 Telegram 通知：启动、实例创建成功（含实例详情）、未处理错误三个时机直接推送（复用 `requests`，照 `send_discord_message` 模式实现）
- 新增 `verify_oci.py` 只读验证脚本：启动前校验 API 凭证、可用域、子网 OCID 与现有实例
- 本地部署配置：`oci.env`（含 Telegram Token/User ID）、`oci_config`、API 私钥（均已加入 `.gitignore`，不进版本库）

### Changed
- `.gitignore` 追加本地凭证/密钥/日志忽略规则，防止敏感信息入库
- `oci.env` 从 git 跟踪中移除（本地保留），避免 Telegram Token 等进入版本历史
