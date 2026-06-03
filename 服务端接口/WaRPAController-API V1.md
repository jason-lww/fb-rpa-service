# WaRPAController 接口文档

## 基本信息

- Base URL: `/api/v1/incubation/wa-msg`
- Method: 全部为 `POST`
- Content-Type: `application/json`
- 返回结构: 统一包裹在 `BaseResponse<T>` 中，业务数据在 `data` 字段。

示例返回:

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

## 状态枚举

实例连接状态:

- `QRCODE`: 等待扫码
- `CONNECTED`: 已连接
- `DISCONNECTED`: 已断开
- `LOGGEDOUT`: 已登出
- `UNPAIRED`: 未配对
- `FAILED`: 失败

App 扫码录入状态 `importStatus`:

- `WAITING_IMPORT`: 等待录入
- `IMPORT_SUCCESS`: 录入成功
- `WAITING_RETRY`: 等待重试

FB 绑定状态 `fbBindStatus`:

- `WAITING_BIND`: 等待绑定
- `BIND_SUCCESS`: 绑定成功
- `BIND_RETRY`: 等待重试

账号类型:

- `CAT`: 猫号，默认值
- `TIGER`: 老虎号

## 1. 查询 WA 消息列表

`POST /select-list`

用于分页查询 WA 消息记录。

请求参数:

```json
{
  "page": 1,
  "pageSize": 10,
  "type": "CAT",
  "instanceId": "instance-id",
  "senderPhone": "521xxxx",
  "receivePhone": "521xxxx",
  "messageFlow": "INCOMING",
  "keyword": "hello"
}
```

响应 data:

```json
{
  "records": [
    {
      "id": 1,
      "tenantId": 1001,
      "instanceId": "instance-id",
      "waType": "CAT",
      "type": "TEXT",
      "receivePhone": "521xxxx",
      "senderPhone": "521xxxx",
      "messageFlow": "INCOMING",
      "msgSource": "INCOMING",
      "text": "hello",
      "filePath": null,
      "msgId": "message-id",
      "status": "DELIVERY",
      "deliverStatus": "true",
      "readStatus": "false",
      "createTime": 1710000000000,
      "userId": 123
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 10
}
```

## 2. 查询 FB/设备验证码

`POST /device/verification-code`

按手机号查询 `whatsapp_device` 库中已连接账号近 5 分钟消息里的验证码。该接口不区分猫号/老虎号，只依赖设备库中账号连接状态。

请求参数:

```json
{
  "phone": "521xxxx"
}
```

响应 data:

```json
{
  "verificationCode": "12345",
  "timestamp": 1710000000000,
  "status": "CONNECTED",
  "message": null
}
```

未连接示例:

```json
{
  "verificationCode": null,
  "timestamp": null,
  "status": "UNCONNECTED",
  "message": "no connected account can use"
}
```

## 3. 获取登录 Code

`POST /login-code`

根据 `jid` 或 `instanceId` 查询实例及代理配置，调用 WhatsApp Go 服务获取登录验证码。支持猫号和老虎号。

查询规则:

- 传 `instanceId`: 先查猫号，不存在再查老虎号。
- 不传 `instanceId`: 按 `jid` 先找可用猫号，不存在再找可用老虎号。
- 可用实例条件: `status = QRCODE`、已配置代理、未删除、未分配 `userId`。

请求参数:

```json
{
  "jid": "521xxxx",
  "instanceId": "optional-instance-id"
}
```

响应 data:

```json
{
  "instanceId": "instance-id",
  "code": "123456",
  "error": null
}
```

无可用账号示例:

```json
{
  "instanceId": null,
  "code": null,
  "error": "No available account"
}
```

## 4. 查询待 App 扫码绑定实例

`POST /pending-scan-bind-list`

查询待 App 扫码绑定的实例。默认查询猫号；传 `type=TIGER` 查询老虎号。固定筛选 `importStatus = WAITING_IMPORT`。

返回的实例记录包含 `serialNo`，对应批量导入时的序列号。

请求参数:

```json
{
  "page": 1,
  "pageSize": 10,
  "type": "CAT",
  "tenantId": 1001,
  "instanceId": "instance-id",
  "jid": "521xxxx",
  "owner": "owner",
  "proxyIp": "1.2.3.4",
  "status": "QRCODE",
  "routeLineId": 1
}
```

响应 data:

```json
{
  "records": [
    {
      "id": "1",
      "tenantId": "1001",
      "type": "CAT",
      "instanceId": "instance-id",
      "jid": "521xxxx",
      "avatar": null,
      "name": null,
      "status": "QRCODE",
      "serialNo": "SN001",
      "importStatus": "WAITING_IMPORT",
      "fbBindStatus": "WAITING_BIND",
      "proxyId": "10",
      "proxyIp": "1.2.3.4",
      "routeLineId": null,
      "routeLineName": null,
      "routeLineCode": null
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 10
}
```

## 5. 查询待 FB 绑定实例

`POST /pending-fb-bind-list`

查询待 FB 绑定的实例。默认查询猫号；传 `type=TIGER` 查询老虎号。固定筛选 `fbBindStatus = WAITING_BIND`。

返回的实例记录包含 `serialNo`，对应批量导入时的序列号。

请求参数:

```json
{
  "page": 1,
  "pageSize": 10,
  "type": "CAT",
  "tenantId": 1001,
  "instanceId": "instance-id",
  "jid": "521xxxx",
  "owner": "owner",
  "proxyIp": "1.2.3.4",
  "status": "QRCODE",
  "routeLineId": 1
}
```

响应 data:

```json
{
  "records": [
    {
      "id": "1",
      "tenantId": "1001",
      "type": "CAT",
      "instanceId": "instance-id",
      "jid": "521xxxx",
      "status": "QRCODE",
      "serialNo": "SN001",
      "importStatus": "IMPORT_SUCCESS",
      "fbBindStatus": "WAITING_BIND",
      "proxyId": "10",
      "proxyIp": "1.2.3.4"
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 10
}
```

## 6. 接收 App 扫码绑定状态

`POST /app-scan-bind-status`

按 `jid` 先查猫号，不存在再查老虎号，更新实例的 `importStatus`。

请求参数:

```json
{
  "jid": "521xxxx",
  "status": "IMPORT_SUCCESS"
}
```

参数说明:

- `jid`: 必填，WhatsApp 账号 jid 或手机号。
- `status`: 可选。不传时默认 `IMPORT_SUCCESS`。
- 支持状态: `WAITING_IMPORT`、`IMPORT_SUCCESS`、`WAITING_RETRY`。

响应 data:

```json
{
  "id": 1,
  "instanceId": "instance-id",
  "jid": "521xxxx",
  "status": "QRCODE",
  "tenantId": 1001,
  "proxyId": 10,
  "serialNo": "SN001",
  "importStatus": "IMPORT_SUCCESS",
  "fbBindStatus": "WAITING_BIND"
}
```

## 7. 接收 FB 绑定状态

`POST /fb-bind-status`

按 `jid` 先查猫号，不存在再查老虎号，更新实例的 `fbBindStatus`。

请求参数:

```json
{
  "jid": "521xxxx",
  "status": "BIND_SUCCESS"
}
```

参数说明:

- `jid`: 必填，WhatsApp 账号 jid 或手机号。
- `status`: 可选。不传时默认 `BIND_SUCCESS`。
- 支持状态: `WAITING_BIND`、`BIND_SUCCESS`、`BIND_RETRY`。

响应 data:

```json
{
  "id": 1,
  "instanceId": "instance-id",
  "jid": "521xxxx",
  "status": "QRCODE",
  "tenantId": 1001,
  "proxyId": 10,
  "serialNo": "SN001",
  "importStatus": "IMPORT_SUCCESS",
  "fbBindStatus": "BIND_SUCCESS"
}
```

