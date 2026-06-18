const agentsList = document.querySelector("#agentsList");
const agentDetail = document.querySelector("#agentDetail");
const agentCount = document.querySelector("#agentCount");
const refreshBtn = document.querySelector("#refreshBtn");
const sidebarToggleBtn = document.querySelector("#sidebarToggleBtn");
const layoutContainer = document.querySelector(".layout");

const scheduleModal = document.querySelector("#scheduleModal");
const scheduleModalBody = document.querySelector("#scheduleModalBody");
const scheduleModalTitle = document.querySelector("#scheduleModalTitle");
const closeScheduleModalBtn = document.querySelector("#closeScheduleModalBtn");

const runConfirmModal = document.querySelector("#runConfirmModal");
const closeRunConfirmModalBtn = document.querySelector("#closeRunConfirmModalBtn");
const cancelRunBtn = document.querySelector("#cancelRunBtn");
const confirmRunBtn = document.querySelector("#confirmRunBtn");
const runSendToTelegram = document.querySelector("#runSendToTelegram");

let pendingRunTaskId = null;
let pendingRunButton = null;

const searchToggleBtn = document.querySelector("#searchToggleBtn");
const searchBarWrap = document.querySelector("#searchBarWrap");
const searchInput = document.querySelector("#searchInput");
let searchQuery = "";

let agents = [];
let selectedAgentId = "";
let selectedDetailTab = "runs";
let runLimitMode = "10";
let customRunLimit = "25";
let runsCache = {};
let editingAlias = false;
let loadingRunsKey = "";
const weekdayLabels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

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

function statusBadge(status, enabled = true) {
  if (!enabled) return `<span class="badge disabled">未启用</span>`;
  if (!status) return `<span class="badge">未运行</span>`;
  const label = status === "success" ? "成功" : status === "failed" ? "失败" : status === "pending" ? "待运行" : status;
  return `<span class="badge ${escapeHtml(status)}">${escapeHtml(label)}</span>`;
}

function formatDate(value) {
  if (!value) return "无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function renderAgents() {
  const filtered = agents.filter((agent) => {
    if (!searchQuery) return true;
    const nameMatch = agent.name.toLowerCase().includes(searchQuery);
    const descMatch = (agent.description || "").toLowerCase().includes(searchQuery);
    const folderMatch = agent.folder.toLowerCase().includes(searchQuery);
    return nameMatch || descMatch || folderMatch;
  });

  agentCount.textContent = `${filtered.length} 个任务`;
  agentsList.innerHTML = "";

  if (filtered.length === 0) {
    agentsList.innerHTML = `<div class="empty">无匹配的任务</div>`;
    return;
  }

  for (let i = 0; i < filtered.length; i++) {
    const agent = filtered[i];
    const isFirst = i === 0;
    const isLast = i === filtered.length - 1;

    const wrap = document.createElement("div");
    wrap.className = "agent-item-wrap";
    wrap.innerHTML = `
      <button class="agent-item${agent.id === selectedAgentId ? " active" : ""}" data-agent-id="${agent.id}">
        <div class="agent-main">
          <strong>${escapeHtml(agent.name)}</strong>
          <span>${escapeHtml(agent.alias ? `${agent.default_name} · ${agent.folder}` : agent.folder)}</span>
        </div>
        <div class="agent-meta">
          ${statusBadge(agent.status, agent.enabled_count > 0)}
          <span>${escapeHtml(agent.task_count)} 个子任务</span>
        </div>
      </button>
      <div class="agent-sort-actions">
        <button class="sort-btn up" data-action="move-up" data-agent-id="${agent.id}" title="上移"${isFirst ? " disabled" : ""}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="18 15 12 9 6 15"></polyline>
          </svg>
        </button>
        <button class="sort-btn down" data-action="move-down" data-agent-id="${agent.id}" title="下移"${isLast ? " disabled" : ""}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </button>
      </div>
    `;
    agentsList.appendChild(wrap);
  }
}

function renderAgentDetail() {
  const agent = agents.find((item) => item.id === selectedAgentId) || agents[0];
  if (!agent) {
    agentDetail.innerHTML = `<div class="empty">暂无任务</div>`;
    return;
  }
  selectedAgentId = agent.id;

  let headerHtml = "";
  if (editingAlias) {
    headerHtml = `
      <form class="inline-alias-form" data-alias-form>
        <input data-alias-input type="text" autocomplete="off" maxlength="80" value="${escapeHtml(agent.alias || "")}" placeholder="${escapeHtml(agent.default_name || agent.id)}" />
        <button class="button primary" type="submit">保存</button>
        <button class="button" type="button" data-action="cancel-edit-alias">取消</button>
      </form>
    `;
  } else {
    headerHtml = `
      <h2 class="detail-title">
        <span>${escapeHtml(agent.name)}</span>
        <button class="button edit-alias-btn" type="button" data-action="edit-alias">编辑别名</button>
      </h2>
    `;
  }

  agentDetail.innerHTML = `
    <div class="detail-head">
      <div class="detail-main-info">
        ${headerHtml}
        <p class="detail-desc">${escapeHtml(agent.description || "")}</p>
      </div>
      <div class="detail-stats">
        ${statusBadge(agent.status, agent.enabled_count > 0)}
        <span class="enabled-stat">
          <strong>${escapeHtml(agent.enabled_count)}</strong>
          <span>/ ${escapeHtml(agent.task_count)} 启用</span>
        </span>
        <span class="next-run-stat">下次 ${escapeHtml(formatDate(agent.next_run_at))}</span>
      </div>
    </div>
    <div class="detail-tabs" role="tablist" aria-label="任务详情">
      <button class="tab-button${selectedDetailTab === "runs" ? " active" : ""}" type="button" data-detail-tab="runs">最近运行结果</button>
      <button class="tab-button${selectedDetailTab === "tasks" ? " active" : ""}" type="button" data-detail-tab="tasks">任务列表</button>
    </div>
    <div class="detail-content">
      ${selectedDetailTab === "runs" ? renderRunsPanel(agent) : renderTaskList(agent)}
    </div>
  `;
  if (selectedDetailTab === "runs") {
    queueRunsLoad(agent.id);
  }
}

function renderTaskList(agent) {
  return `
    <div class="task-stack">
      ${agent.tasks.map(renderTaskCard).join("")}
    </div>
  `;
}

function renderRunsPanel(agent) {
  const key = runsCacheKey(agent.id);
  const cached = runsCache[key];
  const isLoading = loadingRunsKey === key;
  return `
    <section class="runs-panel">
      <form class="runs-toolbar" data-runs-limit-form>
        <div>
          <label>
            <span>显示条数</span>
            <select data-run-limit-mode>
              ${renderLimitOption("10", "最近 10 条")}
              ${renderLimitOption("20", "最近 20 条")}
              ${renderLimitOption("50", "最近 50 条")}
              ${renderLimitOption("100", "最近 100 条")}
              ${renderLimitOption("custom", "自定义")}
              ${renderLimitOption("all", "全部")}
            </select>
          </label>
        </div>
        <label class="${runLimitMode === "custom" ? "" : "hidden"}">
          <span>自定义条数</span>
          <input data-custom-run-limit type="number" min="1" step="1" value="${escapeHtml(customRunLimit)}" />
        </label>
        <button class="button" type="submit">${isLoading ? "加载中" : "应用"}</button>
        <button class="button" type="button" data-refresh-runs>刷新结果</button>
      </form>
      ${renderRunsTable(cached?.runs || [], isLoading)}
    </section>
  `;
}

function renderLimitOption(value, label) {
  return `<option value="${escapeHtml(value)}"${runLimitMode === value ? " selected" : ""}>${escapeHtml(label)}</option>`;
}

function renderRunsTable(runs, isLoading) {
  const sortedRuns = [...runs].sort(compareRunsDesc);
  if (isLoading && runs.length === 0) {
    return `<div class="empty">正在加载运行结果...</div>`;
  }
  if (sortedRuns.length === 0) {
    return `<div class="empty">暂无运行结果</div>`;
  }
  return `
    <div class="runs-table-wrap">
      <table class="runs-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>子任务</th>
            <th>状态</th>
            <th>触发</th>
            <th>耗时</th>
            <th>结果</th>
          </tr>
        </thead>
        <tbody>
          ${sortedRuns.map(renderRunRow).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function compareRunsDesc(left, right) {
  const leftTime = new Date(left.started_at || 0).getTime();
  const rightTime = new Date(right.started_at || 0).getTime();
  if (rightTime !== leftTime) return rightTime - leftTime;
  return Number(right.id || 0) - Number(left.id || 0);
}

function renderRunRow(run) {
  let triggerLabel = "手动";
  if (run.trigger_type === "schedule") {
    triggerLabel = "计划";
  } else if (run.trigger_type && run.trigger_type !== "manual") {
    triggerLabel = run.trigger_type;
  }
  return `
    <tr>
      <td>${escapeHtml(formatDate(run.started_at))}</td>
      <td>
        <strong>${escapeHtml(run.task_name || run.task_id)}</strong>
        <span>${escapeHtml(run.task_id)}</span>
      </td>
      <td>${statusBadge(run.status)}</td>
      <td>${escapeHtml(triggerLabel)}</td>
      <td>${escapeHtml(formatDuration(run.duration_ms))}</td>
      <td class="run-summary">${escapeHtml(run.summary || run.stderr || run.stdout || "无")}</td>
    </tr>
  `;
}

function formatDuration(value) {
  if (value === null || value === undefined || value === "") return "无";
  const ms = Number(value);
  if (Number.isNaN(ms)) return String(value);
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function resolvedRunLimit() {
  if (runLimitMode === "all") return "all";
  if (runLimitMode === "custom") {
    const parsed = Number.parseInt(customRunLimit, 10);
    return Number.isFinite(parsed) && parsed > 0 ? String(parsed) : "10";
  }
  return runLimitMode;
}

function runsCacheKey(agentId) {
  return `${agentId}:${resolvedRunLimit()}`;
}

function queueRunsLoad(agentId, force = false) {
  const key = runsCacheKey(agentId);
  if (!force && (runsCache[key] || loadingRunsKey === key)) return;
  loadAgentRuns(agentId, key).catch((error) => {
    loadingRunsKey = "";
    alert(error.message);
    renderAgentDetail();
  });
}

async function loadAgentRuns(agentId, key) {
  loadingRunsKey = key;
  renderAgentDetail();
  const payload = await api(`/api/task-groups/${encodeURIComponent(agentId)}/runs?limit=${encodeURIComponent(resolvedRunLimit())}`);
  runsCache[key] = payload;
  if (loadingRunsKey === key) loadingRunsKey = "";
  if (selectedAgentId === agentId && selectedDetailTab === "runs") {
    renderAgentDetail();
  }
}

async function saveAgentAlias(agentId, alias, button) {
  button.disabled = true;
  button.textContent = "保存中";
  try {
    await api(`/api/task-groups/${encodeURIComponent(agentId)}/alias`, {
      method: "POST",
      body: JSON.stringify({ alias }),
    });
    editingAlias = false;
    await loadTasks();
  } finally {
    button.disabled = false;
    button.textContent = "保存";
  }
}

function renderTaskCard(task) {
  const run = task.last_run;
  let tgGroup = "未配置";
  if (task.telegram_chat_id) {
    if (task.telegram_group_name) {
      tgGroup = `群名：${task.telegram_group_name} 群id：${task.telegram_chat_id}`;
    } else {
      tgGroup = `群id：${task.telegram_chat_id}`;
    }
  }
  return `
    <article class="task-card">
      <div class="task-top">
        <div>
          <div class="task-name-row">
            <div class="task-name">${escapeHtml(task.name)}</div>
            ${task.alert ? `<span class="alert-tag">${escapeHtml(task.alert_label || "警报")}</span>` : ""}
          </div>
          <div class="task-desc">${escapeHtml(task.description || "")}</div>
        </div>
        <div class="task-actions" style="display: flex; gap: 6px; align-items: center;">
          <button class="button" data-edit-schedule="${escapeHtml(task.id)}">编辑</button>
          ${task.enabled
            ? `<button class="button" data-toggle-enabled="${escapeHtml(task.id)}" data-enabled="false">停止</button>`
            : `<button class="button primary" data-toggle-enabled="${escapeHtml(task.id)}" data-enabled="true">启动</button>`
          }
          <button class="button" data-run="${escapeHtml(task.id)}">运行一次</button>
        </div>
      </div>
      <div class="task-grid">
        <div>
          <span class="label">时间</span>
          <strong>${escapeHtml(task.schedule_label)}</strong>
        </div>
        <div>
          <span class="label">下次</span>
          <strong>${escapeHtml(formatDate(task.next_run_at))}</strong>
        </div>
        <div>
          <span class="label">状态</span>
          ${task.enabled
            ? `<span class="badge success">已启动</span>`
            : `<span class="badge disabled">未启动</span>`
          }
        </div>
        <div>
          <span class="label">最近</span>
          <strong>${escapeHtml(run ? formatDate(run.started_at) : "无")}</strong>
        </div>
        <div>
          <span class="label">TG 通知群</span>
          <strong title="${escapeHtml(tgGroup)}">${escapeHtml(tgGroup)}</strong>
        </div>
      </div>
    </article>
  `;
}

function renderScheduleEditor(task) {
  const schedule = task.schedule || {};
  const times = schedule.times || [];
  return `
    <form class="schedule-form" data-schedule-form data-task-id="${escapeHtml(task.id)}" style="display: flex; flex-direction: column; gap: 12px; margin-top: 0;">
      <div class="schedule-row" style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px;">
        <label>
          <span>范围</span>
          <select data-schedule-mode>
            <option value="long_term"${schedule.mode === "date_range" ? "" : " selected"}>长期</option>
            <option value="date_range"${schedule.mode === "date_range" ? " selected" : ""}>日期范围</option>
          </select>
        </label>
        <label>
          <span>开始日期</span>
          <input data-schedule-start type="date" value="${escapeHtml(schedule.start_date || "")}"${schedule.mode === "date_range" ? "" : " disabled"} />
        </label>
        <label>
          <span>结束日期</span>
          <input data-schedule-end type="date" value="${escapeHtml(schedule.end_date || "")}"${schedule.mode === "date_range" ? "" : " disabled"} />
        </label>
      </div>
      <fieldset class="weekday-fieldset" style="border: 1px solid var(--line); border-radius: 6px; padding: 10px; margin: 0;">
        <legend style="padding: 0 6px; font-size: 12px; font-weight: 600; color: var(--muted);">执行星期</legend>
        <div class="weekday-list" style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;">
          ${weekdayLabels.map((label, index) => `
            <label class="check-label" style="display: flex; align-items: center; gap: 4px; font-size: 13px; cursor: pointer;">
              <input data-schedule-weekday type="checkbox" value="${index}"${(schedule.weekdays || []).includes(index) ? " checked" : ""} style="margin: 0;" />
              <span>${escapeHtml(label)}</span>
            </label>
          `).join("")}
        </div>
      </fieldset>
      <div class="schedule-times-section">
        <span class="schedule-times-title">执行时间</span>
        <div class="schedule-times-list">
          ${(times.length > 0 ? times : [""]).map((time) => `
            <div class="schedule-time-item">
              <input data-schedule-time type="time" value="${escapeHtml(time)}" required style="width: 100%;" />
              <button type="button" class="delete-time-btn" data-delete-time title="删除">&times;</button>
            </div>
          `).join("")}
        </div>
        <button type="button" class="button add-time-btn" data-add-time>+ 添加时间</button>
      </div>
      <div style="border-top: 1px solid var(--line); padding-top: 12px; margin-top: 4px;">
        <strong style="font-size: 13px; color: var(--text); display: block; margin-bottom: 8px;">通知配置 (Telegram)</strong>
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <label style="display: flex; flex-direction: column; gap: 4px;">
            <span>专属 Chat ID</span>
            <input data-schedule-telegram-chat-id type="text" autocomplete="off" placeholder="留空则使用全局 Chat ID" value="${escapeHtml(schedule.telegram_chat_id || "")}" />
          </label>
        </div>
      </div>
      <div class="schedule-actions" style="display: flex; flex-wrap: wrap; align-items: center; gap: 8px; justify-content: flex-end; border-top: 1px solid var(--line); padding-top: 12px; margin-top: 8px;">
        <button class="button primary" type="submit">保存计划</button>
        <button class="button" type="button" data-reset-schedule="${escapeHtml(task.id)}">恢复默认</button>
        <span class="small" style="font-size: 11px; color: var(--muted); width: 100%; text-align: left;">当前：${escapeHtml(task.schedule_label)}</span>
      </div>
    </form>
  `;
}

async function loadTasks() {
  refreshBtn.disabled = true;
  try {
    const payload = await api("/api/tasks");
    agents = payload.agents || groupTasks(payload.tasks || []);
    if (!selectedAgentId || !agents.some((agent) => agent.id === selectedAgentId)) {
      selectedAgentId = agents[0]?.id || "";
    }
    renderAgents();
    renderAgentDetail();
  } finally {
    refreshBtn.disabled = false;
  }
}

function groupTasks(tasks) {
  const byGroup = new Map();
  for (const task of tasks) {
    if (!byGroup.has(task.group)) byGroup.set(task.group, []);
    byGroup.get(task.group).push(task);
  }
  return Array.from(byGroup, ([id, groupedTasks]) => ({
    id,
    name: id,
    folder: id,
    description: "",
    task_count: groupedTasks.length,
    enabled_count: groupedTasks.filter((task) => task.enabled).length,
    status: "",
    schedule_summary: groupedTasks.map((task) => task.schedule_label).join(" / "),
    next_run_at: groupedTasks.find((task) => task.next_run_at)?.next_run_at || null,
    tasks: groupedTasks,
  }));
}

async function runTask(taskId, button, sendToTelegram = false) {
  button.disabled = true;
  button.textContent = "运行中...";
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/run`, {
      method: "POST",
      body: JSON.stringify({ send_to_telegram: sendToTelegram }),
    });
    await loadTasks();
  } finally {
    button.disabled = false;
    button.textContent = "运行一次";
  }
}

function promptRunTask(taskId, button) {
  pendingRunTaskId = taskId;
  pendingRunButton = button;

  const allTasks = agents.flatMap(a => a.tasks || []);
  const task = allTasks.find(t => t.id === taskId);
  const taskName = task ? task.name : taskId;

  document.querySelector("#runConfirmModalTitle").textContent = `确认运行 - ${taskName}`;
  runSendToTelegram.checked = true;
  runConfirmModal.classList.add("show");
}

function closeRunConfirmModal() {
  runConfirmModal.classList.remove("show");
  pendingRunTaskId = null;
  pendingRunButton = null;
}

closeRunConfirmModalBtn.addEventListener("click", closeRunConfirmModal);
cancelRunBtn.addEventListener("click", closeRunConfirmModal);

confirmRunBtn.addEventListener("click", () => {
  const taskId = pendingRunTaskId;
  const button = pendingRunButton;
  const sendToTelegram = runSendToTelegram.checked;
  closeRunConfirmModal();
  if (taskId && button) {
    runTask(taskId, button, sendToTelegram).catch((error) => {
      alert(error.message);
      loadTasks();
    });
  }
});

async function toggleTaskEnabled(taskId, enabled, button) {
  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = enabled ? "启动中" : "停止中";
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/enabled`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    });
    await loadTasks();
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function openScheduleModal(taskId) {
  const agent = agents.find((item) => item.id === selectedAgentId) || agents[0];
  if (!agent) return;
  const task = agent.tasks.find((t) => t.id === taskId);
  if (!task) return;

  scheduleModalTitle.textContent = `计划设置 - ${task.name}`;
  scheduleModalBody.innerHTML = renderScheduleEditor(task);
  scheduleModal.classList.add("show");
}

function closeScheduleModal() {
  scheduleModal.classList.remove("show");
  scheduleModalBody.innerHTML = "";
}

async function saveTaskSchedule(taskId, payload, button) {
  button.disabled = true;
  button.textContent = "保存中";
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/schedule`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    runsCache = {};
    closeScheduleModal();
    await loadTasks();
  } finally {
    button.disabled = false;
    button.textContent = "保存计划";
  }
}

async function resetTaskSchedule(taskId, button) {
  button.disabled = true;
  button.textContent = "恢复中";
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/schedule`, {
      method: "POST",
      body: JSON.stringify({ reset: true }),
    });
    runsCache = {};
    closeScheduleModal();
    await loadTasks();
  } finally {
    button.disabled = false;
    button.textContent = "恢复默认";
  }
}

function collectSchedulePayload(form) {
  const mode = form.querySelector("[data-schedule-mode]").value;
  return {
    mode,
    start_date: form.querySelector("[data-schedule-start]").value,
    end_date: form.querySelector("[data-schedule-end]").value,
    weekdays: Array.from(form.querySelectorAll("[data-schedule-weekday]:checked")).map((input) => Number(input.value)),
    times: Array.from(form.querySelectorAll("[data-schedule-time]")).map((input) => input.value.trim()).filter(Boolean),
    telegram_chat_id: form.querySelector("[data-schedule-telegram-chat-id]")?.value.trim() || "",
  };
}

function updateScheduleMode(form) {
  const mode = form.querySelector("[data-schedule-mode]").value;
  const disabled = mode !== "date_range";
  form.querySelector("[data-schedule-start]").disabled = disabled;
  form.querySelector("[data-schedule-end]").disabled = disabled;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

refreshBtn.addEventListener("click", loadTasks);

agentsList.addEventListener("click", (event) => {
  const sortBtn = event.target.closest("button[data-action]");
  if (sortBtn) {
    event.stopPropagation();
    const action = sortBtn.dataset.action;
    const agentId = sortBtn.dataset.agentId;
    moveAgent(agentId, action);
    return;
  }

  const button = event.target.closest("button.agent-item");
  if (!button) return;
  selectedAgentId = button.dataset.agentId;
  selectedDetailTab = "runs";
  editingAlias = false;
  renderAgents();
  renderAgentDetail();
});

async function moveAgent(agentId, action) {
  const idx = agents.findIndex(a => a.id === agentId);
  if (idx === -1) return;

  if (action === "move-up" && idx > 0) {
    const temp = agents[idx];
    agents[idx] = agents[idx - 1];
    agents[idx - 1] = temp;
  } else if (action === "move-down" && idx < agents.length - 1) {
    const temp = agents[idx];
    agents[idx] = agents[idx + 1];
    agents[idx + 1] = temp;
  } else {
    return;
  }

  renderAgents();

  try {
    await api("/api/agents/reorder", {
      method: "POST",
      body: JSON.stringify({ order: agents.map(a => a.id) })
    });
  } catch (error) {
    console.error("Failed to save agent order:", error);
    loadTasks();
  }
}

agentDetail.addEventListener("click", (event) => {
  const editAliasBtn = event.target.closest("button[data-action='edit-alias']");
  if (editAliasBtn) {
    editingAlias = true;
    renderAgentDetail();
    return;
  }

  const cancelEditAliasBtn = event.target.closest("button[data-action='cancel-edit-alias']");
  if (cancelEditAliasBtn) {
    editingAlias = false;
    renderAgentDetail();
    return;
  }

  const tabButton = event.target.closest("button[data-detail-tab]");
  if (tabButton) {
    selectedDetailTab = tabButton.dataset.detailTab;
    renderAgentDetail();
    return;
  }

  const refreshRunsButton = event.target.closest("button[data-refresh-runs]");
  if (refreshRunsButton) {
    delete runsCache[runsCacheKey(selectedAgentId)];
    queueRunsLoad(selectedAgentId, true);
    renderAgentDetail();
    return;
  }

  const editBtn = event.target.closest("button[data-edit-schedule]");
  if (editBtn) {
    openScheduleModal(editBtn.dataset.editSchedule);
    return;
  }

  const toggleEnabledBtn = event.target.closest("button[data-toggle-enabled]");
  if (toggleEnabledBtn) {
    const taskId = toggleEnabledBtn.dataset.toggleEnabled;
    const enabled = toggleEnabledBtn.dataset.enabled === "true";
    toggleTaskEnabled(taskId, enabled, toggleEnabledBtn).catch((error) => {
      alert(error.message);
      loadTasks();
    });
    return;
  }

  const button = event.target.closest("button[data-run]");
  if (!button) return;
  promptRunTask(button.dataset.run, button);
});

agentDetail.addEventListener("change", (event) => {
  const select = event.target.closest("[data-run-limit-mode]");
  if (!select) return;
  runLimitMode = select.value;
  if (runLimitMode !== "custom") {
    delete runsCache[runsCacheKey(selectedAgentId)];
    queueRunsLoad(selectedAgentId, true);
  }
  renderAgentDetail();
});

agentDetail.addEventListener("submit", (event) => {
  const runsForm = event.target.closest("form[data-runs-limit-form]");
  if (runsForm) {
    event.preventDefault();
    const input = runsForm.querySelector("[data-custom-run-limit]");
    if (input) customRunLimit = input.value.trim() || "10";
    delete runsCache[runsCacheKey(selectedAgentId)];
    queueRunsLoad(selectedAgentId, true);
    return;
  }

  const form = event.target.closest("form[data-alias-form]");
  if (!form) return;
  event.preventDefault();
  const input = form.querySelector("[data-alias-input]");
  const button = form.querySelector("button[type='submit']");
  saveAgentAlias(selectedAgentId, input.value.trim(), button).catch((error) => {
    alert(error.message);
    loadTasks();
  });
});

// 弹窗事件监听
if (closeScheduleModalBtn) {
  closeScheduleModalBtn.addEventListener("click", closeScheduleModal);
}
if (scheduleModal) {
  scheduleModal.addEventListener("click", (event) => {
    if (event.target === scheduleModal) {
      closeScheduleModal();
      return;
    }

    const resetScheduleButton = event.target.closest("button[data-reset-schedule]");
    if (resetScheduleButton) {
      resetTaskSchedule(resetScheduleButton.dataset.resetSchedule, resetScheduleButton).catch((error) => {
        alert(error.message);
        loadTasks();
      });
      return;
    }

    const addTimeBtn = event.target.closest("[data-add-time]");
    if (addTimeBtn) {
      const timesList = scheduleModal.querySelector(".schedule-times-list");
      if (timesList) {
        const item = document.createElement("div");
        item.className = "schedule-time-item";
        item.innerHTML = `
          <input data-schedule-time type="time" value="" required style="width: 100%;" />
          <button type="button" class="delete-time-btn" data-delete-time title="删除">&times;</button>
        `;
        timesList.appendChild(item);
      }
      return;
    }

    const deleteTimeBtn = event.target.closest("[data-delete-time]");
    if (deleteTimeBtn) {
      const item = deleteTimeBtn.closest(".schedule-time-item");
      if (item) {
        item.remove();
      }
      return;
    }
  });

  scheduleModal.addEventListener("change", (event) => {
    const scheduleMode = event.target.closest("[data-schedule-mode]");
    if (scheduleMode) {
      updateScheduleMode(scheduleMode.closest("form[data-schedule-form]"));
    }
  });

  scheduleModal.addEventListener("submit", (event) => {
    const scheduleForm = event.target.closest("form[data-schedule-form]");
    if (scheduleForm) {
      event.preventDefault();
      const button = scheduleForm.querySelector("button[type='submit']");
      saveTaskSchedule(scheduleForm.dataset.taskId, collectSchedulePayload(scheduleForm), button).catch((error) => {
        alert(error.message);
        loadTasks();
      });
    }
  });
}

searchToggleBtn.addEventListener("click", () => {
  const isExpanded = searchBarWrap.classList.toggle("expanded");
  searchToggleBtn.classList.toggle("active", isExpanded);
  if (isExpanded) {
    searchInput.focus();
  } else {
    searchInput.value = "";
    searchQuery = "";
    if (layoutContainer) {
      layoutContainer.classList.remove("searching");
    }
    renderAgents();
  }
});

searchInput.addEventListener("input", (e) => {
  searchQuery = e.target.value.trim().toLowerCase();
  if (layoutContainer) {
    layoutContainer.classList.toggle("searching", !!searchQuery);
  }
  renderAgents();
});

if (sidebarToggleBtn && layoutContainer) {
  sidebarToggleBtn.addEventListener("click", () => {
    const isCollapsed = layoutContainer.classList.toggle("sidebar-collapsed");
    sidebarToggleBtn.classList.toggle("active", isCollapsed);
  });
}

loadTasks().catch((error) => {
  agentsList.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  agentDetail.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
});
