#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const os = require('os');

function requirePlaywright() {
  const candidates = [
    'playwright',
    path.join(
      os.homedir(),
      '.cache',
      'codex-runtimes',
      'codex-primary-runtime',
      'dependencies',
      'node',
      'node_modules',
      'playwright'
    ),
    '/home/eric/Documents/workspace/.tmp/fbprobe/node_modules/playwright'
  ];

  let lastError;
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      lastError = error;
    }
  }

  console.error('[blocked] Missing dependency: playwright');
  console.error(`Unable to load playwright. Last error: ${lastError && lastError.message}`);
  process.exit(2);
}

const { chromium } = requirePlaywright();

const TZ = 'Asia/Shanghai';
const DEFAULT_GROUPS = [
  'https://www.facebook.com/groups/273979355317477',
  'https://www.facebook.com/groups/982872103263383/',
  'https://www.facebook.com/groups/644345363776357'
];

const PROJECT_ROOT = process.env.TRAECLAW_PROJECT_ROOT || path.resolve(__dirname, '../../..');
const DEFAULT_STATE_FILE = path.join(PROJECT_ROOT, 'state/facebook/fb_storage_state.json');
const DEFAULT_OUTPUT_DIR = path.join(PROJECT_ROOT, 'tmp/fb_yesterday_summary');
const DEFAULT_CHROME = os.platform() === 'darwin'
  ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
  : (os.platform() === 'win32'
      ? (fs.existsSync('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')
          ? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
          : 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe')
      : '/usr/bin/google-chrome-stable');

function parseArgs(argv) {
  const args = {
    groups: null,
    config: null,
    stateFile: DEFAULT_STATE_FILE,
    outputDir: DEFAULT_OUTPUT_DIR,
    chromePath: DEFAULT_CHROME,
    date: null,
    headed: false,
    login: false,
    maxPosts: 12,
    scrolls: 8,
    groupWaitMs: 4000,
    requestTimeoutMs: 45000,
    json: false,
    saveHtml: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    switch (arg) {
      case '--groups':
        args.groups = next.split(',').map(s => s.trim()).filter(Boolean);
        i += 1;
        break;
      case '--config':
        args.config = next;
        i += 1;
        break;
      case '--state-file':
        args.stateFile = next;
        i += 1;
        break;
      case '--output-dir':
        args.outputDir = next;
        i += 1;
        break;
      case '--chrome-path':
        args.chromePath = next;
        i += 1;
        break;
      case '--date':
        args.date = next;
        i += 1;
        break;
      case '--max-posts':
        args.maxPosts = Number(next);
        i += 1;
        break;
      case '--scrolls':
        args.scrolls = Number(next);
        i += 1;
        break;
      case '--group-wait-ms':
        args.groupWaitMs = Number(next);
        i += 1;
        break;
      case '--timeout-ms':
        args.requestTimeoutMs = Number(next);
        i += 1;
        break;
      case '--headed':
        args.headed = true;
        break;
      case '--login':
        args.login = true;
        args.headed = true;
        break;
      case '--json':
        args.json = true;
        break;
      case '--save-html':
        args.saveHtml = true;
        break;
      case '--help':
      case '-h':
        printHelp();
        process.exit(0);
      default:
        if (arg.startsWith('--')) {
          throw new Error(`Unknown argument: ${arg}`);
        }
    }
  }
  return args;
}

function printHelp() {
  console.log(`fb_yesterday_summary.js

Usage:
  npx -y -p playwright node fb_yesterday_summary.js [options]

Options:
  --config <json>         JSON config with { groups: [] }
  --groups <a,b,c>        Comma-separated Facebook group URLs
  --state-file <file>     Playwright storageState file (default: ${DEFAULT_STATE_FILE})
  --output-dir <dir>      Output dir for markdown/json/html
  --chrome-path <path>    Chrome executable path (default: ${DEFAULT_CHROME})
  --date <YYYY-MM-DD>     Target date; default = yesterday in Asia/Shanghai
  --max-posts <n>         Max matched posts per group (default: 12)
  --scrolls <n>           Scroll rounds per group (default: 8)
  --group-wait-ms <ms>    Initial wait after loading group page (default: 4000)
  --timeout-ms <ms>       Navigation timeout (default: 45000)
  --headed                Run with visible Chrome window
  --login                 Visible mode for first-time manual login; wait for Enter to continue
  --json                  Also print JSON result to stdout
  --save-html             Save page HTML snapshots for debugging
`);
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function loadGroups(args) {
  if (args.groups?.length) return args.groups;
  if (args.config) {
    const config = JSON.parse(fs.readFileSync(args.config, 'utf8'));
    if (Array.isArray(config.groups) && config.groups.length) return config.groups;
  }
  return DEFAULT_GROUPS;
}

function getTargetDate(input) {
  if (input) return input;
  const now = new Date();
  const date = new Date(now.toLocaleString('en-US', { timeZone: TZ }));
  date.setDate(date.getDate() - 1);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function slugifyGroupUrl(url, index) {
  const match = url.match(/groups\/(\d+)/);
  return match ? `group_${index + 1}_${match[1]}` : `group_${index + 1}`;
}

function formatDateForTitle(ymd) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(`${ymd}T00:00:00+08:00`)).replace(/\//g, '-');
}

function normalizeWhitespace(text) {
  return String(text || '').replace(/\u00a0/g, ' ').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
}

function clip(text, limit = 140) {
  const normalized = normalizeWhitespace(text).replace(/\n/g, ' / ');
  return normalized.length <= limit ? normalized : `${normalized.slice(0, limit - 1)}…`;
}

function safeJsonWrite(filePath, data) {
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8');
}

function extractDateKey(raw, nowYmd) {
  if (!raw) return null;
  const s = raw.trim();
  if (!s) return null;

  const yesterday = new Date(`${nowYmd}T00:00:00+08:00`);
  yesterday.setDate(yesterday.getDate() - 1);
  const prevYmd = [yesterday.getFullYear(), String(yesterday.getMonth() + 1).padStart(2, '0'), String(yesterday.getDate()).padStart(2, '0')].join('-');

  if (/昨天/.test(s)) return prevYmd;
  if (/今天|今日/.test(s)) return nowYmd;

  let m = s.match(/(20\d{2})[\/-](\d{1,2})[\/-](\d{1,2})/);
  if (m) return `${m[1]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}`;

  m = s.match(/(\d{1,2})月(\d{1,2})[日号]?/);
  if (m) {
    const year = nowYmd.slice(0, 4);
    return `${year}-${String(m[1]).padStart(2, '0')}-${String(m[2]).padStart(2, '0')}`;
  }

  m = s.match(/\b([A-Z][a-z]{2,8})\s+(\d{1,2})(?:,\s*(20\d{2}))?/);
  if (m) {
    const monthMap = { jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4, may: 5, jun: 6, june: 6, jul: 7, july: 7, aug: 8, august: 8, sep: 9, sept: 9, september: 9, oct: 10, october: 10, nov: 11, november: 11, dec: 12, december: 12 };
    const month = monthMap[m[1].toLowerCase()];
    if (month) {
      const year = m[3] || nowYmd.slice(0, 4);
      return `${year}-${String(month).padStart(2, '0')}-${String(m[2]).padStart(2, '0')}`;
    }
  }

  return null;
}

function summarizePosts(posts) {
  if (!posts.length) return '昨日未提取到可判定為目標日期的帖子。';
  return posts.slice(0, 5).map((post, idx) => {
    const lines = [];
    lines.push(`${idx + 1}. ${post.author || '未知作者'}｜${post.time || '時間未識別'}`);
    if (post.textSummary) lines.push(`   摘要：${post.textSummary}`);
    if (post.imageCount) lines.push(`   圖片：${post.imageCount} 張`);
    if (post.url) lines.push(`   連結：${post.url}`);
    return lines.join('\n');
  }).join('\n');
}

function buildMarkdownReport(result) {
  const lines = [];
  lines.push(`# Facebook 昨日內容總結`);
  lines.push(`- 日期：${formatDateForTitle(result.targetDate)}`);
  lines.push(`- 群組數：${result.groups.length}`);
  lines.push('');

  for (const group of result.groups) {
    lines.push(`## ${group.label}`);
    lines.push(`- 來源：${group.url}`);
    lines.push(`- 昨日帖子數：${group.posts.length}`);
    if (group.note) lines.push(`- 備註：${group.note}`);
    lines.push('');
    lines.push(summarizePosts(group.posts));
    lines.push('');
  }

  return lines.join('\n');
}

async function autoScroll(page, rounds) {
  for (let i = 0; i < rounds; i += 1) {
    await page.mouse.wheel(0, 2200);
    await page.waitForTimeout(1300);
  }
}

async function extractPosts(page, targetDate, maxPosts) {
  const nowYmd = (() => {
    const now = new Date();
    const local = new Date(now.toLocaleString('en-US', { timeZone: TZ }));
    const y = local.getFullYear();
    const m = String(local.getMonth() + 1).padStart(2, '0');
    const d = String(local.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  })();

  const rawPosts = await page.evaluate(() => {
    const seen = new Set();
    const cards = [...document.querySelectorAll('[role="article"]')];
    const out = [];

    function text(el) {
      return (el?.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
    }

    function firstMatch(elements, predicate) {
      for (const el of elements) {
        try {
          if (predicate(el)) return el;
        } catch (_) {}
      }
      return null;
    }

    for (const card of cards) {
      const links = [...card.querySelectorAll('a[href]')];
      const postA = firstMatch(links, (a) => {
        const href = a.href || '';
        return /\/groups\/\d+\/(?:permalink|posts)\//.test(href) && !href.includes('comment_id=');
      }) || firstMatch(links, (a) => /\/posts\//.test(a.href || ''));

      const url = postA?.href || '';
      const idMatch = url.match(/(?:posts|permalink)\/(\d+)/);
      const id = idMatch?.[1] || url;
      if (!id || seen.has(id)) continue;
      seen.add(id);

      const fullText = text(card);
      if (!fullText) continue;
      const lines = fullText.split('\n').map(s => s.trim()).filter(Boolean);
      const author = lines[0] || '';

      const timeCandidateEls = [
        ...card.querySelectorAll('a[aria-label]'),
        ...card.querySelectorAll('abbr'),
        ...card.querySelectorAll('span[aria-label]')
      ];
      const time = (timeCandidateEls.map(el => el.getAttribute('aria-label') || el.textContent || '').find(Boolean) || '').trim();

      const imageUrls = [...card.querySelectorAll('img[src]')]
        .map(img => img.getAttribute('src') || '')
        .filter(src => src && !src.startsWith('data:'));

      out.push({
        id,
        url,
        author,
        time,
        fullText,
        textLines: lines.slice(0, 60),
        imageCount: imageUrls.length,
      });
    }
    return out;
  });

  const filtered = [];
  for (const post of rawPosts) {
    const dateKey = extractDateKey(post.time, nowYmd);
    if (dateKey !== targetDate) continue;
    filtered.push({
      id: post.id,
      url: post.url,
      author: post.author,
      time: post.time,
      dateKey,
      imageCount: post.imageCount,
      textSummary: clip(post.textLines.join(' '), 180),
      rawText: post.fullText,
    });
    if (filtered.length >= maxPosts) break;
  }

  return filtered;
}

async function waitForManualLogin(page) {
  console.log('請在打開的 Chrome 內完成 Facebook 登入。');
  console.log('登入完成後，返回終端按 Enter 繼續。');
  await page.goto('https://www.facebook.com/', { waitUntil: 'domcontentloaded' });
  await new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once('data', () => resolve());
  });
}

function getContextOptions(args) {
  const options = {
    viewport: { width: 1440, height: 1600 },
    locale: 'zh-CN',
    timezoneId: TZ,
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
  };

  if (!args.login && args.stateFile && fs.existsSync(args.stateFile)) {
    options.storageState = args.stateFile;
  }

  return options;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const groups = loadGroups(args);
  const targetDate = getTargetDate(args.date);
  ensureDir(args.outputDir);
  ensureDir(path.dirname(args.stateFile));

  let browser;
  let context;
  let page;
  let isCDP = false;

  try {
    const cdpCheck = await fetch('http://127.0.0.1:9222/json/version', { signal: AbortSignal.timeout(1000) });
    if (cdpCheck.ok) {
      console.log('檢測到已運行的 Chrome (Port 9222)，正在連接並使用現有瀏覽器會話...');
      browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
      context = browser.contexts()[0];
      page = await context.newPage();
      isCDP = true;
    }
  } catch (e) {
    // Port 9222 not open or connection refused, fallback to launching new browser
  }

  if (!isCDP) {
    const launchOptions = {
      headless: !args.headed,
      args: [
        '--disable-blink-features=AutomationControlled',
        '--no-first-run',
        '--disable-dev-shm-usage'
      ],
    };
    if (fs.existsSync(args.chromePath)) {
      launchOptions.executablePath = args.chromePath;
    }
    browser = await chromium.launch(launchOptions);
    context = await browser.newContext(getContextOptions(args));
    page = await context.newPage();
  }

  try {
    context.setDefaultNavigationTimeout(args.requestTimeoutMs);
    context.setDefaultTimeout(args.requestTimeoutMs);

    if (!isCDP) {
      if (args.login) {
        await waitForManualLogin(page);
        await context.storageState({ path: args.stateFile });
        console.log(`已保存登入態到：${args.stateFile}`);
      } else if (args.stateFile && !fs.existsSync(args.stateFile)) {
        console.error(`[blocked] 尚未找到登入態文件：${args.stateFile}`);
        console.error('先執行一次：fb_yesterday_summary.sh --login');
        process.exit(2);
      }
    }

    const result = {
      targetDate,
      generatedAt: new Date().toISOString(),
      groups: [],
    };

    for (let i = 0; i < groups.length; i += 1) {
      const url = groups[i];
      const slug = slugifyGroupUrl(url, i);
      const label = `群組 ${i + 1}`;
      const groupResult = { label, url, posts: [] };
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(args.groupWaitMs);
        await autoScroll(page, args.scrolls);
        groupResult.posts = await extractPosts(page, targetDate, args.maxPosts);
        if (!groupResult.posts.length) {
          groupResult.note = '未抓到昨日帖子；可能是當日無貼文、登入態失效，或 Facebook DOM/日期格式有變。';
        }
        if (args.saveHtml) {
          fs.writeFileSync(path.join(args.outputDir, `${slug}.html`), await page.content(), 'utf8');
        }
      } catch (error) {
        groupResult.note = `抓取失敗：${error.message}`;
      }
      result.groups.push(groupResult);
    }

    const markdown = buildMarkdownReport(result);
    fs.writeFileSync(path.join(args.outputDir, `fb_yesterday_summary_${targetDate}.md`), markdown, 'utf8');
    safeJsonWrite(path.join(args.outputDir, `fb_yesterday_summary_${targetDate}.json`), result);

    if (args.json) {
      console.log(JSON.stringify(result, null, 2));
    } else {
      console.log(markdown);
    }
  } finally {
    if (isCDP) {
      if (page) {
        await page.close();
      }
      await browser.disconnect();
    } else {
      if (context) {
        await context.close();
      }
      if (browser) {
        await browser.close();
      }
    }
  }
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
