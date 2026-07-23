const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const BSK_PATH = 'C:\\\\Users\\\\40282\\\\.local\\\\bin\\\\bsk.exe';
const TZ = 'Asia/Shanghai';

// Helper to wait
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// Run bsk command and return output
function runBsk(args) {
  try {
    return execFileSync(BSK_PATH, args, { encoding: 'utf8' }).trim();
  } catch (err) {
    console.error(`Error running bsk with args [${args.join(', ')}]:`, err.message);
    if (err.stdout) console.error('stdout:', err.stdout);
    if (err.stderr) console.error('stderr:', err.stderr);
    throw err;
  }
}

// Get active session
function getActiveSession() {
  const output = runBsk(['session', 'list', '--json']);
  try {
    const sessions = JSON.parse(output);
    if (sessions && sessions.length > 0) {
      return sessions[0].session_id;
    }
  } catch (e) {
    // Ignore and try to start
  }
  
  console.log('No active session found. Starting a new session...');
  const newSessionId = runBsk(['session', 'start']);
  console.log(`Started session: ${newSessionId}`);
  return newSessionId;
}

// Get active tab
function getActiveTab(sessionId) {
  const output = runBsk(['tab', 'list', '--session', sessionId, '--json']);
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
      runBsk(['tab', 'borrow', String(activeTab.tab_id), '--session', sessionId]);
    } catch (e) {
      console.warn('Failed to borrow tab:', e.message);
    }
    return activeTab.tab_id;
  }
  throw new Error('No tabs found in session');
}


// Parse time text to Date object
function parseTimeToDate(timeText, referenceDate = new Date()) {
  if (!timeText) return null;
  const s = timeText.trim().toLowerCase();
  if (!s) return null;

  const date = new Date(referenceDate);

  // Minutes check
  const minMatch = s.match(/(\d+)\s*(?:分钟|分钟前|m|min|mins|minute|minutes)/);
  if (minMatch) {
    const m = parseInt(minMatch[1], 10);
    date.setMinutes(date.getMinutes() - m);
    return date;
  }

  // Hours check
  const hourMatch = s.match(/(\d+)\s*(?:小时|小时前|小時|小時前|h|hr|hrs|hour|hours)/);
  if (hourMatch) {
    const h = parseInt(hourMatch[1], 10);
    date.setHours(date.getHours() - h);
    return date;
  }

  // Days check
  const dayMatch = s.match(/(\d+)\s*(?:天|天前|d|day|days)/);
  if (dayMatch) {
    const d = parseInt(dayMatch[1], 10);
    date.setDate(date.getDate() - d);
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

  // Date check (e.g., 2026年6月21日 or 6月21日)
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


// Extract date key

function extractDateKey(timeText, nowYmd) {
  if (!timeText) return null;
  const s = timeText.trim().toLowerCase();
  if (!s) return null;

  const now = new Date(`${nowYmd}T12:00:00+08:00`);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const prevYmd = [yesterday.getFullYear(), String(yesterday.getMonth() + 1).padStart(2, '0'), String(yesterday.getDate()).padStart(2, '0')].join('-');

  if (s.includes('昨天') || s.includes('yesterday') || s.includes('1天') || s.includes('1 d') || s.includes('1d')) {
    return prevYmd;
  }
  if (s.includes('今天') || s.includes('today') || s.includes('分钟') || s.includes('m') || s.includes('刚刚') || s.includes('just now')) {
    return nowYmd;
  }

  // Hours check
  const hourMatch = s.match(/(\d+)\s*(?:小时|小時|hour|h)/);
  if (hourMatch) {
    const h = parseInt(hourMatch[1], 10);
    const postDate = new Date(Date.now() - h * 60 * 60 * 1000);
    const y = postDate.getFullYear();
    const m = String(postDate.getMonth() + 1).padStart(2, '0');
    const d = String(postDate.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  // Exact dates
  let m = s.match(/(20\d{2})[\/-](\d{1,2})[\/-](\d{1,2})/);
  if (m) return `${m[1]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}`;

  m = s.match(/(\d{1,2})月(\d{1,2})[日号]?/);
  if (m) {
    const year = nowYmd.slice(0, 4);
    return `${year}-${String(m[1]).padStart(2, '0')}-${String(m[2]).padStart(2, '0')}`;
  }

  return null;
}

async function main() {
  const projectRoot = path.resolve(__dirname, '../..');
  const groupsFile = path.join(projectRoot, 'state/facebook/fb_groups.json');
  
  let groups = [
    'https://www.facebook.com/groups/273979355317477',
    'https://www.facebook.com/groups/982872103263383/',
    'https://www.facebook.com/groups/644345363776357'
  ];
  
  if (fs.existsSync(groupsFile)) {
    try {
      const config = JSON.parse(fs.readFileSync(groupsFile, 'utf8'));
      if (config.groups && config.groups.length > 0) {
        groups = config.groups;
      }
    } catch (e) {
      console.warn('Error reading fb_groups.json, using defaults:', e.message);
    }
  }

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

  // Helpers to handle Macau local timezone date calculations
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
    const getPart = (type) => parseInt(parts.find(p => p.type === type).value, 10);
    return {
      year: getPart('year'),
      month: getPart('month') - 1, // 0-based
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

  const formatYmd = (date) => {
    const localDate = new Date(date.toLocaleString('en-US', { timeZone: TZ }));
    return [localDate.getFullYear(), String(localDate.getMonth() + 1).padStart(2, '0'), String(localDate.getDate()).padStart(2, '0')].join('-');
  };
  const targetDate = formatYmd(lastCheckDate);

  console.log(`Current Check Time: ${currentCheckTime.toISOString()}`);
  console.log(`Filter Window:      ${lastCheckDate.toISOString()} to ${endCheckDate.toISOString()}`);


  const sessionId = getActiveSession();
  const tabId = getActiveTab(sessionId);
  console.log(`Using Session: ${sessionId}, Tab: ${tabId}`);


  try {
    console.log(`Activating/Focusing tab ${tabId}...`);
    runBsk(['tab', 'select', String(tabId), '--session', sessionId]);
  } catch (e) {
    console.warn('Failed to select tab:', e.message);
  }


  const reportData = [];
  let anyThrottleOrFailure = false;


  for (let i = 0; i < groups.length; i++) {
    const url = groups[i];
    
    // Append chronological sorting parameter
    let targetUrl = url;
    if (targetUrl.includes('?')) {
      targetUrl += '&sorting_setting=CHRONOLOGICAL';
    } else {
      targetUrl = targetUrl.replace(/\/$/, '') + '/?sorting_setting=CHRONOLOGICAL';
    }
    
    console.log(`\n[${i+1}/${groups.length}] Navigating to: ${targetUrl}`);
    runBsk(['navigate', '--session', sessionId, '--tab-id', tabId, '--timeout', '90s', targetUrl]);
    await sleep(6000); // wait for load

    // Get title
    let title = runBsk(['evaluate', '--session', sessionId, '--tab-id', tabId, 'document.title']);
    const groupName = title.replace(/\(\d+\+\)\s*/, '').split('|')[0].replace(/#|@/g, '').trim();
    console.log(`Group Name: ${groupName}`);

    const extractionJs = `
      new Promise(async (resolve) => {
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        
        const accumulated = {};
        let scrolls = 0;
        let maxScrolls = 8;

        function text(el) {
          return (el?.innerText || '').replace(/\\n{3,}/g, '\\n\\n').trim();
        }

        function firstMatch(elements, predicate) {
          for (const el of elements) {
            try {
              if (predicate(el)) return el;
            } catch (_) {}
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

            // Robust text-based time extraction from visual lines
            let time = '';
            const dotIdx = lines.findIndex(l => l === '·' || l === '•' || l.startsWith('·') || l.startsWith('•') || l.endsWith('·') || l.endsWith('•'));
            if (dotIdx > 0) {
              time = lines[dotIdx - 1];
            } else if (lines[1] && (lines[1].includes('小时') || lines[1].includes('小時') || lines[1].includes('分钟') || lines[1].includes('分鐘') || lines[1].includes('天') || lines[1].includes('月') || lines[1].includes('年') || lines[1].includes('昨日') || lines[1].includes('昨天') || /\\d/.test(lines[1]))) {
              time = lines[1];
            }

            // Fallback to selectors if text parsing is empty
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
      const postsOutput = runBsk(['evaluate', '--session', sessionId, '--tab-id', tabId, '--timeout', '90s', extractionJs]);
      result = JSON.parse(postsOutput);
    } catch (e) {
      console.error('Failed to parse extraction results:', e.message);
    }

    const rawPosts = result.posts || [];
    console.log(`Found ${rawPosts.length} raw posts on the page.`);

    // Check if throttled (only flag if tab/window is hidden AND scroll height didn't change with <= 1 post)
    const isThrottled = (result.visibilityState === 'hidden') && (rawPosts.length <= 1) && (!result.scrollHeightsChanged);
    if (isThrottled) {
      console.warn(`[Warning] Group page extraction appears to be throttled/minimized (visibilityState: ${result.visibilityState}, found ${rawPosts.length} posts, scroll height did not change). We will NOT update the last check time for this run.`);
      anyThrottleOrFailure = true;
    }

    // Filter posts between last check time and current check time
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
      groupName,
      url,
      posts: filteredPosts
    });
  }

  // Generate markdown report
  const reportLines = [];
  reportLines.push(`# 📊 Facebook 群组新动态日报`);
  reportLines.push(`- **监控区间**：${lastCheckDate.toLocaleString('zh-CN', { timeZone: TZ })} 至 ${currentCheckTime.toLocaleString('zh-CN', { timeZone: TZ })}`);
  reportLines.push(`- **提取时间**：${currentCheckTime.toLocaleString('zh-CN', { timeZone: TZ })}`);
  reportLines.push(`- **提取会话**：BrowserSkill ${sessionId}`);
  reportLines.push('');


  for (const group of reportData) {
    reportLines.push(`## 📌 ${group.groupName}`);
    reportLines.push(`- **链接**：[${group.groupName}](${group.url})`);
    reportLines.push(`- **昨日帖子数**：${group.posts.length}`);
    reportLines.push('');

    if (group.posts.length === 0) {
      reportLines.push(`*该群组昨日无新贴或未成功抓取。*`);
    } else {
      group.posts.forEach((post, idx) => {
        reportLines.push(`### ${idx + 1}. 作者：${post.author} (${post.time})`);
        if (post.url) {
          reportLines.push(`- **帖子链接**：${post.url}`);
        }
        const cleanText = post.textLines.join('\n').trim();
        reportLines.push(`- **帖子内容**：`);
        reportLines.push('```');
        reportLines.push(cleanText.substring(0, 1000));
        if (cleanText.length > 1000) reportLines.push('... (内容已截断)');
        reportLines.push('```');
        reportLines.push('');
      });
    }
    reportLines.push('---');
    reportLines.push('');
  }

  const outputDir = path.join(projectRoot, 'tmp/fb_yesterday_summary');
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const reportContent = reportLines.join('\n');
  const reportFilePath = path.join(outputDir, `fb_yesterday_summary_${targetDate}.md`);
  fs.writeFileSync(reportFilePath, reportContent, 'utf8');
  console.log(`\nReport generated at: ${reportFilePath}`);
  console.log(reportContent);

  // Helper to extract post title and summary
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
      
      if (/^\d+$/.test(trimmed)) {
        return false; // Reaction or comment counts
      }
      
      if (trimmed.includes('查看') && (trimmed.includes('评论') || trimmed.includes('回覆') || trimmed.includes('回复'))) {
        return false; // "View more comments" text
      }
      
      if (line.includes('条评论') || line.includes('条回覆') || line.includes('分享') || line.includes('赞') || line.includes('所有心情') || line.includes('·') || line.startsWith('以 ')) {
        return false;
      }
      return true;
    });



    let title = cleanLines[0] || '无文字内容';
    if (title.length > 40) {
      title = title.substring(0, 40) + '...';
    }

    let summary = cleanLines.slice(1, 3).join(' ') || '无更多详情';
    if (summary.length > 100) {
      summary = summary.substring(0, 100) + '...';
    } else if (!summary && cleanLines[0] && cleanLines[0].length > 40) {
      summary = cleanLines[0].substring(40, 140);
    }

    return { title, summary };
  }

  // Format detailed summary_text for Telegram and Dashboard
  let summaryTextLines = [];
  summaryTextLines.push(`【Facebook群组新动态播报】`);
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
    // Write the updated check time back to the sync file
    try {
      fs.mkdirSync(path.dirname(lastCheckFile), { recursive: true });
      fs.writeFileSync(lastCheckFile, JSON.stringify({ last_check_time: endCheckDate.toISOString() }, null, 2), 'utf8');
      console.log(`\nUpdated last check time in fb_last_check.json: ${endCheckDate.toISOString()}`);

    } catch (e) {
      console.warn('Failed to write fb_last_check.json:', e.message);
    }
  }



  // Print JSON summary for traeclaw runner to parse
  const summaryObj = {
    summary_text
  };
  console.log('\n---JSON_SUMMARY_START---');
  console.log(JSON.stringify(summaryObj, null, 2));
  console.log('---JSON_SUMMARY_END---');
}




main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
