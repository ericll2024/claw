const telegramForm = document.querySelector("#telegramForm");
const telegramEnabled = document.querySelector("#telegramEnabled");
const telegramToken = document.querySelector("#telegramToken");
const telegramChat = document.querySelector("#telegramChat");
const telegramState = document.querySelector("#telegramState");
const aiForm = document.querySelector("#aiForm");
const aiState = document.querySelector("#aiState");
const aiEnabled = document.querySelector("#aiEnabled");
const aiDefaultProvider = document.querySelector("#aiDefaultProvider");
const aiDeepseekApiBase = document.querySelector("#aiDeepseekApiBase");
const aiDeepseekApiKey = document.querySelector("#aiDeepseekApiKey");
const aiDeepseekModel = document.querySelector("#aiDeepseekModel");
const aiGeminiCliEnabled = document.querySelector("#aiGeminiCliEnabled");
const aiGeminiCliCommand = document.querySelector("#aiGeminiCliCommand");
const testDeepseekBtn = document.querySelector("#testDeepseekBtn");
const mfoodForm = document.querySelector("#mfoodForm");
const mfoodState = document.querySelector("#mfoodState");

const mfoodLoginStatusBadge = document.querySelector("#mfoodLoginStatusBadge");
const mfoodTokenStatusBadge = document.querySelector("#mfoodTokenStatusBadge");
const mfoodTokenInfo = document.querySelector("#mfoodTokenInfo");
const mfoodCurrentToken = document.querySelector("#mfoodCurrentToken");
const checkMFoodTokenBtn = document.querySelector("#checkMFoodTokenBtn");
const loginMFoodBtn = document.querySelector("#loginMFoodBtn");

const mfoodFields = {
  login: {
    account: "#mfoodLoginAccount",
    password_md5: "#mfoodLoginPasswordMd5",
  },
  shence: {
    api_url: "#mfoodShenceApiUrl",
    sensors_api_key: "#mfoodShenceApiKey",
    sensors_project: "#mfoodShenceProject",
  },
  order_monitor: {
    takeout_threshold: "#mfoodTakeoutThreshold",
    market_threshold: "#mfoodMarketThreshold",
  },
};

async function api(path, options = {}) {
  const token = localStorage.getItem("token");
  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const response = await fetch(path, {
    ...options,
    headers,
  });
  if (response.status === 401) {
    localStorage.removeItem("token");
    window.location.href = "/login";
    return new Promise(() => {});
  }
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

async function loadTelegram() {
  const payload = await api("/api/settings/telegram");
  const settings = payload.settings;
  telegramEnabled.checked = Boolean(settings.enabled);
  telegramChat.value = settings.chat_id || "";
  telegramToken.value = "";
  telegramState.textContent = settings.configured ? "已配置" : "未配置";
  telegramState.className = settings.configured ? "badge success" : "badge";
}

async function loadAiSettings() {
  const payload = await api("/api/settings/ai");
  const settings = payload.settings;
  aiEnabled.checked = Boolean(settings.enabled);
  aiDefaultProvider.value = settings.default_provider || "deepseek";
  aiDeepseekApiBase.value = settings.deepseek_api_base || "";
  aiDeepseekApiKey.value = "";
  aiDeepseekModel.value = settings.deepseek_model || "deepseek-chat";
  aiGeminiCliEnabled.checked = Boolean(settings.gemini_cli_enabled);
  aiGeminiCliCommand.value = settings.gemini_cli_command || "gemini";
  const configured = settings.deepseek_api_key_configured || settings.gemini_cli_enabled;
  aiState.textContent = configured ? "已配置" : "未配置";
  aiState.className = configured ? "badge success" : "badge";
}

async function loadMFood() {
  const payload = await api("/api/settings/mfood");
  const settings = payload.settings;
  let configuredCount = 0;
  for (const [section, fields] of Object.entries(mfoodFields)) {
    if (settings[section]?.configured) configuredCount += 1;
    for (const [field, selector] of Object.entries(fields)) {
      const input = document.querySelector(selector);
      if (input.type === "password") {
        input.value = "";
      } else {
        input.value = settings[section]?.[field] || "";
      }
    }
  }
  mfoodState.textContent = `${configuredCount}/3`;
  mfoodState.className = configuredCount === 3 ? "badge success" : configuredCount > 0 ? "badge running" : "badge";

  if (settings.login?.token_configured) {
    mfoodLoginStatusBadge.textContent = "已登录";
    mfoodLoginStatusBadge.className = "badge success";
    mfoodTokenInfo.style.display = "block";
    mfoodCurrentToken.textContent = settings.login.token;
  } else {
    mfoodLoginStatusBadge.textContent = "未登录";
    mfoodLoginStatusBadge.className = "badge";
    mfoodTokenInfo.style.display = "none";
    mfoodCurrentToken.textContent = "";
  }
}



function showToast(message, type = "success") {
  let container = document.querySelector(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.classList.add("show"), 10);
  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

function showError(error) {
  showToast(error.message || error, "error");
}

telegramForm.addEventListener("submit", (event) => {
  event.preventDefault();
  api("/api/settings/telegram", {
    method: "POST",
    body: JSON.stringify({
      enabled: telegramEnabled.checked,
      bot_token: telegramToken.value.trim(),
      chat_id: telegramChat.value.trim(),
    }),
  })
    .then(() => {
      telegramToken.value = "";
      showToast("Telegram 配置保存成功", "success");
      return loadTelegram();
    })
    .catch(showError);
});

aiForm.addEventListener("submit", (event) => {
  event.preventDefault();
  api("/api/settings/ai", {
    method: "POST",
    body: JSON.stringify({
      enabled: aiEnabled.checked,
      default_provider: aiDefaultProvider.value,
      deepseek_api_base: aiDeepseekApiBase.value.trim(),
      deepseek_api_key: aiDeepseekApiKey.value.trim(),
      deepseek_model: aiDeepseekModel.value.trim(),
      gemini_cli_enabled: aiGeminiCliEnabled.checked,
      gemini_cli_command: aiGeminiCliCommand.value.trim(),
    }),
  })
    .then(() => {
      aiDeepseekApiKey.value = "";
      showToast("AI 配置保存成功", "success");
      return loadAiSettings();
    })
    .catch(showError);
});

testDeepseekBtn.addEventListener("click", async () => {
  testDeepseekBtn.disabled = true;
  const originalText = testDeepseekBtn.textContent;
  testDeepseekBtn.textContent = "测试中...";
  try {
    const payload = await api("/api/settings/ai/test", {
      method: "POST",
      body: JSON.stringify({
        deepseek_api_base: aiDeepseekApiBase.value.trim(),
        deepseek_api_key: aiDeepseekApiKey.value.trim(),
        deepseek_model: aiDeepseekModel.value.trim(),
      }),
    });
    const reply = payload.result?.reply || "";
    showToast(`DeepSeek 返回: ${reply || "(空回复)"}`, "success");
  } catch (err) {
    showError(err);
  } finally {
    testDeepseekBtn.disabled = false;
    testDeepseekBtn.textContent = originalText;
  }
});

const mfoodLoginForm = document.querySelector("#mfoodLoginForm");
const mfoodShenceForm = document.querySelector("#mfoodShenceForm");
const mfoodMonitorForm = document.querySelector("#mfoodMonitorForm");

mfoodLoginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const payload = {
    login: {
      account: document.querySelector("#mfoodLoginAccount").value.trim(),
      password_md5: document.querySelector("#mfoodLoginPasswordMd5").value.trim(),
    }
  };
  api("/api/settings/mfood", {
    method: "POST",
    body: JSON.stringify(payload),
  })
    .then(() => {
      showToast("mFood 登录配置保存成功", "success");
      return loadMFood();
    })
    .catch(showError);
});



mfoodShenceForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const payload = {
    shence: {
      api_url: document.querySelector("#mfoodShenceApiUrl").value.trim(),
      sensors_api_key: document.querySelector("#mfoodShenceApiKey").value.trim(),
      sensors_project: document.querySelector("#mfoodShenceProject").value.trim(),
    }
  };
  api("/api/settings/mfood", {
    method: "POST",
    body: JSON.stringify(payload),
  })
    .then(() => {
      showToast("mFood 神策配置保存成功", "success");
      return loadMFood();
    })
    .catch(showError);
});

mfoodMonitorForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const payload = {
    order_monitor: {
      takeout_threshold: document.querySelector("#mfoodTakeoutThreshold").value.trim(),
      market_threshold: document.querySelector("#mfoodMarketThreshold").value.trim(),
    }
  };
  api("/api/settings/mfood", {
    method: "POST",
    body: JSON.stringify(payload),
  })
    .then(() => {
      showToast("mFood 订单对账配置保存成功", "success");
      return loadMFood();
    })
    .catch(showError);
});

checkMFoodTokenBtn.addEventListener("click", async () => {
  checkMFoodTokenBtn.disabled = true;
  mfoodTokenStatusBadge.textContent = "检测中...";
  mfoodTokenStatusBadge.className = "badge running";
  try {
    const res = await api("/api/settings/mfood/check", { method: "POST" });
    if (res.ok) {
      mfoodTokenStatusBadge.textContent = `有效 (${res.status})`;
      mfoodTokenStatusBadge.className = "badge success";
      showToast("Token 有效", "success");
    } else {
      mfoodTokenStatusBadge.textContent = `无效 (${res.status})`;
      mfoodTokenStatusBadge.className = "badge failed";
      showToast(`Token 无效: ${res.status}`, "error");
    }
  } catch (err) {
    mfoodTokenStatusBadge.textContent = "检测失败";
    mfoodTokenStatusBadge.className = "badge failed";
    showError(err);
  } finally {
    checkMFoodTokenBtn.disabled = false;
  }
});

loginMFoodBtn.addEventListener("click", async () => {
  if (!confirm("确定要启动浏览器进行手动登录吗？这可能需要几十秒钟。")) {
    return;
  }
  loginMFoodBtn.disabled = true;
  loginMFoodBtn.textContent = "正在登录...";
  mfoodTokenStatusBadge.textContent = "获取中...";
  mfoodTokenStatusBadge.className = "badge running";
  try {
    const res = await api("/api/settings/mfood/login", { method: "POST" });
    if (res.ok) {
      showToast("手动登录成功，Token 已保存", "success");
      await loadMFood();
      // Verify the new token automatically
      checkMFoodTokenBtn.click();
    } else {
      showToast(`登录失败: ${res.error}`, "error");
    }
  } catch (err) {
    showError(err);
  } finally {
    loginMFoodBtn.disabled = false;
    loginMFoodBtn.textContent = "手动登录";
  }
});

// Telegram 消息監聽模態彈窗及輪詢邏輯
const openListenerBtn = document.querySelector("#openListenerBtn");
const listenerModal = document.querySelector("#listenerModal");
const closeModalBtn = document.querySelector("#closeModalBtn");

const listenerBadge = document.querySelector("#listenerBadge");
const toggleListenerBtn = document.querySelector("#toggleListenerBtn");
const pollOnceBtn = document.querySelector("#pollOnceBtn");
const listenerBotUser = document.querySelector("#listenerBotUser");
const listenerLastPoll = document.querySelector("#listenerLastPoll");
const listenerErrorContainer = document.querySelector("#listenerErrorContainer");
const listenerErrorText = document.querySelector("#listenerErrorText");
const updatesList = document.querySelector("#updatesList");
const aiJobsList = document.querySelector("#aiJobsList");

let listenerPollInterval = null;
let isListenerRunning = false;
const expandedUpdateIds = new Set();

// 打開彈窗
openListenerBtn.addEventListener("click", () => {
  listenerModal.classList.add("show");
  loadListener();
});

// 關閉彈窗
function closeListenerModal() {
  listenerModal.classList.remove("show");
  stopStatusPolling();
}

closeModalBtn.addEventListener("click", closeListenerModal);

// 點擊彈窗外部（遮罩層）也可關閉
listenerModal.addEventListener("click", (event) => {
  if (event.target === listenerModal) {
    closeListenerModal();
  }
});

async function loadListener() {
  try {
    const [listenerPayload, jobsPayload] = await Promise.all([
      api("/api/telegram/listener"),
      api("/api/telegram/ai-jobs"),
    ]);
    updateListenerUI(listenerPayload.listener);
    renderAiJobs(jobsPayload.jobs || []);
  } catch (err) {
    updatesList.innerHTML = `<div class="empty" style="color: var(--red);">加載失敗: ${escapeHtml(err.message)}</div>`;
    aiJobsList.innerHTML = `<div class="empty" style="color: var(--red);">加載失敗: ${escapeHtml(err.message)}</div>`;
  }
}

function updateListenerUI(listener) {
  isListenerRunning = Boolean(listener.running);
  
  listenerBadge.textContent = listener.running ? "運行中" : "未運行";
  listenerBadge.className = listener.running ? "badge success" : "badge";
  
  toggleListenerBtn.textContent = listener.running ? "停止監聽" : "開啟監聽";
  toggleListenerBtn.className = listener.running ? "button" : "button primary";
  
  listenerBotUser.textContent = listener.bot_username ? `@${listener.bot_username}` : "未獲取";
  
  if (listener.last_poll_at) {
    const d = new Date(listener.last_poll_at);
    listenerLastPoll.textContent = isNaN(d.getTime()) ? listener.last_poll_at : d.toLocaleString();
  } else {
    listenerLastPoll.textContent = "無";
  }
  
  if (listener.last_error) {
    listenerErrorText.textContent = listener.last_error;
    listenerErrorContainer.style.display = "block";
  } else {
    listenerErrorContainer.style.display = "none";
  }
  
  renderUpdates(listener.updates || []);
  
  if (listener.running) {
    startStatusPolling();
  } else {
    stopStatusPolling();
  }
}

function renderUpdates(updates) {
  if (updates.length === 0) {
    updatesList.innerHTML = '<div class="empty">暫無消息</div>';
    return;
  }
  
  updatesList.innerHTML = updates.map(update => {
    const dateStr = update.received_at ? new Date(update.received_at).toLocaleString() : "未知時間";
    const updateId = update.update_id;
    const isMention = update.is_mention ? 'mention' : '';
    const textContent = update.text || '[空內容]';
    const rawJsonStr = JSON.stringify(update.raw, null, 2);
    
    const isExpanded = expandedUpdateIds.has(updateId);
    const displayStyle = isExpanded ? 'block' : 'none';
    
    return `
      <div class="update-item ${isMention}">
        <div class="update-item-header">
          <span class="update-item-sender">來自: ${escapeHtml(update.from_name || '未知')} (ID: ${update.from_id || '無'})</span>
          <span>${dateStr}</span>
        </div>
        <div class="update-item-text">${escapeHtml(textContent)}</div>
        <div class="update-item-meta">
          <span>對話: ${escapeHtml(update.chat_title || '個人對話')} (ID: ${update.chat_id}) | 類型: ${update.chat_type || '未知'}</span>
          <button class="update-item-raw-btn" onclick="toggleRaw(${updateId})">查看原始 JSON</button>
        </div>
        <pre id="raw-${updateId}" class="update-item-raw-content" style="display: ${displayStyle};">${escapeHtml(rawJsonStr)}</pre>
      </div>
    `;
  }).join('');
}

function aiJobStatusLabel(status) {
  switch (status) {
    case "queued":
      return "排队中";
    case "running":
      return "处理中";
    case "rolled_back":
      return "已回滚";
    case "rerun_success":
      return "已成功重跑";
    case "failed":
      return "失败";
    default:
      return status || "未知";
  }
}

function renderAiJobs(jobs) {
  if (!jobs.length) {
    aiJobsList.innerHTML = '<div class="empty">暂无 AI 作业</div>';
    return;
  }
  aiJobsList.innerHTML = jobs.map((job) => {
    const createdAt = job.created_at ? new Date(job.created_at).toLocaleString() : "未知时间";
    const touched = (job.files_touched || []).length ? job.files_touched.join(", ") : "无";
    return `
      <div class="update-item">
        <div class="update-item-header">
          <span class="update-item-sender">${escapeHtml(job.task_id || "未知任务")}</span>
          <span>${createdAt}</span>
        </div>
        <div class="update-item-text">${escapeHtml(job.request_text || "无请求内容")}</div>
        <div class="update-item-meta" style="align-items: flex-start; flex-direction: column; gap: 6px;">
          <span>状态: ${escapeHtml(aiJobStatusLabel(job.status))} | Provider: ${escapeHtml(job.provider || "-")}</span>
          <span>修改文件: ${escapeHtml(touched)}</span>
          <span>验证: ${escapeHtml(job.verification_status || "未执行")}</span>
          ${job.reply_text ? `<span>回复: ${escapeHtml(job.reply_text)}</span>` : ""}
          <div style="display: flex; gap: 8px;">
            <button class="button" data-retry-ai-job="${job.id}">重试</button>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
}

window.toggleRaw = function(updateId) {
  const el = document.getElementById(`raw-${updateId}`);
  if (el) {
    if (el.style.display === 'none') {
      el.style.display = 'block';
      expandedUpdateIds.add(updateId);
    } else {
      el.style.display = 'none';
      expandedUpdateIds.delete(updateId);
    }
  }
};

function startStatusPolling() {
  if (listenerPollInterval) return;
  listenerPollInterval = setInterval(async () => {
    // 只有在彈窗顯示的情況下才進行輪詢
    if (!listenerModal.classList.contains("show")) {
      stopStatusPolling();
      return;
    }
    try {
      const payload = await api("/api/telegram/listener");
      isListenerRunning = Boolean(payload.listener.running);
      listenerBadge.textContent = payload.listener.running ? "運行中" : "未運行";
      listenerBadge.className = payload.listener.running ? "badge success" : "badge";
      toggleListenerBtn.textContent = payload.listener.running ? "停止監聽" : "開啟監聽";
      toggleListenerBtn.className = payload.listener.running ? "button" : "button primary";
      listenerBotUser.textContent = payload.listener.bot_username ? `@${payload.listener.bot_username}` : "未獲取";
      if (payload.listener.last_poll_at) {
        const d = new Date(payload.listener.last_poll_at);
        listenerLastPoll.textContent = isNaN(d.getTime()) ? payload.listener.last_poll_at : d.toLocaleString();
      } else {
        listenerLastPoll.textContent = "無";
      }
      if (payload.listener.last_error) {
        listenerErrorText.textContent = payload.listener.last_error;
        listenerErrorContainer.style.display = "block";
      } else {
        listenerErrorContainer.style.display = "none";
      }
      renderUpdates(payload.listener.updates || []);
      const jobsPayload = await api("/api/telegram/ai-jobs");
      renderAiJobs(jobsPayload.jobs || []);
      if (!payload.listener.running) {
        stopStatusPolling();
      }
    } catch (err) {
      console.error("輪詢 Telegram 監聽器狀態失敗:", err);
    }
  }, 3000);
}

function stopStatusPolling() {
  if (listenerPollInterval) {
    clearInterval(listenerPollInterval);
    listenerPollInterval = null;
  }
}

toggleListenerBtn.addEventListener("click", async () => {
  toggleListenerBtn.disabled = true;
  try {
    const payload = await api("/api/telegram/listener", {
      method: "POST",
      body: JSON.stringify({ enabled: !isListenerRunning }),
    });
    updateListenerUI(payload.listener);
  } catch (err) {
    showError(err);
  } finally {
    toggleListenerBtn.disabled = false;
  }
});

pollOnceBtn.addEventListener("click", async () => {
  pollOnceBtn.disabled = true;
  try {
    const payload = await api("/api/telegram/listener/poll", {
      method: "POST",
    });
    updateListenerUI(payload.listener);
    const jobsPayload = await api("/api/telegram/ai-jobs");
    renderAiJobs(jobsPayload.jobs || []);
  } catch (err) {
    showError(err);
  } finally {
    pollOnceBtn.disabled = false;
  }
});

listenerModal.addEventListener("click", async (event) => {
  const retryButton = event.target.closest("[data-retry-ai-job]");
  if (!retryButton) {
    return;
  }
  retryButton.disabled = true;
  try {
    await api(`/api/telegram/ai-jobs/${retryButton.dataset.retryAiJob}/retry`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    showToast("AI 作业已重试", "success");
    await loadListener();
  } catch (err) {
    showError(err);
  } finally {
    retryButton.disabled = false;
  }
});

Promise.all([loadTelegram(), loadAiSettings(), loadMFood()]).catch(showError);

const logoutBtn = document.querySelector("#logoutBtn");
if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST" });
      localStorage.removeItem("token");
      window.location.href = "/login";
    } catch (err) {
      console.error("Logout failed:", err);
      localStorage.removeItem("token");
      window.location.href = "/login";
    }
  });
}
