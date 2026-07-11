// PA Agent Web Dashboard 交互

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
  }

  // 默认加载上次使用的交易所
  loadExchangeSetting();
});

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

  // K 线摘要
  if (data.kline_summary) {
    const ks = data.kline_summary;
    html += `<div class="result-section"><h3>${data.symbol} ${data.timeframe} — ${data.exchange}</h3>
      <div class="result-grid">
        <div class="result-item"><div class="label">当前价格</div><div class="value">${ks.current_price.toFixed(2)}</div></div>
        <div class="result-item"><div class="label">区间最高</div><div class="value">${ks.high_24h.toFixed(2)}</div></div>
        <div class="result-item"><div class="label">区间最低</div><div class="value">${ks.low_24h.toFixed(2)}</div></div>
        ${ks.atr ? `<div class="result-item"><div class="label">ATR14</div><div class="value">${ks.atr}</div></div>` : ""}
        <div class="result-item"><div class="label">K 线数</div><div class="value">${ks.bar_count}</div></div>
      </div></div>`;
  }

  // 策略诊断
  if (data.diagnosis) {
    const d = data.diagnosis;
    const dirClass = d.direction === "bullish" ? "bullish" : d.direction === "bearish" ? "bearish" : "neutral";
    html += `<div class="result-section"><h3>📈 策略诊断</h3>
      <div class="result-grid">
        <div class="result-item"><div class="label">方向</div><div class="value ${dirClass}">${translateDir(d.direction)}</div></div>
        <div class="result-item"><div class="label">§2.3 闸门</div><div class="value">${d.gate_23.answer}</div></div>
        <div class="result-item"><div class="label">AlwaysIn</div><div class="value">${d.gate_24.branch || d.gate_24.answer}</div></div>
        <div class="result-item"><div class="label">动量</div><div class="value">${d.gate_25.answer}</div></div>
        <div class="result-item"><div class="label">极端混乱</div><div class="value">${d.chaos ? "是 ⚠️" : "否"}</div></div>
      </div></div>`;
  }

  // AI 决策
  if (data.decision) {
    const dec = data.decision.decision || {};
    html += `<div class="result-section"><h3>🎯 AI 交易决策</h3>
      <div class="result-grid">
        <div class="result-item"><div class="label">订单类型</div><div class="value">${dec.order_type || "—"}</div></div>
        <div class="result-item"><div class="label">方向</div><div class="value ${(dec.order_direction||"").includes("多") ? "bullish" : "bearish"}">${dec.order_direction || "—"}</div></div>
        <div class="result-item"><div class="label">入场价</div><div class="value">${dec.entry_price ? dec.entry_price.toFixed?.(2) ?? dec.entry_price : "—"}</div></div>
        <div class="result-item"><div class="label">止损</div><div class="value" style="color:#ef4444">${dec.stop_loss_price ? dec.stop_loss_price.toFixed?.(2) ?? dec.stop_loss_price : "—"}</div></div>
        <div class="result-item"><div class="label">止盈</div><div class="value" style="color:#22c55e">${dec.take_profit_price ? dec.take_profit_price.toFixed?.(2) ?? dec.take_profit_price : "—"}</div></div>
        <div class="result-item"><div class="label">置信度</div><div class="value">${dec.trade_confidence ?? "—"}%</div></div>
      </div></div>`;
  }

  if (data.status === "no_ai_key") {
    html += `<div style="background:#2a1a1a;border:1px solid #4a2a2a;border-radius:8px;padding:16px;">
      <h3 style="color:#ef4444">⚠️ 未配置 API Key</h3>
      <p style="margin-top:8px;color:#a0a0a0">策略引擎已运行，但 AI 分析需要配置 API Key。<br>
      请在 VPS 上执行：
      <code style="display:block;background:#0f0f1a;padding:12px;margin:12px 0;border-radius:6px;font-size:12px">
        nano config/settings.json <br>
        # 填入 provider.api_key
      </code>
      </p></div>`;
  }

  if (data.usage) {
    html += `<div class="result-section"><h3>Token 用量</h3>
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
    let html = `<table>
      <thead><tr><th>时间</th><th>标的</th><th>周期</th><th>方向</th><th>订单类型</th><th>置信度</th><th>状态</th></tr></thead><tbody>`;
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
async function loadSettings() {
  const container = document.getElementById("settingsContent");
  if (!container) return;
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    let html = '<div class="settings-grid">';

    // 交易所设置
    html += `<div class="setting-item">
      <span class="label">交易所</span>
      <form id="exchangeForm" style="display:flex;gap:8px;align-items:center">
        <select name="exchange" id="settingsExchange" style="background:#0f0f1a;border:1px solid #2a2a4a;border-radius:6px;padding:6px 10px;color:#e0e0e0">
          <option value="okx" ${data.general.last_ccxt_exchange === "okx" ? "selected" : ""}>OKX</option>
          <option value="binance" ${data.general.last_ccxt_exchange === "binance" ? "selected" : ""}>Binance</option>
          <option value="bybit" ${data.general.last_ccxt_exchange === "bybit" ? "selected" : ""}>Bybit</option>
          <option value="bitget" ${data.general.last_ccxt_exchange === "bitget" ? "selected" : ""}>Bitget</option>
          <option value="kucoin" ${data.general.last_ccxt_exchange === "kucoin" ? "selected" : ""}>KuCoin</option>
        </select>
        <button type="submit" class="btn btn-primary btn-sm">保存</button>
      </form>
    </div>`;

    // 默认标的
    html += `<div class="setting-item">
      <span class="label">默认交易对</span>
      <span class="value">${data.general.last_symbol}</span>
    </div>`;

    // 默认周期
    html += `<div class="setting-item">
      <span class="label">默认周期</span>
      <span class="value">${data.general.last_timeframe}</span>
    </div>`;

    // 分析偏向
    html += `<div class="setting-item">
      <span class="label">交易偏向</span>
      <span class="value">${data.general.decision_stance}</span>
    </div>`;

    // AI 模型
    html += `<div class="setting-item">
      <span class="label">AI 模型</span>
      <span class="value">${data.provider.model}</span>
    </div>`;

    // API Key 状态
    html += `<div class="setting-item">
      <span class="label">API Key</span>
      <span class="value" style="${data.provider.api_key_configured ? 'color:#22c55e' : 'color:#ef4444'}">
        ${data.provider.api_key_configured ? "✅ 已配置" : "❌ 未配置"}
      </span>
    </div>`;

    html += '</div>';
    container.innerHTML = html;

    // 交易所表单提交
    const exForm = document.getElementById("exchangeForm");
    if (exForm) {
      exForm.addEventListener("submit", async function(e) {
        e.preventDefault();
        const fd = new FormData(this);
        await fetch("/api/settings/exchange", { method: "POST", body: fd });
        loadSettings();
      });
    }
  } catch(err) {
    container.innerHTML = `<div class="empty-state">加载失败: ${err.message}</div>`;
  }
}

async function loadExchangeSetting() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    const ex = data.general.last_ccxt_exchange;
    const sel = document.getElementById("exchange");
    if (sel) sel.value = ex;
  } catch(_) {}
}
