# ics-rpa-service 使用文档

FB 账号操作 RPA 服务（Python 版）。用 **patchright + connect_over_cdp** 连接一台**已登录 FB 的真实 Chrome**，复用其会话执行：

- WhatsApp 号码绑定到 FB 商业主页（从养号系统拉号 → 绑定 → 取码 → 确认 → 回写）
- 解绑、业务主页创建
- 绑定数据留档（MySQL）+ 内置 admin 控台

> 选择“连真实 Chrome”而不是拉起全新自动化浏览器，是为了把 FB 风控/封号风险降到接近真人操作。

---

## 1. 环境要求

- Python 3.10+
- 一台桌面 Chrome（用于登录 FB 并开调试端口）
- MySQL 5.7+（可选，用于留档；不配也能跑，只是没有历史数据/控台）
- 能访问养号系统网关（incubation）

---

## 2. 安装

```bash
cd /Users/liweiwei/workplace/Java/ICS/ics-rpa-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
patchright install chrome          # 安装 patchright 用的 Chrome（首次）
```

---

## 3. 配置（.env）

复制模板并填写：

```bash
cp .env.example .env
```

关键项说明：

| 变量 | 说明 | 示例 |
| --- | --- | --- |
| `PORT` | 服务端口 | `8790` |
| `INCUBATION_GATEWAY_KEY` | 养号系统网关密钥（**必填**，否则取码/拉号/回写失败） | `xxxxx` |
| `OTP_SERVICE_ENVIRONMENT` | OTP/WaRPA 环境：`production` 或 `test` | `production` |
| `DATABASE_URL` | MySQL 连接串；留空则禁用留档 | 见下 |
| `CDP_ENDPOINT` | 真实 Chrome 的调试端点 | `http://127.0.0.1:9222` |
| `BETWEEN_PHONE_DELAY_MIN_SECONDS` / `MAX` | 号码之间随机间隔（拟人化） | `10` / `120` |
| `ACTION_DELAY_MS` | 单步动作前后停顿 | `300` |

MySQL 连接串格式（密码里的特殊字符要 URL 编码，例如 `#` → `%23`）：

```
DATABASE_URL=mysql+pymysql://用户名:密码@主机:端口/库名
# 例（密码 85209SbcS#c244b0 中的 # 编码为 %23）：
DATABASE_URL=mysql+pymysql://liweiwei:85209SbcS%23c244b0@sh-cdb-kohbvv70.sql.tencentcdb.com:26749/ics_rpa
```

> 不要把真实密钥/密码提交到仓库。`.env` 已被 `.gitignore` 忽略。

---

## 4. 准备 MySQL（可选，启用留档时）

库不存在时先建库（一次性）：

```sql
CREATE DATABASE IF NOT EXISTS ics_rpa DEFAULT CHARSET utf8mb4;
```

表会在**服务启动时自动创建**（幂等），无需手动建表。

---

## 5. 启动一台已登录 FB 的真实 Chrome（关键）

用你平时登录 FB 的浏览器配置，开启调试端口。**先在这个 Chrome 里手动登录好 FB，并确认能切换到目标商业主页。**

macOS：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/fb-rpa-profile"
```

Windows：

```bat
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="C:\fb-rpa-profile"
```

说明：
- `--user-data-dir` 指定一个独立的浏览器资料目录，第一次需要在里面手动登录 FB。
- 端口要和 `.env` 的 `CDP_ENDPOINT` 一致（默认 9222）。
- 该 Chrome 要保持打开，服务运行期间不要关。

---

## 6. 启动服务

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8790
```

启动时若配置了 `DATABASE_URL`，会自动建表（连远程库握手可能要十几秒，属正常）。

健康检查：

```bash
curl http://127.0.0.1:8790/health
```

返回里 `gatewayKeyConfigured` 和 `databaseConfigured` 应为 `true`。

---

## 7. 业务流程与 API

### 7.1 绑定队列（核心：脚本2）

从养号系统拉取“待 FB 绑定”的实例，逐个绑定。

```bash
curl -X POST http://127.0.0.1:8790/rpa/fb/warpa-queue/start \
  -H 'Content-Type: application/json' \
  -d '{ "type": "CAT", "pageSize": 10 }'
# 返回: {"taskId":"xxxx","status":"RUNNING"}
```

`type` 可选 `CAT`（猫号，默认）/`TIGER`（老虎号）/`FIVE_SEGMENT`（五段号）。

流程（每个号码）：检查设备连接 → 切到当前商业主页并记录主页名 → 选 `MX+52` → 填号 → 点“绑定/发送验证码” → 轮询取码（先等 5s，之后每 15s，最多 5 次）→ 填码确认 → 列表校验成功 → 回写 `fb-bind-status`。号码之间有 10–120s 随机间隔。

查询任务进度（含每个号码状态与操作日志）：

```bash
curl http://127.0.0.1:8790/rpa/fb/tasks/<taskId>
```

暂停队列：

```bash
curl -X POST http://127.0.0.1:8790/rpa/fb/tasks/<taskId>/pause
```

遇到 FB 风控（“你暂时无法使用这一功能”、“发送验证码时出错”、“非商业账号”）会自动暂停/失败并记录，不会硬怼。

### 7.2 业务主页创建

```bash
# 指定名称
curl -X POST http://127.0.0.1:8790/rpa/fb/business-page/create \
  -H 'Content-Type: application/json' \
  -d '{ "pageName": "My New Page", "personalProfileName": "María Elicia" }'

# 或从 MySQL 名字池随机取名（需先导入名字池，见 7.3）
curl -X POST http://127.0.0.1:8790/rpa/fb/business-page/create \
  -H 'Content-Type: application/json' -d '{}'
```

查询创建结果：

```bash
curl http://127.0.0.1:8790/rpa/fb/business-page/tasks/<taskId>
```

### 7.3 留档 / 管理数据

```bash
# 绑定历史快照（批次/记录/日志）
curl http://127.0.0.1:8790/api/admin-state

# 商户列表（含已绑定数、可用性、最新风控状态）
curl http://127.0.0.1:8790/api/merchants

# 名字池：导入
curl -X POST http://127.0.0.1:8790/api/page-names \
  -H 'Content-Type: application/json' \
  -d '{ "names": ["Page Name A", "Page Name B"] }'
curl http://127.0.0.1:8790/api/page-names

# 个人主页
curl -X POST http://127.0.0.1:8790/api/personal-profiles \
  -H 'Content-Type: application/json' \
  -d '{ "profileId": "100001", "profileName": "María Elicia" }'
curl http://127.0.0.1:8790/api/personal-profiles
```

### 7.4 admin 控台

浏览器打开：

```
http://127.0.0.1:8790/admin-console
```

展示绑定记录、商户计数与状态、操作日志、名字池/个人主页，每 10s 自动刷新（数据来自上面的 `/api/*`，需配置 `DATABASE_URL`）。

---

## 8. 完整跑一遍（最小流程）

1. 配好 `.env`（`INCUBATION_GATEWAY_KEY`、`DATABASE_URL`）。
2. 启动已登录 FB 的真实 Chrome（`--remote-debugging-port=9222`），确认能手动切到目标公司主页。
3. `uvicorn app.main:app --port 8790`，`curl /health` 确认 ok。
4. `POST /rpa/fb/warpa-queue/start` 启动绑定，记下 `taskId`。
5. `GET /rpa/fb/tasks/<taskId>` 跟踪进度；或开 `/admin-console` 看。
6. 跑完后在 `/api/merchants` 查看各商户已绑定数。

---

## 9. 常见问题

| 现象 | 排查 |
| --- | --- |
| 启动报“没有已存在的浏览器上下文” | 真实 Chrome 没开调试端口，或 `CDP_ENDPOINT` 端口不对，或 Chrome 没打开 |
| 取码一直 pending / 失败 | `INCUBATION_GATEWAY_KEY` 未配或环境（`OTP_SERVICE_ENVIRONMENT`）选错；号码设备未连接 |
| 找不到“绑定/确认/主页”等按钮 | FB 文案/DOM 变了，需要按实际页面微调 `app/automation/*.py` 里的文案与选择器 |
| 控台/`/api/*` 报“未配置 DATABASE_URL” | 没配 MySQL；配上 `DATABASE_URL` 重启 |
| 队列自动暂停并提示风控 | FB 触发限频/安全验证，按提示人工处理后再继续 |

---

## 10. 降低封控的注意事项

- 必须连**真实已登录**的 Chrome，不要用全新自动化浏览器。
- 配住宅/移动代理（在该 Chrome 上配置），避免数据中心 IP。
- 保留默认的号码间随机间隔与动作停顿，不要调太快。
- 首次小批量验证，FB 页面经常改版，需要时微调选择器。
