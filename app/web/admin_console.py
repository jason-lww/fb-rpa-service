"""自包含 admin 控台（Python 服务直出）。

streamlined 重写：消费 /api/admin-state、/api/merchants、/api/page-names、/api/personal-profiles，
展示绑定批次/记录/日志、商户计数与状态、名字池与个人主页。比旧 TS SPA 精简，聚焦观测。
"""

ADMIN_CONSOLE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ICS RPA 控台</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif; background: #0f1419; color: #e6e8eb; }
  header { padding: 16px 24px; background: #161b22; border-bottom: 1px solid #2b313a; display: flex; align-items: center; gap: 16px; position: sticky; top: 0; z-index: 10; }
  header h1 { font-size: 18px; margin: 0; }
  header .meta { color: #9aa4b2; font-size: 13px; }
  header button { margin-left: auto; background: #2563eb; color: #fff; border: 0; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 13px; }
  main { padding: 20px 24px; display: grid; gap: 24px; }
  section { background: #161b22; border: 1px solid #2b313a; border-radius: 12px; overflow: hidden; }
  section h2 { font-size: 14px; margin: 0; padding: 12px 16px; border-bottom: 1px solid #2b313a; color: #cdd5df; display: flex; gap: 8px; align-items: center; }
  section h2 .count { color: #9aa4b2; font-weight: 400; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #20262e; white-space: nowrap; }
  th { color: #9aa4b2; font-weight: 500; background: #12171d; position: sticky; top: 0; }
  td.wrap { white-space: normal; max-width: 420px; color: #b9c2cd; }
  .tablewrap { max-height: 360px; overflow: auto; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; }
  .s-success, .s-BIND_SUCCESS, .s-unbound, .s-available { background: #0f3d2e; color: #4ade80; }
  .s-failed, .s-disconnected, .s-unavailable, .s-BIND_RETRY { background: #3d1f1f; color: #f87171; }
  .s-pending, .s-binding_requested, .s-code_received, .s-verifying, .s-WAITING_BIND { background: #2a2f1a; color: #facc15; }
  .empty { padding: 20px 16px; color: #6b7280; font-size: 13px; }
  .err { background:#3d1f1f; color:#f87171; padding:10px 16px; font-size:13px; }
</style>
</head>
<body>
<header>
  <h1>ICS RPA 控台</h1>
  <span class="meta" id="meta">加载中…</span>
  <button id="refresh">刷新</button>
</header>
<main>
  <div class="err" id="err" style="display:none"></div>
  <section>
    <h2>绑定记录 <span class="count" id="recCount"></span></h2>
    <div class="tablewrap"><table id="records"><thead><tr>
      <th>批次</th><th>手机号</th><th>商户主页</th><th>状态</th><th>次数</th><th>回写</th><th class="wrap">最近错误</th>
    </tr></thead><tbody></tbody></table></div>
  </section>
  <section>
    <h2>商户 <span class="count" id="mCount"></span></h2>
    <div class="tablewrap"><table id="merchants"><thead><tr>
      <th>商户名</th><th>FB主页ID</th><th>已绑定</th><th>可用性</th><th>创建状态</th><th class="wrap">最近状态</th>
    </tr></thead><tbody></tbody></table></div>
  </section>
  <section>
    <h2>操作日志 <span class="count" id="logCount"></span></h2>
    <div class="tablewrap"><table id="logs"><thead><tr><th>时间</th><th>手机号</th><th class="wrap">消息</th></tr></thead><tbody></tbody></table></div>
  </section>
  <section>
    <h2>名字池 / 个人主页</h2>
    <div class="tablewrap"><table id="pool"><thead><tr><th>类型</th><th>名称</th><th>状态/ID</th></tr></thead><tbody></tbody></table></div>
  </section>
</main>
<script>
const pill = (s) => `<span class="pill s-${s}">${s||'-'}</span>`;
const esc = (v) => (v==null?'':String(v)).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function getJson(url){ const r = await fetch(url); if(!r.ok) throw new Error(url+' -> HTTP '+r.status); return r.json(); }
async function load(){
  const err = document.getElementById('err');
  err.style.display='none';
  try {
    const [state, merchants, pageNames, profiles] = await Promise.all([
      getJson('/api/admin-state').catch(()=>({records:[],operationLog:[],updatedAt:''})),
      getJson('/api/merchants').catch(()=>({merchants:[]})),
      getJson('/api/page-names').catch(()=>({pageNames:[]})),
      getJson('/api/personal-profiles').catch(()=>({personalProfiles:[]})),
    ]);
    const recs = state.records||[];
    document.querySelector('#records tbody').innerHTML = recs.length ? recs.map(r=>`<tr>
      <td>${esc(r.batchId)}</td><td>${esc(r.phone)}</td><td>${esc(r.businessPageName)}</td>
      <td>${pill(r.status)}</td><td>${esc(r.attemptCount)}</td><td>${pill(r.serverFbBindStatus)}</td>
      <td class="wrap">${esc(r.lastError)}</td></tr>`).join('') : '<tr><td colspan=7 class="empty">暂无记录</td></tr>';
    document.getElementById('recCount').textContent = recs.length;

    const ms = merchants.merchants||[];
    document.querySelector('#merchants tbody').innerHTML = ms.length ? ms.map(m=>`<tr>
      <td>${esc(m.merchantName)}</td><td>${esc(m.fbPageId)}</td><td>${esc(m.boundWaCount)}</td>
      <td>${pill(m.bindingAvailability)}</td><td>${esc(m.creationStatus)}</td>
      <td class="wrap">${esc(m.latestAlertMessage)}</td></tr>`).join('') : '<tr><td colspan=6 class="empty">暂无商户</td></tr>';
    document.getElementById('mCount').textContent = ms.length;

    const logs = (state.operationLog||[]).slice(-200).reverse();
    document.querySelector('#logs tbody').innerHTML = logs.length ? logs.map(l=>`<tr>
      <td>${esc(l.time)}</td><td>${esc(l.phone)}</td><td class="wrap">${esc(l.message)}</td></tr>`).join('') : '<tr><td colspan=3 class="empty">暂无日志</td></tr>';
    document.getElementById('logCount').textContent = (state.operationLog||[]).length;

    const poolRows = [
      ...(pageNames.pageNames||[]).map(p=>`<tr><td>名字池</td><td>${esc(p.pageName)}</td><td>${pill(p.status)}</td></tr>`),
      ...(profiles.personalProfiles||[]).map(p=>`<tr><td>个人主页</td><td>${esc(p.profileName)}</td><td>${esc(p.profileId)}</td></tr>`),
    ];
    document.querySelector('#pool tbody').innerHTML = poolRows.length ? poolRows.join('') : '<tr><td colspan=3 class="empty">暂无</td></tr>';

    document.getElementById('meta').textContent = '更新于 ' + (state.updatedAt||'-');
  } catch(e){
    err.textContent = '加载失败：' + e.message + '（请确认已配置 DATABASE_URL 且 MySQL 可达）';
    err.style.display='block';
  }
}
document.getElementById('refresh').addEventListener('click', load);
load();
setInterval(load, 10000);
</script>
</body>
</html>
"""
