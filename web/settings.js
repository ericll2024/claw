const telegramForm = document.querySelector("#telegramForm");
const telegramEnabled = document.querySelector("#telegramEnabled");
const telegramToken = document.querySelector("#telegramToken");
const telegramChat = document.querySelector("#telegramChat");
const telegramState = document.querySelector("#telegramState");
const mfoodForm = document.querySelector("#mfoodForm");
const mfoodState = document.querySelector("#mfoodState");

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
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
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

  const tokenStatus = document.querySelector("#mfoodTokenStatus");
  if (tokenStatus) {
    if (settings.login?.token_configured) {
      tokenStatus.textContent = `已登录 / 已获取 (${settings.login.token_masked})`;
      tokenStatus.style.color = "var(--green)";
    } else {
      tokenStatus.textContent = "未登录 / 未获取";
      tokenStatus.style.color = "var(--muted)";
    }
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

const mfoodLoginBtn = document.querySelector("#mfoodLoginBtn");
if (mfoodLoginBtn) {
  mfoodLoginBtn.addEventListener("click", () => {
    mfoodLoginBtn.disabled = true;
    mfoodLoginBtn.textContent = "正在登录...";
    api("/api/mfood/login", { method: "POST" })
      .then((res) => {
        showToast("登录成功，Token 已刷新并保存", "success");
        loadMFood();
      })
      .catch((err) => {
        showError(err);
      })
      .finally(() => {
        mfoodLoginBtn.disabled = false;
        mfoodLoginBtn.textContent = "立即登录 / 刷新 Token";
      });
  });
}

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
    const payload = await api("/api/telegram/listener");
    updateListenerUI(payload.listener);
  } catch (err) {
    updatesList.innerHTML = `<div class="empty" style="color: var(--red);">加載失敗: ${escapeHtml(err.message)}</div>`;
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
  } catch (err) {
    showError(err);
  } finally {
    pollOnceBtn.disabled = false;
  }
});

Promise.all([loadTelegram(), loadMFood()]).catch(showError);
