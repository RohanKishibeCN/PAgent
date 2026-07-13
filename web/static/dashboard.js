// PA Agent Web Dashboard 交互

// ── 工具函数 ──
function $(id) { return document.getElementById(id); }

function showToast(msg, type) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg; t.className = "toast " + (type || "info");
  t.style.display = "block";
  setTimeout(() => { t.style.display = "none"; }, 4000);
}

// ── 分析表单提交 ──
document.addEventListener("DOMContentLoaded", function() {
  const form = document.getElementById("analyzeForm");
  if (form) {
    form.addEventListener("submit", async function(e) {
      e.preventDefault();
      const btn = document.getElementById("analyzeBtn");
      btn.disabled = true; btn.textContent = "⏳ 分析中...";
      document.getElementById("loadingArea").style.display = "block";
      document.getElementById("loadingText").textContent = "正在获取数据...";
      document.getElementById("resultArea").style.display = "none";

      const fd = new FormData(this);
      try {
        const res = await fetch("/api/analyze", { method: "POST", body: fd });
        const data = await res.json();
        displayResult(data);
      } catch(err) {
        document.getElementById("resultContent").innerHTML =
          `<div class="result-section"><h3>错误</h3><p style="color:#ef4444">${err.message}</p></div>`;
        document.getElementById("resultArea").style.display = "block";
      } finally {
        btn.disabled = false; btn.textContent = "🚀 开始分析";
        document.getElementById("loadingArea").style.display = "none";
      }
    });

    // 交易所切换时刷新交易对下拉
    const exSel = document.getElementById("exchange");
    if (exSel) exSel.addEventListener("change", loadSymbols);
  }

  loadExchangeSetting();
  loadSettingsUI();
});

// ── 动态加载交易对 ──
async function loadSymbols() {
  const sel = document.getElementById("symbol");
  if (!sel) return;
  const exchange = document.getElementById("exchange")?.value || "okx";
  sel.disabled = true;
  sel.innerHTML = '<option value="">加载中...</option>';
  try {
    const res = await fetch("/api/symbols", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({exchange}),
    });
    const data = await res.json();
    sel.innerHTML = "";
    for (const sym of (data.symbols || [])) {
      const opt = document.createElement("option");
      opt.value = sym; opt.textContent = sym;
      sel.appendChild(opt);
    }
  } catch(err) {
    sel.innerHTML = '<option value="BTC/USDT">BTC/USDT</option><option value="ETH/USDT">ETH/USDT</option><option value="SOL/USDT">SOL/USDT</option>';
  }
  sel.disabled = false;
}

// ── 显示分析结果 ──
function displayResult(data) {
  const area = document.getElementById("resultArea");
  const content = document.getElementById("resultContent");
  let html = "";

  if (data.status === "error") {
    html = `<div class="result-section"><h3>❌ 错误</h3><p>${data.error}</p></div>`;
    content.innerHTML = html; area.style.display = "block"; return;
  }
  if (data.status === "preflight_failed") {
    html = `<div class="result-section"><h3>数据不足</h3><p>${data.error}</p></div>`;
    content.innerHTML = html; area.style.display = "block"; return;
  }

  if (data.kline_summary) {
    const ks = data.kline_summary;
    html += `<div class="result-section"><h3>📊 ${data.symbol} ${data.timeframe} — ${data.exchange}</h3>
      <div class="result-grid">
        <div class="result-item"><div class="label">当前价格</div><div class="value">${ks.current_price?.toFixed?.(2) ?? ks.current_price}</div></div>
        <div class="result-item"><div class="label">区间最高</div><div class="value">${ks.high_24h?.toFixed?.(2) ?? ks.high_24h}</div></div>
        <div class="result-item"><div class="label">区间最低</div><div class="value">${ks.low_24h?.toFixed?.(2) ?? ks.low_24h}</div></div>
        ${ks.atr ? `<div class="result-item"><div class="label">ATR14</div><div class="value">${ks.atr}</div></div>` : ""}
        <div class="result-item"><div class="label">K 线数</div><div class="value">${ks.bar_count}</div></div>
      </div></div>`;
  }

  if (data.diagnosis) {
    const d = data.diagnosis;
    const dirClass = d.direction === "bullish" ? "bullish" : d.direction === "bearish" ? "bearish" : "neutral";
    html += `<div class="result-section"><h3>📈 策略诊断</h3>
      <div class="result-grid">
        <div class="result-item"><div class="label">方向</div><div class="value ${dirClass}">${translateDir(d.direction)}</div></div>
        <div class="result-item"><div class="label">§2.3 闸门</div><div class="value">${d.gate_23?.answer || "—"}</div></div>
        <div class="result-item"><div class="label">AlwaysIn</div><div class="value">${d.gate_24?.branch || d.gate_24?.answer || "—"}</div></div>
        <div class="result-item"><div class="label">动量</div><div class="value">${d.gate_25?.answer || "—"}</div></div>
        <div class="result-item"><div class="label">极端混乱</div><div class="value">${d.chaos ? "是 ⚠️" : "否"}</div></div>
      </div></div>`;
  }

  if (data.decision) {
    const dec = data.decision.decision || {};
    html += `<div class="result-section"><h3>🎯 AI 交易决策</h3>
      <div class="result-grid">
        <div class="result-item"><div class="label">订单类型</div><div class="value">${dec.order_type || "—"}</div></div>
        <div class="result-item"><div class="label">方向</div><div class="value ${(dec.order_direction||"").includes("多") ? "bullish" : "bearish"}">${dec.order_direction || "—"}</div></div>
        <div class="result-item"><div class="label">入场价</div><div class="value">${dec.entry_price ? dec.entry_price : "—"}</div></div>
        <div class="result-item"><div class="label">止损</div><div class="value" style="color:#ef4444">${dec.stop_loss_price ? dec.stop_loss_price : "—"}</div></div>
        <div class="result-item"><div class="label">止盈</div><div class="value" style="color:#22c55e">${dec.take_profit_price ? dec.take_profit_price : "—"}</div></div>
        <div class="result-item"><div class="label">置信度</div><div class="value">${dec.trade_confidence ?? "—"}%</div></div>
      </div></div>`;
  }

  if (data.status === "no_ai_key") {
    html += `<div style="background:#2a1a1a;border:1px solid #4a2a2a;border-radius:8px;padding:16px;margin-top:16px">
      <h3 style="color:#ef4444">⚠️ 未配置 API Key</h3>
      <p style="margin-top:8px;color:#a0a0a0">策略引擎已运行，但 AI 分析需要配置 API Key。<br>
      在 <a href="/settings" style="color:#7c3aed">设置页面</a> 中填写 AI API Key 即可。</p></div>`;
  }

  if (data.usage) {
    html += `<div class="result-section"><h3>📊 Token 用量</h3>
      <p style="font-size:13px;color:#888">prompt=${data.usage.prompt_tokens || 0} | completion=${data.usage.completion_tokens || 0} | total=${data.usage.total_tokens || 0}</p></div>`;
  }

  content.innerHTML = html;
  area.style.display = "block";
}

function translateDir(d) {
  const m = { bullish: "📈 多头", bearish: "📉 空头", neutral: "➡️ 中性" };
  return m[d] || d;
}

// ── 历史记录 ──
async function loadResults() {
  const container = document.getElementById("resultsTable");
  if (!container) return;
  container.innerHTML = '<div class="empty-state">加载中...</div>';
  try {
    const res = await fetch("/api/results");
    const data = await res.json();
    if (!data.items.length) {
      container.innerHTML = '<div class="empty-state">暂无分析记录，先去 <a href="/" style="color:#7c3aed">分析页面</a> 运行一次</div>';
      return;
    }
    let html = `<table><thead><tr><th>时间</th><th>标的</th><th>周期</th><th>方向</th><th>订单类型</th><th>置信度</th><th>状态</th></tr></thead><tbody>`;
    for (const item of data.items) {
      const dirClass = item.direction === "bullish" ? "bullish" : item.direction === "bearish" ? "bearish" : "";
      const status = item.error ? `<span class="error-badge">❌ 错误</span>` : `<span class="success-badge">✓ 成功</span>`;
      html += `<tr class="clickable" onclick="showDetail('${item.filename}')">
        <td>${item.time?.slice(0,19) || "—"}</td>
        <td>${item.symbol || "—"}</td>
        <td>${item.timeframe || "—"}</td>
        <td class="${dirClass}">${translateDir(item.direction) || "—"}</td>
        <td>${item.order_type || "—"}</td>
        <td>${item.confidence !== "?" ? item.confidence + "%" : "—"}</td>
        <td>${status}</td>
      </tr>`;
    }
    html += "</tbody></table>";
    container.innerHTML = html;
  } catch(err) {
    container.innerHTML = `<div class="empty-state">加载失败: ${err.message}</div>`;
  }
}

async function showDetail(filename) {
  const modal = document.getElementById("detailModal");
  const content = document.getElementById("detailContent");
  if (!modal) return;
  modal.style.display = "flex";
  content.textContent = "加载中...";
  try {
    const res = await fetch(`/api/results/${filename}`);
    const data = await res.json();
    content.textContent = JSON.stringify(data, null, 2);
  } catch(err) {
    content.textContent = `错误: ${err.message}`;
  }
}

function closeDetail() {
  const modal = document.getElementById("detailModal");
  if (modal) modal.style.display = "none";
}

// ── 设置页面 ──
async function loadSettingsUI() {
  const root = document.getElementById("settingsRoot");
  if (!root) return;
  root.innerHTML = '<div class="empty-state">加载中...</div>';

  try {
    const res = await fetch("/api/settings");
    const data = await res.json();

    let html = '<div class="settings-sections">';

    // ─── 1. 交易所设置 ───
    html += '<div class="card"><h2>🔌 交易所</h2>';
    html += settingsCard("交易所", `
      <select id="s_exchange" style="background:#0f0f1a;border:1px solid #2a2a4a;border-radius:6px;padding:8px 12px;color:#e0e0e0;font-size:14px">
        <option value="okx">OKX</option>
        <option value="binance">Binance</option>
        <option value="bybit">Bybit</option>
        <option value="bitget">Bitget</option>
        <option value="kucoin">KuCoin</option>
      </select>
      <button class="btn btn-sm btn-primary" onclick="testExchange()">测试连接</button>
      <span id="s_test_result" style="font-size:12px;margin-left:8px"></span>
    `, "exchange");
    html += '</div>';

    // ─── 2. 交易对设置 ───
    html += '<div class="card"><h2>📊 交易参数</h2>';
    html += settingsCard("交易对", `<input type="text" id="s_symbol" value="${data.general.last_symbol}" class="setting-input">`, "symbol");
    html += settingsCard("周期", `
      <select id="s_tf" class="setting-input">
        <option value="15m" ${data.general.last_timeframe==="15m"?"selected":""}>15分钟</option>
        <option value="1h" ${data.general.last_timeframe==="1h"?"selected":""}>1小时</option>
        <option value="4h" ${data.general.last_timeframe==="4h"?"selected":""}>4小时</option>
        <option value="1d" ${data.general.last_timeframe==="1d"?"selected":""}>1天</option>
      </select>
    `, "timeframe");
    html += settingsCard("K 线数量", `<input type="number" id="s_bar_count" value="${data.general.analysis_bar_count}" min="20" max="500" class="setting-input" style="width:100px">`, "bars");
    html += settingsCard("分析偏向", `
      <select id="s_stance" class="setting-input">
        <option value="conservative" ${data.general.decision_stance==="conservative"?"selected":""}>保守</option>
        <option value="balanced" ${data.general.decision_stance==="balanced"?"selected":""}>平衡</option>
        <option value="aggressive" ${data.general.decision_stance==="aggressive"?"selected":""}>激进</option>
      </select>
    `, "stance");
    html += settingsCard("置信度门槛", `<input type="number" id="s_confidence" value="${data.general.decision_confidence_threshold}" min="0" max="100" class="setting-input" style="width:80px">%`);
    html += '</div>';

    // ─── 3. AI 模型设置 ───
    html += '<div class="card"><h2>🤖 AI 模型</h2>';
    html += settingsCard("模型", `<input type="text" id="s_model" value="${data.provider.model}" class="setting-input" style="width:300px">`, "model");
    html += settingsCard("API 地址", `<input type="text" id="s_base_url" value="${data.provider.base_url}" class="setting-input" style="width:400px">`, "base_url");
    html += settingsCard("API Key", `
      <input type="password" id="s_api_key" placeholder="${data.provider.api_key_configured ? '已配置（输入新 Key 覆盖）' : '未配置，在此输入'}" class="setting-input" style="width:300px">
      <span style="font-size:12px;margin-left:8px;color:${data.provider.api_key_configured ? '#22c55e' : '#ef4444'}">${data.provider.api_key_configured ? '✅ 已配置' : '❌ 未配置'}</span>
    `, "api_key");
    html += settingsCard("思考模式", `
      <label class="toggle"><input type="checkbox" id="s_thinking" ${data.provider.thinking ? "checked" : ""}><span class="toggle-slider"></span></label>
    `, "thinking");
    html += '</div>';

    // ─── 4. 交易所 API（自动交易用） ───
    const exCfg = data.exchange_api || {};
    html += '<div class="card" id="exApiCard"><h2>🔐 交易所 API（自动下单用）</h2>';
    html += `<div style="background:#2a1a1a;border:1px solid #4a2a2a;border-radius:8px;padding:12px;margin-bottom:16px;font-size:13px">
      ⚠️ <strong>安全提醒</strong>：在交易所后台创建 API Key 时，<br>
      1. 只勾选「交易」+「读取」权限<br>
      2. 绝对不要勾选「提现」权限<br>
      3. 绑定 IP 白名单到当前服务器 IP<br>
      4. 或使用 <code>.env</code> 文件存储（通过 SSH 在项目目录创建 .env）<br>
    </div>`;
    html += settingsCard("API Key", `<input type="password" id="s_ex_key" placeholder="${exCfg.api_key_masked || '输入交易所 API Key'}" class="setting-input" style="width:400px">`, "ex_api_key");
    html += settingsCard("Secret", `<input type="password" id="s_ex_secret" placeholder="${exCfg.secret_masked || '输入 Secret'}" class="setting-input" style="width:400px">`, "ex_secret");
    html += settingsCard("Passphrase", `<input type="password" id="s_ex_pass" placeholder="${exCfg.password_masked || 'OKX 需要（Binance 可留空）'}" class="setting-input" style="width:400px">`, "ex_pass");
    html += `<div style="display:flex;gap:12px;margin-top:12px">
      <button class="btn btn-sm btn-primary" onclick="testExchangeAuth()">测试认证</button>
      <span id="s_auth_result" style="font-size:12px;line-height:32px"></span>
    </div>`;
    html += '</div>';

    // ─── 5. 自动交易开关 ───
    const tr = data.trading || {};
    html += '<div class="card"><h2>🤖 自动交易</h2>';
    html += `<div style="background:${tr.auto_trade_enabled ? '#1a2a1a' : '#1a1a2e'};border:1px solid ${tr.auto_trade_enabled ? '#2a4a2a' : '#2a2a4a'};border-radius:8px;padding:16px;margin-bottom:16px">
      <div style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <strong style="font-size:16px">自动下单</strong><br>
          <span style="font-size:12px;color:#888">
            ${tr.auto_trade_enabled
              ? '⚠️ 开启中！分析结果将通过交易所 API 自动下单'
              : '🔒 已关闭。开启后将根据分析结果自动发送订单'}
          </span>
        </div>
        <label class="toggle toggle-lg">
          <input type="checkbox" id="s_auto_trade" ${tr.auto_trade_enabled ? "checked" : ""}>
          <span class="toggle-slider"></span>
        </label>
      </div>
    </div>`;
    html += settingsCard("下单数量", `<input type="number" id="s_trade_amt" value="${tr.trade_amount}" min="0.0001" step="0.0005" class="setting-input" style="width:120px"> BTC`, "trade_amt");
    html += settingsCard("单笔风险", `<input type="number" id="s_risk" value="${tr.max_risk_per_trade_pct}" min="0.001" max="0.5" step="0.005" class="setting-input" style="width:80px"> = ${(tr.max_risk_per_trade_pct * 100).toFixed(1)}% 账户`, "risk_pct");
    html += settingsCard("最低置信度", `<input type="number" id="s_min_conf" value="${tr.min_confidence}" min="0" max="100" class="setting-input" style="width:80px">% 以上才下单`, "min_conf");
    html += '</div>';

    // ─── 6. 通知设置 ───
    html += '<div class="card"><h2>🔔 通知（飞书）</h2>';
    html += settingsCard("飞书通知", `
      <label class="toggle"><input type="checkbox" id="s_feishu_enabled" ${data.feishu?.enabled ? "checked" : ""}><span class="toggle-slider"></span></label>
    `, "feishu_enable");
    html += settingsCard("Webhook URL", `<input type="text" id="s_feishu_url" value="${data.feishu?.webhook_url || ''}" class="setting-input" style="width:400px" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/...">`, "feishu_url");
    html += '</div>';

    // ─── 7. 保存按钮 ───
    html += `<div style="display:flex;justify-content:flex-end;gap:12px;padding:16px 0">
      <button class="btn btn-primary" onclick="saveAllSettings()" style="padding:12px 32px;font-size:16px">💾 保存所有设置</button>
    </div>`;

    html += '</div>';
    root.innerHTML = html;

    // Set exchange dropdown
    const exSel = document.getElementById("s_exchange");
    if (exSel && data.general.last_ccxt_exchange) exSel.value = data.general.last_ccxt_exchange;

  } catch(err) {
    root.innerHTML = `<div class="empty-state">加载设置失败: ${err.message}</div>`;
  }
}

function settingsCard(label, content, id) {
  return `<div class="setting-item">
    <span class="label">${label}</span>
    <div style="display:flex;align-items:center;gap:8px">${content}</div>
  </div>`;
}

// ── 测试交易所连接 ──
async function testExchange() {
  const ex = document.getElementById("s_exchange").value;
  const btn = event?.target;
  if (btn) btn.disabled = true;
  document.getElementById("s_test_result").textContent = "测试中...";
  try {
    const res = await fetch("/api/settings/test-exchange", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({exchange: ex}),
    });
    const data = await res.json();
    document.getElementById("s_test_result").textContent = data.message;
  } catch(err) {
    document.getElementById("s_test_result").textContent = "❌ 请求失败";
  }
  if (btn) btn.disabled = false;
}

// ── 测试交易所认证 ──
async function testExchangeAuth() {
  const exchange = document.getElementById("s_exchange").value;
  const apiKey = document.getElementById("s_ex_key").value;
  const secret = document.getElementById("s_ex_secret").value;
  const password = document.getElementById("s_ex_pass").value;
  const el = document.getElementById("s_auth_result");
  el.textContent = "⏳ 认证中...";

  try {
    const res = await fetch("/api/settings/test-exchange-auth", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ exchange, api_key: apiKey, secret, password }),
    });
    const data = await res.json();
    if (data.ok && data.balance) {
      const b = data.balance;
      el.textContent = `${data.message} | 余额: USDT=${b.USDT} BTC=${b.BTC}`;
    } else {
      el.textContent = data.message;
    }
  } catch(err) {
    el.textContent = "❌ 请求失败";
  }
}

// ── 保存所有设置 ──
async function saveAllSettings() {
  const body = {};

  body.general = {
    last_ccxt_exchange: getVal("s_exchange"),
    last_symbol: getVal("s_symbol"),
    last_timeframe: getVal("s_tf"),
    analysis_bar_count: intVal("s_bar_count"),
    decision_stance: getVal("s_stance"),
    decision_confidence_threshold: intVal("s_confidence"),
  };

  body.provider = {
    model: getVal("s_model"),
    base_url: getVal("s_base_url"),
    thinking: chkVal("s_thinking"),
  };

  // Only send API key if user typed something (don't overwrite with empty)
  const apik = document.getElementById("s_api_key")?.value?.trim();
  if (apik) body.provider.api_key = apik;

  body.exchange_api = {};
  const ek = document.getElementById("s_ex_key")?.value?.trim();
  if (ek) body.exchange_api.api_key = ek;
  const es = document.getElementById("s_ex_secret")?.value?.trim();
  if (es) body.exchange_api.secret = es;
  const ep = document.getElementById("s_ex_pass")?.value?.trim();
  if (ep) body.exchange_api.password = ep;

  body.trading = {
    auto_trade_enabled: chkVal("s_auto_trade"),
    trade_amount: floatVal("s_trade_amt"),
    max_risk_per_trade_pct: floatVal("s_risk"),
    min_confidence: intVal("s_min_conf"),
  };

  body.feishu = {
    enabled: chkVal("s_feishu_enabled"),
    webhook_url: getVal("s_feishu_url"),
  };

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.ok) {
      showToast("✅ 设置已保存", "success");
      // 重新加载以刷新显示
      setTimeout(() => loadSettingsUI(), 500);
    } else {
      showToast("❌ 保存失败", "error");
    }
  } catch(err) {
    showToast("❌ 保存失败: " + err.message, "error");
  }
}

function getVal(id) { return document.getElementById(id)?.value || ""; }
function intVal(id) { return parseInt(document.getElementById(id)?.value) || 0; }
function floatVal(id) { return parseFloat(document.getElementById(id)?.value) || 0; }
function chkVal(id) { return document.getElementById(id)?.checked || false; }

// ── 分析页加载默认交易所 ──
async function loadExchangeSetting() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    const ex = data.general?.last_ccxt_exchange;
    const sy = data.general?.last_symbol;
    if (ex && document.getElementById("exchange")) document.getElementById("exchange").value = ex;
    if (sy && document.getElementById("symbol")) document.getElementById("symbol").value = sy;
    loadSymbols();
  } catch(_) {}
}
