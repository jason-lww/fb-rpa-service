# ics-rpa-service（FB WhatsApp 绑定自动化）

Python 实现的 FB 账号操作 RPA 服务：用 **patchright + `connect_over_cdp`** 连接一个**已登录 FB 的真实 Chrome**，复用其会话执行 WhatsApp 号码绑定/解绑与商业主页创建，最大限度降低 FB 风控/封号风险；养号系统对接、OTP、留档与 admin 控台均由本服务承担。

> 本服务由原 Chrome 扩展项目 `FBChromeBind` 重构而来，已全量迁移到 Python，原 TypeScript 实现已移除。

## 为什么连真实 Chrome

不拉起全新自动化浏览器，而是连到你手动启动、已登录 FB 的真实 Chrome 并复用其 `contexts[0]`（绝不 `new_context()`）。配合动作节奏、号码间随机间隔、FB 风控提示检测（限频/发码失败/非商业账号→暂停人工），把封控风险降到接近“真人操作”。

## 运行

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
patchright install chrome          # 首次需要

cp .env.example .env               # 填入 INCUBATION_GATEWAY_KEY、DATABASE_URL 等

# 启动一个已登录 FB 的真实 Chrome（务必用你平时登录的 profile）
chrome --remote-debugging-port=9222 --user-data-dir=/path/to/your/profile

uvicorn app.main:app --host 127.0.0.1 --port 8790 --reload
```

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 + OTP 环境/CDP 端点/DB 状态 |
| POST | `/rpa/fb/warpa-queue/start` | 从养号系统拉取待绑定实例并开始绑定队列 |
| GET | `/rpa/fb/tasks/{task_id}` | 查询绑定任务状态、记录、日志 |
| POST | `/rpa/fb/tasks/{task_id}/pause` | 暂停队列 |
| POST | `/rpa/fb/business-page/create` | 创建业务主页（可指定名称或从名字池取） |
| GET | `/rpa/fb/business-page/tasks/{task_id}` | 查询主页创建任务状态 |
| GET | `/api/admin-state` `/api/merchants` `/api/page-names` `/api/personal-profiles` | 留档/管理数据读写 |
| GET | `/admin-console` | 内置 admin 控台（HTML） |

## 模块

```text
app/core/         配置(env) + 日志
app/shared/       号码归一化、队列状态机、WaRPA 队列、国家码表、数据模型
app/clients/      incubation 网关客户端(OTP/连接检测/待绑定/回写)
app/services/     OTP 轮询(5s→15s×5)、绑定编排、主页创建编排
app/automation/   patchright connect_over_cdp 会话 + FB 绑定/主页创建 DOM 流程
app/db/           MySQL 会话(SQLAlchemy+PyMySQL) + 终态 schema
app/repositories/ admin-state / merchants / page-names / personal-profiles 留档仓库
app/web/          内置 admin 控台
app/main.py       FastAPI 入口
```

## 留档（MySQL）

设置 `DATABASE_URL=mysql+pymysql://user:pass@host:3306/db` 后，服务启动自动建表（幂等）。
绑定队列每处理完一个号码会把批次/记录/操作日志写入 MySQL，并维护商户已绑定计数与最新风控状态。
留空 `DATABASE_URL` 则禁用留档，仅保留内存任务态。

## 注意

- FB 页面 DOM/文案/风控策略经常变化。绑定与主页创建流程优先使用 `aria-label`、`role`、可见文本、`autocomplete="tel"`、`inputmode="numeric"` 等较稳定特征，但**首次务必小批量在真实 FB 上验证并按需微调选择器**，尤其是主页创建向导（类目“女装店”、设置向导序列）。
- 真实密钥不要提交，`.env.example` 仅占位。
- 文档参考：`docs/`、`服务端接口/`、`PRD/`。

## 进度

- [x] Phase 1：核心绑定链路（拉号 → 切主页 → 选 MX+52 → 填号 → 取码 → 确认 → 回写）+ 风控检测 + 拟人节奏
- [x] Phase 2：MySQL 留档（admin-state/merchants/page-names/profiles）+ 管理接口
- [x] Phase 3：业务主页创建自动化 + 内置 admin 控台；已删除被替代的 TS
