# WaRPA 管理控台与实例池可观测 PRD

## 1. 背景与目标

当前管理控台主要展示本地绑定批次、号码记录、操作日志和本地商户状态。接入 WaRPA 服务端待绑定队列后，管理控台需要补充服务端实例池视角，让运营或执行人员能看到“服务端有哪些实例待处理、本地执行到了哪一步、是否已经回写服务端”。

本 PRD 目标是在现有 `admin.html` 和 `src/extension/admin.ts` 的基础上新增 WaRPA 实例池可观测能力，形成服务端状态、扩展执行日志、本地留档之间的关联视图。

## 2. 用户价值

- 快速判断当前是否还有待 FB 绑定实例。
- 根据 `type`、`tenantId`、`routeLineId`、`proxyIp` 等字段定位异常批次。
- 对比服务端 `fbBindStatus` 与本地执行结果，发现回写失败或重复处理。
- 查询 WA 消息记录，辅助排查 OTP 未到、验证码延迟、设备断联等问题。

## 3. 范围

包含：

- 管理控台新增“WaRPA 实例池”视图。
- 展示待 FB 绑定实例列表。
- 展示本地执行记录与服务端实例字段的关联。
- 展示服务端回写状态和回写错误。
- 提供消息审计查询入口，调用 `/select-list`。
- 保留现有“绑定任务”和“商户管理”视图。

不包含：

- 在管理控台内直接执行 Facebook 页面自动化。
- 远端服务端数据修改能力，除明确的状态回写接口外不做编辑。
- 复杂 BI 报表或跨租户权限系统。

## 4. 相关接口

实例池查询：

```text
POST /api/v1/incubation/wa-msg/pending-fb-bind-list
```

WA 消息查询：

```text
POST /api/v1/incubation/wa-msg/select-list
```

状态回写读取来源：

- 本地 `admin_binding_records.payload.serverFbBindStatus`
- 本地 `admin_binding_records.payload.serverWritebackAt`
- 本地 `admin_binding_records.payload.serverWritebackError`

## 5. 信息架构

管理控台建议拆成 4 个顶层视图：

- `绑定任务`：保留现有批次、号码、日志。
- `商户管理`：保留现有商户主页创建和绑定计数。
- `WaRPA实例池`：新增，展示服务端待 FB 绑定实例。
- `WA消息审计`：新增，按号码或关键词查询消息记录。

## 6. WaRPA 实例池视图需求

### 6.1 筛选条件

页面顶部提供筛选：

- 账号类型：`CAT`、`TIGER`。
- `tenantId`。
- `jid`。
- `instanceId`。
- `owner`。
- `proxyIp`。
- `routeLineId`。
- 每页数量。

默认筛选：

- `type = CAT`。
- `page = 1`。
- `pageSize = 20`。

### 6.2 列表字段

实例池表格至少展示：

- 序号。
- `serialNo`。
- `type`。
- `tenantId`。
- `jid`。
- `instanceId`。
- `status`。
- `importStatus`。
- `fbBindStatus`。
- `proxyIp`。
- `routeLineName` 或 `routeLineCode`。
- 本地最近执行结果。
- 服务端回写结果。

### 6.3 本地记录关联

优先按以下顺序关联本地记录：

1. `instanceId`。
2. `jid`。
3. `phone`。

如果同一实例有多条本地记录，展示最近更新时间的一条，并允许点击查看对应操作日志。

### 6.4 状态展示

状态标签建议：

- 服务端待绑定：`WAITING_BIND`。
- 本地执行中：`pending`、`binding_requested`、`code_received`、`verifying`。
- 本地成功且已回写：`success + BIND_SUCCESS`。
- 本地成功但回写失败：`success + serverWritebackError`。
- 本地失败且已回写重试：`failed/disconnected + BIND_RETRY`。
- 本地暂停未回写：风控、权限、登录、安全验证类异常。

## 7. WA 消息审计视图需求

### 7.1 查询条件

支持：

- `senderPhone`。
- `receivePhone`。
- `instanceId`。
- `type`。
- `messageFlow`。
- `keyword`。
- 分页。

### 7.2 展示字段

消息列表至少展示：

- 创建时间。
- `instanceId`。
- `waType`。
- `senderPhone`。
- `receivePhone`。
- `messageFlow`。
- `text`。
- `status`。
- `deliverStatus`。
- `readStatus`。

### 7.3 用途

- 当 OTP 查询超时时，用当前号码快速查最近 5 分钟消息。
- 当设备显示未连接时，用 `instanceId` 查近期消息流。
- 当验证码解析失败时，人工确认消息文本是否包含验证码。

## 8. 本地代理需求

建议新增：

- `POST /api/warpa/pending-fb-bind-list`
- `POST /api/warpa/select-list`

代理统一负责：

- 网关密钥注入。
- `BaseResponse<T>` 解包。
- 错误信息标准化。
- CORS 处理。

## 9. 数据留档需求

本地 PostgreSQL 留档仍保留现有批次快照模式，但绑定记录 payload 需要增加服务端字段：

- `instanceId`
- `jid`
- `waType`
- `serialNo`
- `tenantId`
- `proxyIp`
- `routeLineId`
- `serverFbBindStatus`
- `serverWritebackAt`
- `serverWritebackError`

如果后续需要高效筛选，可再将关键字段从 JSONB 提升为生成列或独立列。

## 10. 异常与空状态

- 远端接口不可达：展示“WaRPA 服务不可达”，不影响现有本地绑定任务视图。
- 无待绑定实例：展示空状态“暂无待 FB 绑定实例”。
- 本地记录无法关联：实例仍展示，最近执行结果显示“未在本地执行过”。
- 消息审计查询为空：展示“未查询到消息”，不视为错误。
- 网关密钥缺失：展示本地代理配置错误。

## 11. 验收标准

- 管理控台新增 `WaRPA实例池` 视图。
- 用户可以按账号类型、租户、线路、号码筛选待绑定实例。
- 实例列表能展示服务端字段和本地最近执行结果。
- 本地成功但服务端回写失败的记录有明确标记。
- 用户可以按号码查询 WA 消息记录。
- 现有绑定任务和商户管理视图不回归。
- 测试覆盖接口 URL 构造、筛选参数、状态标签、本地记录关联和空状态。

## 12. 待确认

- 管理控台是否需要操作按钮触发“重新回写状态”。
- 是否需要导出服务端实例池查询结果。
- 是否有租户权限隔离要求。
