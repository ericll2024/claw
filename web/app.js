const agentsList = document.querySelector("#agentsList");
const agentDetail = document.querySelector("#agentDetail");
const agentCount = document.querySelector("#agentCount");
const refreshBtn = document.querySelector("#refreshBtn");
const sidebarToggleBtn = document.querySelector("#sidebarToggleBtn");
const layoutContainer = document.querySelector(".layout");
const telegramListenerStatus = document.querySelector("#telegramListenerStatus");

const scheduleModal = document.querySelector("#scheduleModal");
const scheduleModalBody = document.querySelector("#scheduleModalBody");
const scheduleModalTitle = document.querySelector("#scheduleModalTitle");
const closeScheduleModalBtn = document.querySelector("#closeScheduleModalBtn");

const workflowModal = document.querySelector("#workflowModal");
const workflowModalBody = document.querySelector("#workflowModalBody");
const workflowModalTitle = document.querySelector("#workflowModalTitle");
const closeWorkflowModalBtn = document.querySelector("#closeWorkflowModalBtn");

const alertModal = document.querySelector("#alertModal");
const alertModalBody = document.querySelector("#alertModalBody");
const closeAlertModalBtn = document.querySelector("#closeAlertModalBtn");

const runLogModal = document.querySelector("#runLogModal");
const runLogModalBody = document.querySelector("#runLogModalBody");
const runLogModalTitle = document.querySelector("#runLogModalTitle");
const closeRunLogModalBtn = document.querySelector("#closeRunLogModalBtn");

const configModal = document.querySelector("#configModal");
const configTextarea = document.querySelector("#configTextarea");
const configForm = document.querySelector("#configForm");
const closeConfigModalBtn = document.querySelector("#closeConfigModalBtn");
const cancelConfigBtn = document.querySelector("#cancelConfigBtn");
const saveConfigBtn = document.querySelector("#saveConfigBtn");
let activeConfigTaskId = null;

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
let selectedRunFilterTaskId = "all";
let selectedRunFilterStatus = "all";

const taskWorkflows = {
  "cp.predict": [
    { title: "加载历史数据", detail: "连接 traerclaw.sqlite3 数据库，执行 SQL 语句：SELECT max(issue_code) FROM ssq_history 读取双色球最新期号，并将最近 100 期的红球、蓝球中奖号码全部载入内存。" },
    { title: "运行预测算法", detail: "基于历史开奖数据，运用概率算法及杀号过滤规则（比如和值范围、奇偶比、跨度等条件）过滤出高概率备选球，交叉组合并打分计算出下一期的前瞻推荐号码方案。" },
    { title: "生成推荐方案", detail: "整理评分最高的前 5 组双色球推荐号码方案（每组含 6 个红球与 1 个蓝球）。" },
    { title: "保存预测结果", detail: "执行 SQL：INSERT INTO predictions (issue_code, red_balls, blue_ball) VALUES (?, ?, ?) 将预测推荐结果持久化，供开奖后结算核实。" }
  ],
  "cp.check_result": [
    { title: "拉取最新开奖", detail: "使用 HTTP GET 请求双色球数据接口（如爱彩网或新浪彩票），带重试机制，拉取最新一期的开奖号码 JSON 数据。" },
    { title: "写入开奖历史", detail: "执行 SQL：INSERT OR IGNORE INTO ssq_history (issue_code, red_balls, blue_ball) VALUES (?, ?, ?) 将拉取的最新中奖号码存入本地数据库。" },
    { title: "读取预测方案", detail: "执行 SQL：SELECT id, red_balls, blue_ball FROM predictions WHERE issue_code = ? 查询之前为该期生成的预测号码方案。" },
    { title: "结算与复盘", detail: "逻辑：逐一比对预测红蓝球与开奖红蓝球的重合数。如 6+1 匹配为一等奖，5+1 为三等奖等，计算中奖金额，更新 predictions 中该期 prize_level，生成 markdown 对账单通过 Telegram 群播报。" }
  ],
  "tycp.dlt_recommend": [
    { title: "生成预算组合", detail: "逻辑：通过过滤规则及出现频率推荐出 100元(8+2)、500元(10+2)、1000元(11+2) 复式票组合号码方案。" },
    { title: "保存推荐方案", detail: "执行 SQL：INSERT INTO dlt_plans / dlt_tickets 将方案和所有展开的投注明细持久化到 SQLite 数据库。" }
  ],
  "tycp.dlt_fetch": [
    { title: "拉取最新开奖", detail: "使用 HTTP GET 请求接口：https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry 增量更新大乐透开奖结果。" },
    { title: "比对结算复盘", detail: "逻辑：查询之前为该期生成的各预算推荐方案明细，逐一比对中奖情况，计算中奖注数及金额，更新至大乐透中奖明细及复盘数据库并输出报告。" }
  ],
  "mfood.maskphone_monitor": [
    { title: "读取登录 Token", detail: "执行 SQL：SELECT value FROM settings WHERE key = 'mfood.login.token' 读取全局登录 Token。如 Token 缺失直接报错并中断运行。" },
    { title: "访问隐私号 API", detail: "使用 HTTP POST 携带 Token、x-scope='manager' 标头请求接口：https://management-api.mfoodapp.com/managers/orgs/maskPhone/_topCount 抓取当天隐私号使用详情。" },
    { title: "监测使用限额", detail: "逻辑：提取 allCount (总配额)、usingCount (使用中)、otherUsingCount (其他使用)。计算 focusUsedCount = usingCount + otherUsingCount，设定警戒阈值 threshold = allCount * 0.8。" },
    { title: "推送报警消息", detail: "逻辑：如果 focusUsedCount > threshold 成立（即已用隐私号占配额 80% 以上），状态记为 alert，格式化异常报警消息并通过 Telegram 发送警报；若未超限则记为 ok 正常状态。" }
  ],
  "mfood.shence_health": [
    { title: "加载神策配置", detail: "从 settings 表中加载 sensors_api_key、sensors_project 凭据和接口地址 api_url。" },
    { title: "构建查询 SQL", detail: "从任务定义或运行时配置读取待执行的神策 SQL 分析语句（如检测昨日特定渠道 of 订单付款埋点明细）。" },
    { title: "发送网络查询", detail: "使用 HTTP POST 携带 API Key 等头信息调用：https://{sensors_api_url}/api/v3/analytics/v1/model/sql/query 传入 SQL 与 limit 行数（默认 100）。" },
    { title: "解析返回行集", detail: "逻辑：解析返回的 JSON 结构，验证是否包含 error 字段。如无错，则获取返回行数 row_count 并解析每一行的字段（columns），将数据传给前端展示。" }
  ],
  "mfood.takeout_business_analysis": [
    { title: "解析店铺配置", detail: "读取 state/mfdb/takeout_business_analysis_check_config.json 中的商户和店铺 ID 列表，并读取 settings 表的全局 Token。" },
    { title: "请求营业数据", detail: "使用 HTTP POST 发送 x-merchant 头，调用接口：https://management-api.mfoodapp.com/merchants/takeouts/analysis/store/order/_business_data 获取指定日期的营业额 totalBusinessAmtn 与实收 receive。" },
    { title: "拉取订单与差评", detail: "二级对账逻辑：如果营业数据返回的 totalBusinessAmtn 营业额为 0，则调用订单复查列表接口：https://management-api.mfoodapp.com/merchants/takeouts/order/_list 拉取昨日订单明细。" },
    { title: "异常诊断与推送", detail: "逻辑：判定 is_zero(totalBusinessAmtn) 且 review_has_orders(昨日订单数 > 0) 是否成立。如果该店铺营业分析显示营业额为 0 但列表里其实有订单，则为对账异常。状态标记为 alert 并通过 Telegram 报警。" }
  ],
  "mfood.market_business_analysis": [
    { title: "解析超市配置", detail: "从 market_business_analysis_check_config.json 加载商户 ID 列表，及 settings 表里的全局 Token。" },
    { title: "获取超市营业数据", detail: "使用 HTTP POST 携带参数，请求接口：https://management-api.mfoodapp.com/merchants/market/report/business/_merchant-data 抓取各店铺昨日超市营业总额与退款笔数。" },
    { title: "提取超市订单明细", detail: "二级对账逻辑：如果超市营业数据中的 totalBusinessAmtn 营业额为 0，则请求超市订单列表接口：https://management-api.mfoodapp.com/merchants/market/merchantOrder/report/_list 进行复核。" },
    { title: "指标计算与播报", detail: "逻辑：若 totalBusinessAmtn 为 0 且复核接口中昨日订单数 > 0 判定为 True，即判定为账目异常。状态记为 alert，将异常门店和金额推送至 Telegram 警报。" }
  ],
  "mfood.market_summary": [
    { title: "加载对账配置", detail: "从 market_summary_check_config.json 读取超市结算与对账监控的配置参数，并提取全局登录 Token。" },
    { title: "调取超市汇总报表", detail: "使用 HTTP POST 请求接口：https://management-api.mfoodapp.com/merchants/market/summary/_merchant-list 获取全商户在指定日期的超市汇总对账单数据。" },
    { title: "核对资金流向", detail: "二级对账逻辑：对每一行超市记录，如果其 subsidyStoreReceiveAmtn 补贴金额为 0，则调用超市订单对账列表接口：https://management-api.mfoodapp.com/merchants/market/merchantOrder/report/_list 检查是否有昨日的实际完成订单。" },
    { title: "异常核算并播报", detail: "逻辑：若对账汇总中补贴为 0，但订单列表中实际上有已结账订单，则判定为资金流数据不一致（has_issue = True）。状态记为 alert 并向 Telegram 播报异常。" }
  ],
  "mfood.merchant_summary": [
    { title: "加载外卖汇总配置", detail: "从 merchant_summary_check_config.json 获取外卖商家结算汇总配置，并提取全局登录 Token。" },
    { title: "请求商户对账单", detail: "使用 HTTP POST 接口：https://management-api.mfoodapp.com/merchants/summarys/summary/_list 抓取昨日外卖销售总额、实际结算金额等财务数据。" },
    { title: "处理账目不匹配项", detail: "二级对账逻辑：如果外卖商户对账的结算值/补贴为 0，调用外卖订单列表接口：https://management-api.mfoodapp.com/merchants/takeouts/order/_list 抓取昨日实际生成的订单数据进行复核。" },
    { title: "差异结算报告与报警", detail: "逻辑：若销售汇总结算金额为 0 但二级复核中存在昨日实收订单，则判定为财务对账异常（has_issue = True）。状态置为 alert 并发送 Telegram 汇总异常报警。" }
  ],
  "shence.order_reconcile": [
    { title: "配置时间区间", detail: "默认获取昨日的零点和深夜 23:59:59 的毫秒时间戳（startTime 和 endTime）。" },
    { title: "运行神策 SQL", detail: "调用 traeclaw.mfood.shence 模块，利用神策 API 查询昨日埋点数据：统计外卖、超市支付成功（pay_order）与退款成功的订单数和总金额。" },
    { title: "获取 mFood 账单", detail: "调用 traeclaw.mfood.login 获取 Token 并登录 mFood 商家后台，拉取相同时段的真实订单交易记录。" },
    { title: "双端比对及报警", detail: "逻辑：比对神策和 mFood 的订单数量与实付金额，如果异常差值超出限额，写入 sqlite 监控数据库，并发送 Telegram 对账异常播报。" }
  ],
  "facebook.yesterday_summary": [
    { title: "读取监测群组", detail: "从 fb_groups.json 加载需要监控的 Facebook 群组链接，并从 fb_last_check.json 读取最后检查时间戳。" },
    { title: "连接 BrowserSkill", detail: "逻辑：通过 BrowserSkill 与本地 Edge 浏览器建立自动化连接并激活监控标签页。" },
    { title: "遍历抓取新贴", detail: "逻辑：循环访问各群组页面，滑动页面加载内容，增量抓取自上一次检查时间以来的新贴文本与作者。" },
    { title: "内容摘要与通知", detail: "逻辑：过滤去重并提取新贴主题与摘要，生成日报报告，若配置了 Telegram 机器人则推送汇总消息。" }
  ]
};

let agents = [];
let selectedAgentId = "";
let selectedDetailTab = "runs";
let runLimitMode = "10";
let customRunLimit = "25";
let runsCache = {};
let editingAlias = false;
let loadingRunsKey = "";
let runsOffset = 0;
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

async function loadTelegramListenerStatus() {
  if (!telegramListenerStatus) {
    return;
  }
  try {
    const payload = await api("/api/telegram/listener");
    const listener = payload.listener || {};
    if (listener.running) {
      telegramListenerStatus.textContent = "Telegram 监听中";
      telegramListenerStatus.className = "badge success";
    } else if (listener.enabled) {
      telegramListenerStatus.textContent = "Telegram 待启动";
      telegramListenerStatus.className = "badge running";
    } else {
      telegramListenerStatus.textContent = "Telegram 未监听";
      telegramListenerStatus.className = "badge";
    }
  } catch (error) {
    telegramListenerStatus.textContent = "Telegram 状态异常";
    telegramListenerStatus.className = "badge failed";
  }
}

function statusBadge(status, enabled = true) {
  if (!enabled) return `<span class="badge disabled">未启用</span>`;
  if (!status) return `<span class="badge">未运行</span>`;
  const label = status === "success" ? "成功" : status === "failed" ? "失败" : status === "pending" ? "待运行" : status === "running" ? "运行中" : status;
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
        <div class="agent-meta" style="justify-content: flex-end;">
          <span>${escapeHtml(agent.enabled_count)} / ${escapeHtml(agent.task_count)} 启用</span>
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
    <div class="tasks-panel">
      <div class="tasks-table-wrap">
        <table class="tasks-table">
          <thead>
            <tr>
              <th>子任务</th>
              <th>时间配置 / 下次</th>
              <th>最近运行</th>
              <th>TG 通知群</th>
              <th style="width: 100px;">状态</th>
              <th style="width: 380px;">操作</th>
            </tr>
          </thead>
          <tbody>
            ${agent.tasks.map((task, idx) => renderTaskRow(task, idx, agent.tasks.length)).join("")}
          </tbody>
        </table>
      </div>
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
        <div>
          <label>
            <span>筛选子任务</span>
            <select data-run-filter-task>
              <option value="all">全部子任务</option>
              ${agent.tasks.map(t => `<option value="${escapeHtml(t.id)}"${selectedRunFilterTaskId === t.id ? " selected" : ""}>${escapeHtml((t.schedule && t.schedule.name) || t.name)}</option>`).join("")}
            </select>
          </label>
        </div>
        <div>
          <label>
            <span>筛选状态</span>
            <select data-run-filter-status>
              <option value="all" ${selectedRunFilterStatus === "all" ? "selected" : ""}>全部状态</option>
              <option value="success" ${selectedRunFilterStatus === "success" ? "selected" : ""}>成功</option>
              <option value="failed" ${selectedRunFilterStatus === "failed" ? "selected" : ""}>失败</option>
              <option value="running" ${selectedRunFilterStatus === "running" ? "selected" : ""}>运行中</option>
              <option value="pending" ${selectedRunFilterStatus === "pending" ? "selected" : ""}>待运行</option>
            </select>
          </label>
        </div>
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
  let filteredRuns = runs;
  if (selectedRunFilterTaskId && selectedRunFilterTaskId !== "all") {
    filteredRuns = runs.filter(run => run.task_id === selectedRunFilterTaskId);
  }
  if (selectedRunFilterStatus && selectedRunFilterStatus !== "all") {
    filteredRuns = filteredRuns.filter(run => run.status === selectedRunFilterStatus);
  }
  const sortedRuns = [...filteredRuns].sort(compareRunsDesc);
  if (isLoading && runs.length === 0) {
    return `<div class="empty">正在加载运行结果...</div>`;
  }
  if (sortedRuns.length === 0) {
    return `<div class="empty">暂无运行结果</div>`;
  }

  const limitStr = resolvedRunLimit();
  const limit = limitStr === "all" ? null : Number(limitStr);
  const cacheKey = runsCacheKey(selectedAgentId);
  const cachedPayload = runsCache[cacheKey] || {};
  const hasNext = cachedPayload.has_next || false;

  let paginationHtml = "";
  if (limit !== null) {
    paginationHtml = `
      <div class="runs-pagination" style="display: flex; align-items: center; justify-content: flex-start; gap: 12px; margin-top: 12px; padding: 8px 0; border-top: 1px solid var(--line);">
        <button class="button small-btn" data-action="runs-prev-page" ${runsOffset <= 0 ? "disabled" : ""}>上一页</button>
        <span style="font-size: 13px; color: var(--muted);">第 ${Math.floor(runsOffset / limit) + 1} 页 (每页 ${limit} 条)</span>
        <button class="button small-btn" data-action="runs-next-page" ${!hasNext ? "disabled" : ""}>下一页</button>
      </div>
    `;
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
            <th>TG 通知</th>
            <th>耗时</th>
            <th>结果</th>
            <th style="width: 150px; text-align: center;">操作</th>
          </tr>
        </thead>
        <tbody>
          ${sortedRuns.map(renderRunRow).join("")}
        </tbody>
      </table>
    </div>
    ${paginationHtml}
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

  let notifyLabel = "";
  const ns = (run.notify_status || "").toLowerCase();
  if (ns === "sent" || ns === "success") {
    notifyLabel = `<span class="badge success">已发送</span>`;
  } else if (ns === "failed") {
    notifyLabel = `<span class="badge failed" style="cursor: help;" title="${escapeHtml(run.notify_error || '未知错误')}">发送失败 ❓</span>`;
  } else if (ns === "skipped") {
    notifyLabel = `<span class="badge" style="background: #e2e8f0; color: #4a5568;">已略过</span>`;
  } else {
    notifyLabel = `<span class="badge" style="background: transparent; border: 1px solid var(--line); color: var(--muted);">未发送</span>`;
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
      <td>${notifyLabel}</td>
      <td>${escapeHtml(formatDuration(run.duration_ms))}</td>
      <td class="run-summary">${escapeHtml(run.summary || run.stderr || run.stdout || "无")}</td>
      <td style="text-align: center; vertical-align: middle;">
        <div style="display: flex; flex-direction: column; gap: 6px; align-items: center; justify-content: center;">
          <button class="button small-btn" data-action="view-run-log" data-run-id="${escapeHtml(run.id)}" style="padding: 3px 6px; font-size: 11px; white-space: nowrap; width: 100px;">查看运行日志</button>
          <button class="button danger small-btn" data-action="delete-run" data-run-id="${escapeHtml(run.id)}" style="padding: 3px 6px; font-size: 11px; white-space: nowrap; width: 100px;">删除</button>
        </div>
      </td>
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
  return `${agentId}:${resolvedRunLimit()}:${runsOffset}`;
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
  const payload = await api(`/api/task-groups/${encodeURIComponent(agentId)}/runs?limit=${encodeURIComponent(resolvedRunLimit())}&offset=${encodeURIComponent(runsOffset)}`);
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

function renderTaskRow(task, idx, total) {
  const run = task.last_run;
  let tgGroupHtml = '<span style="color: var(--muted); font-size: 12px;">未配置</span>';
  if (task.telegram_chat_id) {
    tgGroupHtml = `
      <div style="font-weight: 500; color: var(--text); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px;" title="群名：${escapeHtml(task.telegram_group_name || "无")}">
        群名：${escapeHtml(task.telegram_group_name || "无")}
      </div>
      <div style="font-size: 11px; color: var(--muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px;" title="群id：${escapeHtml(task.telegram_chat_id)}">
        群id：${escapeHtml(task.telegram_chat_id)}
      </div>
    `;
  }

  const isFirst = idx === 0;
  const isLast = idx === total - 1;

  const sortActionsHtml = `
    <div class="task-sort-actions" style="display: flex; gap: 4px; justify-content: center;">
      <button class="sort-btn up" data-action="move-task-up" data-task-id="${escapeHtml(task.id)}" title="上移"${isFirst ? " disabled" : ""}>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="18 15 12 9 6 15"></polyline>
        </svg>
      </button>
      <button class="sort-btn down" data-action="move-task-down" data-task-id="${escapeHtml(task.id)}" title="下移"${isLast ? " disabled" : ""}>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>
    </div>
  `;

  return `
    <tr>
      <td>
        <div class="task-name-row" style="display: flex; align-items: center; gap: 8px;">
          <strong style="color: var(--text); font-size: 14px;">${escapeHtml((task.schedule && task.schedule.name) || task.name || "")}</strong>
        </div>
        <div class="task-desc" style="margin-top: 4px; font-size: 12px; color: var(--muted); max-width: 420px; line-height: 1.4;">
          ${escapeHtml(task.note || (task.schedule && task.schedule.note) || task.description || "")}
        </div>
        ${task.config_preview ? `
          <div class="task-config-preview" style="margin-top: 6px; font-size: 11px; color: var(--accent); background: rgba(37, 111, 108, 0.08); padding: 3px 8px; border-radius: 4px; display: inline-flex; align-items: center; gap: 4px; font-family: monospace; border: 1px solid rgba(37, 111, 108, 0.15);">
            <span style="font-size: 12px; line-height: 1;">⚙️</span> <span>${escapeHtml(task.config_preview)}</span>
          </div>
        ` : ''}
      </td>
      <td>
        <div style="font-weight: 600; color: var(--text);">${escapeHtml(task.schedule_label)}</div>
        <div style="font-size: 11px; color: var(--muted); margin-top: 2px;">下次: ${escapeHtml(formatDate(task.next_run_at))}</div>
      </td>
      <td>
        ${run ? `
          <div style="font-weight: 500;">${escapeHtml(formatDate(run.started_at))}</div>
          <div style="margin-top: 2px;">${statusBadge(run.status)}</div>
        ` : `<span style="color: var(--muted);">无</span>`}
      </td>
      <td>
        ${tgGroupHtml}
      </td>
      <td style="text-align: center;">
        ${task.enabled
          ? `<span class="badge success">已启动</span>`
          : `<span class="badge disabled">未启动</span>`
        }
      </td>
      <td style="text-align: right;">
        <div class="task-actions" style="display: inline-flex; gap: 6px; align-items: center;">
          ${sortActionsHtml}
          <button class="button" data-view-workflow="${escapeHtml(task.id)}">工作流</button>
          <button class="button" data-edit-schedule="${escapeHtml(task.id)}">编辑</button>
          <button class="button" data-view-config="${escapeHtml(task.id)}">配置</button>
          ${task.enabled
            ? `<button class="button" data-toggle-enabled="${escapeHtml(task.id)}" data-enabled="false">停止</button>`
            : `<button class="button primary" data-toggle-enabled="${escapeHtml(task.id)}" data-enabled="true">启动</button>`
          }
          <button class="button" data-run="${escapeHtml(task.id)}">运行一次</button>
        </div>
      </td>
    </tr>
  `;
}

function renderScheduleEditor(task) {
  const schedule = task.schedule || {};
  const times = schedule.times || [];
  return `
    <form class="schedule-form" data-schedule-form data-task-id="${escapeHtml(task.id)}" style="display: flex; flex-direction: column; gap: 12px; margin-top: 0;">
      <div style="display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--line); padding-bottom: 12px; margin-bottom: 4px;">
        <label style="display: flex; flex-direction: column; gap: 4px;">
          <span>任务名称</span>
          <input data-schedule-name type="text" autocomplete="off" placeholder="${escapeHtml(task.default_name || task.name)}" value="${escapeHtml(schedule.name || "")}" style="width: 100%;" />
        </label>
        <label style="display: flex; flex-direction: column; gap: 4px;">
          <span>任务备注</span>
          <textarea data-schedule-note placeholder="添加任务备注，说明具体用途或注意事项..." style="width: 100%; min-height: 60px; resize: vertical; padding: 6px 8px; border: 1px solid var(--line); border-radius: 4px; background: var(--input-bg); color: var(--text);">${escapeHtml(schedule.note || task.note || task.description || "")}</textarea>
        </label>
      </div>
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
          <label style="display: flex; flex-direction: column; gap: 4px; margin-bottom: 4px;">
            <span>专属 Chat ID</span>
            <input data-schedule-telegram-chat-id type="text" autocomplete="off" placeholder="留空则使用全局 Chat ID" value="${escapeHtml(schedule.telegram_chat_id || "")}" />
          </label>
          <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; user-select: none;">
            <input data-schedule-only-alert type="checkbox" ${schedule.only_alert_on_abnormal ? "checked" : ""} style="margin: 0;" />
            <span>异常提醒才提醒 (仅在检测到异常时发送消息通知)</span>
          </label>
        </div>
      </div>
      <div class="schedule-actions" style="display: flex; flex-wrap: wrap; align-items: center; gap: 8px; justify-content: flex-end; border-top: 1px solid var(--line); padding-top: 12px; margin-top: 8px;">
        <button class="button primary" type="submit">保存计划</button>
      </div>
    </form>
  `;
}

async function loadTasks() {
  refreshBtn.disabled = true;
  try {
    await loadTelegramListenerStatus();
    const payload = await api(`/api/tasks?t=${Date.now()}`);
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
    queueRunsLoad(selectedAgentId, true);
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
  runSendToTelegram.checked = false;
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

async function moveTask(taskId, action) {
  const agent = agents.find((item) => item.id === selectedAgentId);
  if (!agent) return;
  const idx = agent.tasks.findIndex(t => t.id === taskId);
  if (idx === -1) return;

  if (action === "move-up" && idx > 0) {
    const temp = agent.tasks[idx];
    agent.tasks[idx] = agent.tasks[idx - 1];
    agent.tasks[idx - 1] = temp;
  } else if (action === "move-down" && idx < agent.tasks.length - 1) {
    const temp = agent.tasks[idx];
    agent.tasks[idx] = agent.tasks[idx + 1];
    agent.tasks[idx + 1] = temp;
  } else {
    return;
  }

  renderAgentDetail();

  try {
    await api("/api/tasks/reorder", {
      method: "POST",
      body: JSON.stringify({
        agent_id: agent.id,
        order: agent.tasks.map(t => t.id)
      })
    });
  } catch (error) {
    console.error("Failed to save task order:", error);
    loadTasks();
  }
}

function openWorkflowModal(taskId) {
  const agent = agents.find((item) => item.id === selectedAgentId) || agents[0];
  if (!agent) return;
  const task = agent.tasks.find((t) => t.id === taskId);
  if (!task) return;

  const steps = task.workflow_steps || taskWorkflows[taskId] || [];
  workflowModalTitle.textContent = `工作流 - ${task.name}`;

  if (steps.length === 0) {
    workflowModalBody.innerHTML = `<div class="empty">暂无该任务的工作流描述</div>`;
  } else {
    workflowModalBody.innerHTML = `
      <div class="workflow-steps">
        ${steps.map((step, idx) => `
          <div class="workflow-step">
            <div class="workflow-step-badge">${idx + 1}</div>
            <div class="workflow-step-content">
              <div class="workflow-step-title">${escapeHtml(step.title)}</div>
              <div class="workflow-step-desc">${escapeHtml(step.detail)}</div>
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  workflowModal.classList.add("show");
}

function closeWorkflowModal() {
  workflowModal.classList.remove("show");
  workflowModalBody.innerHTML = "";
}

async function openConfigModal(taskId) {
  const agent = agents.find((item) => item.id === selectedAgentId) || agents[0];
  if (!agent) return;
  const task = agent.tasks.find((t) => t.id === taskId);
  if (!task) return;

  activeConfigTaskId = taskId;
  document.querySelector("#configModalTitle").textContent = `任务配置 - ${task.name}`;
  configTextarea.value = "正在加载配置...";
  configTextarea.disabled = true;
  saveConfigBtn.disabled = true;
  configModal.classList.add("show");

  try {
    const payload = await api(`/api/tasks/${encodeURIComponent(taskId)}/config`);
    if (payload.has_config) {
      configTextarea.disabled = false;
      saveConfigBtn.disabled = false;
      try {
        const parsed = JSON.parse(payload.config_content);
        configTextarea.value = JSON.stringify(parsed, null, 2);
      } catch (e) {
        configTextarea.value = payload.config_content;
      }
    } else {
      configTextarea.value = "此子任务为系统内置核心逻辑，无需外部配置文件。";
      configTextarea.disabled = true;
      saveConfigBtn.disabled = true;
    }
  } catch (error) {
    configTextarea.value = `加载配置失败: ${error.message}`;
    configTextarea.disabled = true;
    saveConfigBtn.disabled = true;
  }
}

function closeConfigModal() {
  configModal.classList.remove("show");
  configTextarea.value = "";
  activeConfigTaskId = null;
}

function getAlertDetails(task) {
  const reasons = [];

  // 1. Check latest results (the payload files)
  const results = task.latest_results || [];
  for (const res of results) {
    const payload = res.payload || {};
    const createdStr = res.created_at ? new Date(res.created_at).toLocaleString("zh-CN") : "";
    
    // Find alert fields in payload recursively
    const alertsInPayload = [];
    findAlertsInPayload(payload, "", alertsInPayload);
    if (alertsInPayload.length > 0) {
      reasons.push({
        type: "business_data",
        time: createdStr,
        details: alertsInPayload
      });
    }
  }

  // 2. Check last run output (stdout, stderr, summary)
  const run = task.last_run;
  if (run) {
    const outputReasons = [];
    const textToCheck = `${run.summary || ""} ${run.stdout || ""} ${run.stderr || ""}`;
    const alertWords = ["报警", "告警", "异常"];
    for (const word of alertWords) {
      if (textToCheck.includes(word)) {
        // Extract context lines or snippets containing the word
        const lines = textToCheck.split(/[\r\n]+/);
        for (const line of lines) {
          if (line.includes(word) && !outputReasons.includes(line.trim())) {
            outputReasons.push(line.trim());
          }
        }
      }
    }
    if (outputReasons.length > 0) {
      reasons.push({
        type: "run_logs",
        time: run.started_at ? new Date(run.started_at).toLocaleString("zh-CN") : "",
        details: outputReasons
      });
    }
  }

  return reasons;
}

function findAlertsInPayload(obj, prefix, results) {
  if (!obj || typeof obj !== "object") return;
  
  if (Array.isArray(obj)) {
    obj.forEach((item, idx) => findAlertsInPayload(item, `${prefix}[${idx}]`, results));
    return;
  }
  
  if (obj.status === "alert" || obj.status === "failed") {
    const msg = obj.message || obj.note || obj.error || JSON.stringify(obj);
    results.push(`${prefix ? prefix + ": " : ""}${msg}`);
  }
  
  for (const [key, value] of Object.entries(obj)) {
    const keyLower = key.toLowerCase();
    if (keyLower.endsWith("alert") && value === true) {
      results.push(`异常激活指标: ${prefix ? prefix + "." : ""}${key}`);
    } else if (typeof value === "object") {
      findAlertsInPayload(value, prefix ? `${prefix}.${key}` : key, results);
    } else if (typeof value === "string") {
      const alertWords = ["报警", "告警", "异常"];
      if (alertWords.some(word => value.includes(word))) {
        results.push(`${prefix ? prefix + "." : ""}${key}: ${value}`);
      }
    }
  }
}

function openAlertModal(taskId) {
  const agent = agents.find((item) => item.id === selectedAgentId) || agents[0];
  if (!agent) return;
  const task = agent.tasks.find((t) => t.id === taskId);
  if (!task) return;

  const reasons = getAlertDetails(task);
  
  let contentHtml = "";
  if (reasons.length === 0) {
    contentHtml = `
      <div style="text-align: center; padding: 24px 0;">
        <div style="font-size: 40px; margin-bottom: 12px;">✅</div>
        <div style="font-size: 15px; font-weight: 600; color: var(--text);">未检测到明显异常</div>
        <div style="font-size: 13px; color: var(--muted); margin-top: 6px;">系统未在最近的运行输出或业务数据中发现异常/报警字样。</div>
      </div>
    `;
  } else {
    contentHtml = reasons.map((reason) => {
      const title = reason.type === "business_data" ? "📊 业务指标异常" : "⚙️ 运行日志报警";
      const badgeClass = reason.type === "business_data" ? "warning" : "failed";
      return `
        <div style="margin-bottom: 16px; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: rgba(0,0,0,0.02);">
          <div style="padding: 10px 14px; background: rgba(0,0,0,0.05); border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; align-items: center;">
            <strong style="font-size: 13.5px; color: var(--text);">${title}</strong>
            <span class="badge ${badgeClass}" style="font-size: 11px; margin: 0; padding: 2px 6px;">${escapeHtml(reason.time)}</span>
          </div>
          <div style="padding: 14px; display: flex; flex-direction: column; gap: 8px;">
            ${reason.details.map((detail) => `
              <div style="display: flex; gap: 8px; font-size: 13px; line-height: 1.5; align-items: flex-start;">
                <span style="color: var(--red); font-weight: bold; font-size: 14px;">•</span>
                <span style="color: var(--text); word-break: break-all;">${escapeHtml(detail)}</span>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }).join("");
  }

  document.querySelector("#alertModalTitle").textContent = `警报详情 - ${task.name}`;
  alertModalBody.innerHTML = `
    <div style="margin-bottom: 16px; font-size: 13px; color: var(--muted); line-height: 1.4;">
      系統在執行該子任務時，透過比對業務資料或分析執行日誌，發現了以下異常指標。請依指示進行排查：
    </div>
    ${contentHtml}
  `;
  alertModal.classList.add("show");
}

function closeAlertModal() {
  alertModal.classList.remove("show");
  alertModalBody.innerHTML = "";
}

function openRunLogModal(runId) {
  const agent = agents.find((item) => item.id === selectedAgentId) || agents[0];
  if (!agent) return;
  const key = runsCacheKey(agent.id);
  const cached = runsCache[key];
  if (!cached || !cached.runs) return;

  const run = cached.runs.find(r => String(r.id) === String(runId));
  if (!run) return;

  runLogModalTitle.textContent = `运行日志 - ${(run.task_name || run.task_id)}`;

  let content = "";
  content += `开始时间: ${new Date(run.started_at).toLocaleString("zh-CN")}\n`;
  content += `运行状态: ${run.status === "success" ? "成功" : run.status === "failed" ? "失败" : run.status}\n`;
  content += `执行耗时: ${formatDuration(run.duration_ms)}\n`;
  if (run.exit_code !== null && run.exit_code !== undefined) {
    content += `退出代码 (Exit Code): ${run.exit_code}\n`;
  }
  content += `\n======================================================================\n`;
  content += `摘要 (Summary):\n`;
  content += `======================================================================\n`;
  content += `${run.summary || "无"}\n\n`;

  content += `======================================================================\n`;
  content += `标准输出 (Stdout):\n`;
  content += `======================================================================\n`;
  content += `${run.stdout || "无"}\n\n`;

  content += `======================================================================\n`;
  content += `标准错误 (Stderr):\n`;
  content += `======================================================================\n`;
  content += `${run.stderr || "无"}\n`;

  runLogModalBody.textContent = content;
  runLogModal.classList.add("show");
}

function closeRunLogModal() {
  runLogModal.classList.remove("show");
  runLogModalBody.innerHTML = "";
}

async function deleteRun(runId, button) {
  button.disabled = true;
  try {
    await api(`/api/runs/${encodeURIComponent(runId)}/delete`, { method: "POST" });
    delete runsCache[runsCacheKey(selectedAgentId)];
    queueRunsLoad(selectedAgentId, true);
  } finally {
    button.disabled = false;
  }
}

function collectSchedulePayload(form) {
  const mode = form.querySelector("[data-schedule-mode]").value;
  return {
    name: form.querySelector("[data-schedule-name]")?.value.trim() || "",
    note: form.querySelector("[data-schedule-note]")?.value.trim() || "",
    mode,
    start_date: form.querySelector("[data-schedule-start]").value,
    end_date: form.querySelector("[data-schedule-end]").value,
    weekdays: Array.from(form.querySelectorAll("[data-schedule-weekday]:checked")).map((input) => Number(input.value)),
    times: Array.from(form.querySelectorAll("[data-schedule-time]")).map((input) => input.value.trim()).filter(Boolean),
    telegram_chat_id: form.querySelector("[data-schedule-telegram-chat-id]")?.value.trim() || "",
    only_alert_on_abnormal: form.querySelector("[data-schedule-only-alert]")?.checked || false,
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
  selectedRunFilterTaskId = "all";
  selectedRunFilterStatus = "all";
  runsOffset = 0;
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

  const moveUpBtn = event.target.closest("button[data-action='move-task-up']");
  if (moveUpBtn) {
    event.stopPropagation();
    moveTask(moveUpBtn.dataset.taskId, "move-up");
    return;
  }

  const moveDownBtn = event.target.closest("button[data-action='move-task-down']");
  if (moveDownBtn) {
    event.stopPropagation();
    moveTask(moveDownBtn.dataset.taskId, "move-down");
    return;
  }

  const viewWorkflowBtn = event.target.closest("button[data-view-workflow]");
  if (viewWorkflowBtn) {
    openWorkflowModal(viewWorkflowBtn.dataset.viewWorkflow);
    return;
  }

  const prevPageBtn = event.target.closest("[data-action='runs-prev-page']");
  if (prevPageBtn) {
    const limitStr = resolvedRunLimit();
    const limit = limitStr === "all" ? 10 : Number(limitStr);
    runsOffset = Math.max(0, runsOffset - limit);
    queueRunsLoad(selectedAgentId, true);
    return;
  }

  const nextPageBtn = event.target.closest("[data-action='runs-next-page']");
  if (nextPageBtn) {
    const limitStr = resolvedRunLimit();
    const limit = limitStr === "all" ? 10 : Number(limitStr);
    runsOffset += limit;
    queueRunsLoad(selectedAgentId, true);
    return;
  }

  const viewRunLogBtn = event.target.closest("[data-action='view-run-log']");
  if (viewRunLogBtn) {
    event.stopPropagation();
    openRunLogModal(viewRunLogBtn.dataset.runId);
    return;
  }

  const deleteRunBtn = event.target.closest("[data-action='delete-run']");
  if (deleteRunBtn) {
    event.stopPropagation();
    if (confirm("确定要删除这条运行记录吗？")) {
      const runId = deleteRunBtn.dataset.runId;
      deleteRun(runId, deleteRunBtn).catch((error) => alert(error.message));
    }
    return;
  }

  const viewConfigBtn = event.target.closest("button[data-view-config]");
  if (viewConfigBtn) {
    event.stopPropagation();
    openConfigModal(viewConfigBtn.dataset.viewConfig);
    return;
  }

  const viewAlertBtn = event.target.closest("[data-action='view-alert']");
  if (viewAlertBtn) {
    event.stopPropagation();
    openAlertModal(viewAlertBtn.dataset.taskId);
    return;
  }

  const button = event.target.closest("button[data-run]");
  if (!button) return;
  promptRunTask(button.dataset.run, button);
});

agentDetail.addEventListener("change", (event) => {
  const limitSelect = event.target.closest("[data-run-limit-mode]");
  if (limitSelect) {
    runLimitMode = limitSelect.value;
    const agent = agents.find((item) => item.id === selectedAgentId) || agents[0];
    if (agent) {
      runsOffset = 0;
      queueRunsLoad(agent.id, true);
    }
    renderAgentDetail();
    return;
  }

  const filterSelect = event.target.closest("[data-run-filter-task]");
  if (filterSelect) {
    selectedRunFilterTaskId = filterSelect.value;
    renderAgentDetail();
    return;
  }

  const statusFilterSelect = event.target.closest("[data-run-filter-status]");
  if (statusFilterSelect) {
    selectedRunFilterStatus = statusFilterSelect.value;
    renderAgentDetail();
    return;
  }
});

agentDetail.addEventListener("submit", (event) => {
  const runsForm = event.target.closest("form[data-runs-limit-form]");
  if (runsForm) {
    event.preventDefault();
    const input = runsForm.querySelector("[data-custom-run-limit]");
    if (input) customRunLimit = input.value.trim() || "10";
    runsOffset = 0;
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
if (closeWorkflowModalBtn) {
  closeWorkflowModalBtn.addEventListener("click", closeWorkflowModal);
}
if (closeAlertModalBtn) {
  closeAlertModalBtn.addEventListener("click", closeAlertModal);
}
if (workflowModal) {
  workflowModal.addEventListener("click", (event) => {
    if (event.target === workflowModal) {
      closeWorkflowModal();
    }
  });
}
if (alertModal) {
  alertModal.addEventListener("click", (event) => {
    if (event.target === alertModal) {
      closeAlertModal();
    }
  });
}
if (closeRunLogModalBtn) {
  closeRunLogModalBtn.addEventListener("click", closeRunLogModal);
}
if (runLogModal) {
  runLogModal.addEventListener("click", (event) => {
    if (event.target === runLogModal) {
      closeRunLogModal();
    }
  });
}
if (scheduleModal) {
  scheduleModal.addEventListener("click", (event) => {
    if (event.target === scheduleModal) {
      closeScheduleModal();
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

// 任务配置弹窗事件监听
if (closeConfigModalBtn) {
  closeConfigModalBtn.addEventListener("click", closeConfigModal);
}
if (cancelConfigBtn) {
  cancelConfigBtn.addEventListener("click", closeConfigModal);
}
if (configModal) {
  configModal.addEventListener("click", (event) => {
    if (event.target === configModal) {
      closeConfigModal();
    }
  });
}
if (configForm) {
  configForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!activeConfigTaskId) return;

    const newContent = configTextarea.value.trim();
    try {
      JSON.parse(newContent);
    } catch (e) {
      alert(`保存失败: JSON 格式错误 (${e.message})`);
      return;
    }

    saveConfigBtn.disabled = true;
    saveConfigBtn.textContent = "保存中...";

    api(`/api/tasks/${encodeURIComponent(activeConfigTaskId)}/config`, {
      method: "POST",
      body: JSON.stringify({ config_content: newContent })
    }).then(() => {
      alert("配置保存成功！");
      closeConfigModal();
      loadTasks();
    }).catch((error) => {
      alert(`保存失败: ${error.message}`);
    }).finally(() => {
      saveConfigBtn.disabled = false;
      saveConfigBtn.textContent = "保存配置";
    });
  });
}

loadTasks().catch((error) => {
  agentsList.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  agentDetail.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
});

// 重启服务事件监听
const restartBtn = document.querySelector("#restartBtn");
if (restartBtn) {
  restartBtn.addEventListener("click", async () => {
    if (!confirm("是否确认重启服务？")) {
      return;
    }
    restartBtn.disabled = true;
    restartBtn.textContent = "正在重启...";
    try {
      await api("/api/restart", { method: "POST" });
    } catch (e) {
      console.log("Restart request sent. Server terminating...", e);
    }
    
    const overlay = document.createElement("div");
    overlay.style.position = "fixed";
    overlay.style.top = "0";
    overlay.style.left = "0";
    overlay.style.width = "100%";
    overlay.style.height = "100%";
    overlay.style.background = "rgba(0,0,0,0.7)";
    overlay.style.color = "#fff";
    overlay.style.display = "flex";
    overlay.style.alignItems = "center";
    overlay.style.justifyContent = "center";
    overlay.style.fontSize = "18px";
    overlay.style.zIndex = "9999";
    overlay.innerHTML = "正在重启服务，请稍候...";
    document.body.appendChild(overlay);
    
    setTimeout(() => {
      window.location.reload();
    }, 3000);
  });
}

// 退出登录事件监听
const logoutBtn = document.querySelector("#logoutBtn");
if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST" });
      localStorage.removeItem("token");
      window.location.href = "/login";
    } catch (err) {
      console.error("Logout failed:", err);
    }
  });
}

