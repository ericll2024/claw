const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const BSK_PATH = 'C:\\Users\\40282\\.local\\bin\\bsk.exe';
const EGO_PATH = 'ego-browser';
const TZ = 'Asia/Shanghai';

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function runBrowserTool(toolName, args) {
  const tool = (toolName || 'ego-browser').toLowerCase();
  if (tool === 'ego-browser' || tool === 'ego') {
    try {
      return execFileSync(EGO_PATH, args, { encoding: 'utf8' }).trim();
    } catch (err1) {
      try {
        return execFileSync('ego', args, { encoding: 'utf8' }).trim();
      } catch (err2) {
        console.warn('[ego-browser] CLI fallback to BrowserSkill (bsk) engine...');
        return execFileSync(BSK_PATH, args, { encoding: 'utf8' }).trim();
      }
    }
  } else {
    return execFileSync(BSK_PATH, args, { encoding: 'utf8' }).trim();
  }
}

function getActiveSession(toolName) {
  const output = runBrowserTool(toolName, ['session', 'list', '--json']);
  try {
    const sessions = JSON.parse(output);
    if (sessions && sessions.length > 0) {
      return sessions[0].session_id;
    }
  } catch (e) {}

  console.log(`[${toolName}] No active session found. Starting a new session...`);
  const newSessionId = runBrowserTool(toolName, ['session', 'start']);
  console.log(`[${toolName}] Started session: ${newSessionId}`);
  return newSessionId;
}

function getActiveTab(toolName, sessionId) {
  const output = runBrowserTool(toolName, ['tab', 'list', '--session', sessionId, '--json']);
  const data = JSON.parse(output);
  if (data.tabs && data.tabs.length > 0) {
    const agentTab = data.tabs.find(t => t.scope === 'agent');
    if (agentTab) {
      console.log(`Using Agent-scoped Tab: ${agentTab.tab_id}`);
      return agentTab.tab_id;
    }
    const activeTab = data.tabs.find(t => t.active) || data.tabs[0];
    console.log(`Using User-scoped Tab: ${activeTab.tab_id}. Borrowing...`);
    try {
      runBrowserTool(toolName, ['tab', 'borrow', String(activeTab.tab_id), '--session', sessionId]);
    } catch (e) {
      console.warn('Failed to borrow tab:', e.message);
    }
    return activeTab.tab_id;
  }
  throw new Error('No tabs found in session');
}

function parseTimeToDate(timeText, referenceDate = new Date()) {
  if (!timeText) return null;
  const s = timeText.trim().toLowerCase();
  if (!s) return null;

  const date = new Date(referenceDate);

  const minMatch = s.match(/(\d+)\s*(?:分钟|分钟前|m|min|mins|minute|minutes)/);
  if (minMatch) {
    date.setMinutes(date.getMinutes() - parseInt(minMatch[1], 10));
    return date;
  }

  const hourMatch = s.match(/(\d+)\s*(?:小时|小时前|小時|小時前|h|hr|hrs|hour|hours)/);
  if (hourMatch) {
    date.setHours(date.getHours() - parseInt(hourMatch[1], 10));
    return date;
  }

  const dayMatch = s.match(/(\d+)\s*(?:天|天前|d|day|days)/);
  if (dayMatch) {
    date.setDate(date.getDate() - parseInt(dayMatch[1], 10));
    return date;
  }

  if (s.includes('昨天') || s.includes('yesterday')) {
    date.setDate(date.getDate() - 1);
    return date;
  }

  if (s.includes('前天')) {
    date.setDate(date.getDate() - 2);
    return date;
  }

  let m = s.match(/(20\d{2})[/\-](\d{1,2})[/\-](\d{1,2})/);
  if (m) {
    return new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10), 12, 0, 0);
  }

  m = s.match(/(\d{1,2})月(\d{1,2})[日号]?/);
  if (m) {
    return new Date(date.getFullYear(), parseInt(m[1], 10) - 1, parseInt(m[2], 10), 12, 0, 0);
  }

  const parsedEpoch = Date.parse(s);
  if (!isNaN(parsedEpoch)) {
    return new Date(parsedEpoch);
  }

  return null;
}

async function main() {
  const projectRoot = path.resolve(__dirname, '../..');
  const groupsFile = path.join(projectRoot, 'state/facebook/fb_groups.json');

  let tool = 'ego-browser';
  let groups = [
    'https://www.facebook.com/groups/273979355317477',
    'https://www.facebook.com/groups/982872103263383/',
    'https://www.facebook.com/groups/644345363776357'
  ];

  if (fs.existsSync(groupsFile)) {
    try {
      const config = JSON.parse(fs.readFileSync(groupsFile, 'utf8'));
      if (config.tool) tool = config.tool;
      if (config.groups && config.groups.length > 0) groups = config.groups;
    } catch (e) {
      console.warn('Error reading fb_groups.json:', e.message);
    }
  }

  console.log(`Configured Scraping Tool: ${tool}`);

  const lastCheckFile = path.join(projectRoot, 'state/facebook/fb_last_check.json');
  let lastCheckTimeStr = '';
  if (fs.existsSync(lastCheckFile)) {
    try {
      const lastCheckData = JSON.parse(fs.readFileSync(lastCheckFile, 'utf8'));
      lastCheckTimeStr = lastCheckData.last_check_time || '';
    } catch (e) {
      console.warn('Error reading fb_last_check.json:', e.message);
    }
  }

  function getLocalDateParts(date) {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: TZ,
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      hour12: false
    });
    const parts = formatter.formatToParts(date);
    const getPart = (t) => parseInt(parts.find(p => p.type === t).value, 10);
    return {
      year: getPart('year'),
      month: getPart('month') - 1,
      day: getPart('day'),
      hour: getPart('hour'),
      minute: getPart('minute'),
      second: getPart('second')
    };
  }

  function makeMacauDate(year, month, day, hour = 0, minute = 0, second = 0) {
    const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}+08:00`;
    return new Date(dateStr);
  }

  const currentCheckTime = new Date();
  let lastCheckDate;
  let endCheckDate;
  let isFallbackToYesterday = false;

  if (lastCheckTimeStr) {
    lastCheckDate = new Date(lastCheckTimeStr);
    if (isNaN(lastCheckDate.getTime())) {
      isFallbackToYesterday = true;
    } else {
      endCheckDate = currentCheckTime;
    }
  } else {
    isFallbackToYesterday = true;
  }

  if (isFallbackToYesterday) {
    const todayMacau = new Date();
    const yesterdayMacau = new Date(todayMacau.getTime() - 24 * 60 * 60 * 1000);
    const yesterdayParts = getLocalDateParts(yesterdayMacau);
    lastCheckDate = makeMacauDate(yesterdayParts.year, yesterdayParts.month, yesterdayParts.day, 0, 0, 0);
    endCheckDate = makeMacauDate(yesterdayParts.year, yesterdayParts.month, yesterdayParts.day, 23, 59, 59);
  }

  console.log(`Current Check Time: ${currentCheckTime.toISOString()}`);
  console.log(`Filter Window:      ${lastCheckDate.toISOString()} to ${endCheckDate.toISOString()}`);

  const sessionId = getActiveSession(tool);
  const tabId = getActiveTab(tool, sessionId);
  console.log(`Using Session: ${sessionId}, Tab: ${tabId}`);

  try {
    console.log(`Activating/Focusing tab ${tabId}...`);
    runBrowserTool(tool, ['tab', 'select', String(tabId), '--session', sessionId]);
  } catch (e) {
    console.warn('Failed to select tab:', e.message);
  }

  const reportData = [];
  let anyThrottleOrFailure = false;

  for (let i = 0; i < groups.length; i++) {
    const url = groups[i];
    let targetUrl = url;
    if (targetUrl.includes('?')) {
      targetUrl += '&sorting_setting=CHRONOLOGICAL';
    } else {
      targetUrl = targetUrl.replace(/\/$/, '') + '/?sorting_setting=CHRONOLOGICAL';
    }

    console.log(`\n[${i+1}/${groups.length}] Navigating via ${tool}: ${targetUrl}`);
    runBrowserTool(tool, ['navigate', '--session', sessionId, '--tab-id', String(tabId), '--timeout', '90s', targetUrl]);
    await sleep(6000);

    let title = runBrowserTool(tool, ['evaluate', '--session', sessionId, '--tab-id', String(tabId), 'document.title']);
    const groupName = title.replace(/\(\d+\+\)\s*/, '').split('|')[0].replace(/#|@/g, '').trim();
    console.log(`Group Name: ${groupName}`);

    const extractionJs = `
      new Promise(async (resolve) => {
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        const accumulated = {};
        let scrolls = 0;
        let maxScrolls = 8;

        function text(el) {
          if (!el) return '';
          let clone = el.cloneNode(true);
          clone.querySelectorAll('script, style, svg').forEach(s => s.remove());
          return clone.innerText || clone.textContent || '';
        }

        function firstMatch(arr, fn) {
          for (const item of arr) {
            if (fn(item)) return item;
          }
          return null;
        }

        function extractVisible() {
          const cards = [...document.querySelectorAll('[role="article"]')];
          for (const card of cards) {
            if (card.querySelector('[role="status"]') || card.getAttribute('data-visualcompletion') === 'loading-state') {
              continue;
            }

            const fullText = text(card);
            if (!fullText) continue;

            const links = [...card.querySelectorAll('a[href]')];
            const postA = firstMatch(links, (a) => {
              const href = a.href || '';
              return /\\/groups\\/\\d+\\/(?:permalink|posts)\\//.test(href) && !href.includes('comment_id=');
            }) || firstMatch(links, (a) => /\\/posts\\//.test(a.href || ''));

            const url = postA?.href || '';
            const idMatch = url.match(/(?:posts|permalink)\\/(\\d+)/);
            const id = idMatch?.[1] || url || fullText.substring(0, 50);

            if (accumulated[id]) continue;

            const lines = fullText.split('\\n').map(s => s.trim()).filter(Boolean);
            const author = lines[0] || '';

            let time = '';
            const dotIdx = lines.findIndex(l => l === '·' || l === '•' || l.startsWith('·') || l.startsWith('•') || l.endsWith('·') || l.endsWith('•'));
            if (dotIdx > 0) {
              time = lines[dotIdx - 1];
            } else if (lines[1] && (lines[1].includes('小时') || lines[1].includes('小時') || lines[1].includes('分钟') || lines[1].includes('分鐘') || lines[1].includes('天') || lines[1].includes('月') || lines[1].includes('年') || lines[1].includes('昨日') || lines[1].includes('昨天') || /\\d/.test(lines[1]))) {
              time = lines[1];
            }

            if (!time) {
              const timeCandidateEls = [
                ...card.querySelectorAll('abbr'),
                ...card.querySelectorAll('span[aria-label]'),
                ...card.querySelectorAll('a[aria-label]')
              ];
              time = (timeCandidateEls.map(el => el.getAttribute('aria-label') || el.textContent || '').find(Boolean) || '').trim();
            }

            const imageUrls = [...card.querySelectorAll('img[src]')]
              .map(img => img.getAttribute('src') || '')
              .filter(src => src && !src.startsWith('data:'));

            accumulated[id] = {
              id,
              url,
              author,
              time,
              fullText,
              textLines: lines.slice(0, 15),
              imageCount: imageUrls.length,
            };
          }
        }

        let lastScrollHeight = 0;
        let scrollHeightsChanged = false;

        extractVisible();

        while (scrolls < maxScrolls) {
          lastScrollHeight = document.documentElement.scrollHeight;
          document.documentElement.scrollTop = document.documentElement.scrollHeight;
          window.dispatchEvent(new Event('scroll'));
          document.dispatchEvent(new Event('scroll'));
          await sleep(2500);
          if (document.documentElement.scrollHeight > lastScrollHeight) {
            scrollHeightsChanged = true;
          }
          extractVisible();
          scrolls++;
        }

        resolve(JSON.stringify({
          posts: Object.values(accumulated),
          scrollHeightsChanged,
          visibilityState: document.visibilityState
        }));
      })
    `;

    let result = { posts: [], scrollHeightsChanged: false, visibilityState: 'visible' };
    try {
      const postsOutput = runBrowserTool(tool, ['evaluate', '--session', sessionId, '--tab-id', String(tabId), '--timeout', '90s', extractionJs]);
      result = JSON.parse(postsOutput);
    } catch (e) {
      console.error('Failed to parse extraction results:', e.message);
    }

    const rawPosts = result.posts || [];
    console.log(`Found ${rawPosts.length} raw posts on the page via ${tool}.`);

    const isThrottled = (result.visibilityState === 'hidden') && (rawPosts.length <= 1) && (!result.scrollHeightsChanged);
    if (isThrottled) {
      console.warn(`[Warning] Group page extraction appears to be throttled/minimized (visibilityState: ${result.visibilityState}, found ${rawPosts.length} posts, scroll height did not change). We will NOT update the last check time for this run.`);
      anyThrottleOrFailure = true;
    }

    const filteredPosts = [];
    for (const post of rawPosts) {
      const postDate = parseTimeToDate(post.time, currentCheckTime);
      if (postDate && postDate >= lastCheckDate && postDate <= endCheckDate) {
        filteredPosts.push({
          ...post,
          postDate: postDate.toISOString()
        });
      }
    }

    console.log(`Filtered: ${filteredPosts.length} new posts since ${lastCheckDate.toISOString()}`);
    reportData.push({
      groupUrl: url,
      groupName,
      posts: filteredPosts
    });
  }

  function getPostTitleAndSummary(textLines, post) {
    const cleanLines = textLines.map(line => line.trim()).filter(line => {
      if (!line) return false;
      const lowerLine = line.toLowerCase();
      if (post.author && lowerLine.includes(post.author.toLowerCase())) return false;
      if (post.time && lowerLine === post.time.toLowerCase()) return false;
      const trimmed = line.trim();
      if (trimmed === '赞' || trimmed === '讚' || trimmed === '赞好' || trimmed === '讚好' || trimmed === '评论' || trimmed === '評論' || trimmed === '分享' || trimmed === '回复' || trimmed === '回覆' || trimmed === '关注' || trimmed === '關注') {
        return false;
      }
      if (/^\d+$/.test(trimmed)) return false;
      if (trimmed.includes('查看') && (trimmed.includes('评论') || trimmed.includes('回覆') || trimmed.includes('回复'))) return false;
      if (line.includes('条评论') || line.includes('条回覆') || line.includes('分享') || line.includes('赞') || line.includes('所有心情') || line.includes('·') || line.startsWith('以 ')) return false;
      return true;
    });

    let title = cleanLines[0] || '无文字内容';
    if (title.length > 40) title = title.substring(0, 40) + '...';

    let summary = cleanLines.slice(1, 3).join(' ') || '无更多详情';
    if (summary.length > 100) {
      summary = summary.substring(0, 100) + '...';
    } else if (!summary && cleanLines[0] && cleanLines[0].length > 40) {
      summary = cleanLines[0].substring(40, 140);
    }

    return { title, summary };
  }

  let summaryTextLines = [];
  summaryTextLines.push(`【Facebook群组新动态播报】`);
  summaryTextLines.push(`⚙️ 抓取工具: ${tool}`);
  summaryTextLines.push(`📅 时间区间:\n${lastCheckDate.toLocaleString('zh-CN', { timeZone: TZ })}\n至\n${currentCheckTime.toLocaleString('zh-CN', { timeZone: TZ })}\n`);

  for (const group of reportData) {
    summaryTextLines.push(`📌 ${group.groupName} (${group.posts.length}条新帖)`);
    if (group.posts.length === 0) {
      summaryTextLines.push(`  (监控区间内无新贴)`);
    } else {
      group.posts.forEach((post, idx) => {
        const { title, summary } = getPostTitleAndSummary(post.textLines, post);
        summaryTextLines.push(`  ${idx + 1}. 作者: ${post.author} (${post.time})`);
        summaryTextLines.push(`     - 主题: ${title}`);
        summaryTextLines.push(`     - 摘要: ${summary}`);
      });
    }
    summaryTextLines.push('');
  }

  summaryTextLines.push(`详细日报已生成，可在看板或日志中查看。`);
  const summary_text = summaryTextLines.join('\n');

  if (anyThrottleOrFailure) {
    console.log('\n[Notice] Last check time was NOT updated because some group extractions were throttled or failed. It will retry catching up in the next run.');
  } else {
    try {
      fs.mkdirSync(path.dirname(lastCheckFile), { recursive: true });
      fs.writeFileSync(lastCheckFile, JSON.stringify({ last_check_time: endCheckDate.toISOString() }, null, 2), 'utf8');
      console.log(`\nUpdated last check time in fb_last_check.json: ${endCheckDate.toISOString()}`);
    } catch (e) {
      console.warn('Failed to write fb_last_check.json:', e.message);
    }
  }

  const summaryObj = { summary_text };
  console.log('\n---JSON_SUMMARY_START---');
  console.log(JSON.stringify(summaryObj, null, 2));
  console.log('---JSON_SUMMARY_END---');
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
