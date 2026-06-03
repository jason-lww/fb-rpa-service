# ICS RPA Service

基于 `daq-service` 的 FastAPI + Patchright 风格实现 FB 账号操作流程。

## 脚本 2：FB 账号操作流程

前提：

- Chrome 中已登录个人 FB 账号。
- 执行绑定/移除前，确保当前身份可切换到目标公司主页。
- 号码池 Excel 第一行需要包含手机号列，例如 `手机号`、`号码`、`phone`。
- 状态列支持 `状态` / `status`，账套列支持 `账套` / `投放状态`。

启动：

```bash
pip install -r requirements.txt
python -m patchright install chrome
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

绑定号码：

```bash
curl -X POST http://127.0.0.1:8000/rpa/fb/account-flow/bind-number \
  -H 'Content-Type: application/json' \
  -d '{
    "phone_pool_file": "/path/to/号池维护记录.xlsx",
    "company_page_name": "公司主页名称"
  }'
```

脚本会从最新 sheet 开始选择状态为空、且不是 `绑定前封号` 的号码。提交手机号后，通过接口写入 GEELARK 收到的 OTP：

```bash
curl -X POST http://127.0.0.1:8000/rpa/fb/account-flow/submit-otp \
  -H 'Content-Type: application/json' \
  -d '{"task_id": "<bind task id>", "otp_code": "123456"}'
```

绑定成功后，脚本会把 Excel 中该行 `账套` 更新为 `待投放`。

移除投放完成号码：

```bash
curl -X POST http://127.0.0.1:8000/rpa/fb/account-flow/remove-completed \
  -H 'Content-Type: application/json' \
  -d '{
    "phone_pool_file": "/path/to/号池维护记录.xlsx",
    "company_page_name": "公司主页名称"
  }'
```

脚本会扫描状态为 `投放完成` 的号码，进入 Linked accounts 列表移除，并把 Excel 状态更新为 `已移除`。

查询任务状态：

```bash
curl http://127.0.0.1:8000/rpa/fb/account-flow/tasks/<task_id>
```

FB 页面经常调整文案和 DOM。如果页面无法自动切换公司主页，可以在打开的 Chrome 中手动确认公司主页身份后，让脚本继续执行。
