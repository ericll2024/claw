#!/usr/bin/env node

const crypto = require("crypto");
const fs = require("fs");
const https = require("https");
const os = require("os");
const path = require("path");

const MANAGER_ORIGIN = "https://manager.mfoodapp.com";
const LOGIN_URL = "https://management-api.mfoodapp.com/token/_get";
const VALIDATE_URL =
  "https://management-api.mfoodapp.com/managers/orgs/users/_getName";
const SIGNING_SECRET = "5fde65edc94340458a4411d412bdc454";
const DEFAULT_USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36";
const DEFAULT_BROWSER_LANGUAGE = "zh";
const DEFAULT_PLATFORM = "MacIntel";

function defaultStateDir() {
  const codexHome =
    process.env.CODEX_HOME || path.join(os.homedir(), ".codex");
  const currentDir = path.join(codexHome, "state", "mfood_login_skill");
  const legacyDir = path.join(codexHome, "state", "mfood-token");
  if (!fs.existsSync(currentDir) && fs.existsSync(legacyDir)) {
    return legacyDir;
  }
  return currentDir;
}

function defaultCachePath() {
  return path.join(defaultStateDir(), "cache.json");
}

function defaultDefaultsPath() {
  return path.join(defaultStateDir(), "defaults.json");
}

function usage() {
  return [
    "Usage:",
    "  run_mfood_token.sh [--profile PROFILE]",
    "  run_mfood_token.sh --account ACCOUNT [--password PASSWORD | --password-md5 MD5]",
    "",
    "Options:",
    "  --profile PROFILE         Use a saved profile from defaults.json",
    "  --account ACCOUNT         mFood manager account",
    "  --password PASSWORD       Plaintext password; the script stores only md5",
    "  --password-md5 MD5        Pre-hashed password",
    "  --save-profile PROFILE    Save the resolved account into this profile",
    "  --make-default            Set selected/saved profile as default",
    "  --list-profiles           Print configured profiles and exit",
    "  --force-refresh           Skip cache validation and log in again",
    "  --cache-path PATH         Override cache path",
    "  --defaults-path PATH      Override defaults config path",
    "  --format json|text|external-json",
    "  --help                    Show this help",
  ].join("\n");
}

function parseArgs(argv) {
  const args = {
    forceRefresh: false,
    format: "json",
    cachePath: process.env.MFOOD_TOKEN_CACHE_PATH || defaultCachePath(),
    defaultsPath:
      process.env.MFOOD_TOKEN_DEFAULTS_PATH || defaultDefaultsPath(),
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") {
      args.help = true;
      continue;
    }
    if (arg === "--force-refresh") {
      args.forceRefresh = true;
      continue;
    }
    if (arg === "--profile") {
      args.profile = argv[++i];
      continue;
    }
    if (arg === "--account") {
      args.account = argv[++i];
      continue;
    }
    if (arg === "--password") {
      args.password = argv[++i];
      continue;
    }
    if (arg === "--password-md5") {
      args.passwordMd5 = argv[++i];
      continue;
    }
    if (arg === "--save-profile") {
      args.saveProfile = argv[++i];
      continue;
    }
    if (arg === "--make-default") {
      args.makeDefault = true;
      continue;
    }
    if (arg === "--list-profiles") {
      args.listProfiles = true;
      continue;
    }
    if (arg === "--cache-path") {
      args.cachePath = argv[++i];
      continue;
    }
    if (arg === "--defaults-path") {
      args.defaultsPath = argv[++i];
      continue;
    }
    if (arg === "--format") {
      args.format = argv[++i];
      continue;
    }
    throw new Error(`Unknown argument: ${arg}`);
  }

  if (!args.account) {
    args.account = process.env.MFOOD_ACCOUNT;
  }
  if (!args.password) {
    args.password = process.env.MFOOD_PASSWORD;
  }
  if (!args.passwordMd5) {
    args.passwordMd5 = process.env.MFOOD_PASSWORD_MD5;
  }
  if (!["json", "text", "external-json"].includes(args.format)) {
    throw new Error("--format must be json, text, or external-json");
  }

  return args;
}

function md5Hex(value) {
  return crypto.createHash("md5").update(value, "utf8").digest("hex");
}

function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch (error) {
    return null;
  }
}

function apiMessage(payload, fallback) {
  if (payload && typeof payload === "object") {
    if (payload.note) return String(payload.note);
    if (payload.message) return String(payload.message);
    if (payload.enNote) return String(payload.enNote);
    if (payload.detail) return String(payload.detail);
    if (payload.error) return String(payload.error);
  }
  return fallback;
}

function normalizePasswordMd5(args, cacheEntry) {
  if (args.passwordMd5) {
    const value = String(args.passwordMd5).trim().toLowerCase();
    if (!/^[0-9a-f]{32}$/.test(value)) {
      throw new Error("--password-md5 must be a 32-character lowercase hex md5");
    }
    return value;
  }
  if (args.password) {
    return md5Hex(String(args.password));
  }
  if (cacheEntry && cacheEntry.passwordMd5) {
    return String(cacheEntry.passwordMd5);
  }
  throw new Error(
    "Missing password. Provide --password or --password-md5 on first use.",
  );
}

function loadCache(cachePath) {
  if (!fs.existsSync(cachePath)) {
    return { version: 1, accounts: {} };
  }
  const raw = fs.readFileSync(cachePath, "utf8");
  const parsed = safeJsonParse(raw);
  if (!parsed || typeof parsed !== "object") {
    return { version: 1, accounts: {} };
  }
  if (!parsed.accounts || typeof parsed.accounts !== "object") {
    parsed.accounts = {};
  }
  if (!parsed.version) {
    parsed.version = 1;
  }
  return parsed;
}

function loadDefaults(defaultsPath) {
  const emptyConfig = { version: 2, defaultProfile: null, profiles: {} };
  if (!defaultsPath || !fs.existsSync(defaultsPath)) {
    return emptyConfig;
  }
  const raw = fs.readFileSync(defaultsPath, "utf8");
  const parsed = safeJsonParse(raw);
  if (!parsed || typeof parsed !== "object") {
    return emptyConfig;
  }
  const normalized = {
    version: 2,
    defaultProfile: null,
    profiles: {},
  };

  if (parsed.profiles && typeof parsed.profiles === "object") {
    for (const [profileName, value] of Object.entries(parsed.profiles)) {
      if (!value || typeof value !== "object") {
        continue;
      }
      const account = value.account || profileName;
      normalized.profiles[profileName] = {
        account: String(account),
        ...(value.password ? { password: String(value.password) } : {}),
        ...(value.passwordMd5
          ? { passwordMd5: String(value.passwordMd5).toLowerCase() }
          : {}),
      };
    }
  }

  if (parsed.accounts && typeof parsed.accounts === "object") {
    for (const [accountKey, value] of Object.entries(parsed.accounts)) {
      if (!value || typeof value !== "object") {
        continue;
      }
      const profileName = value.profileName || accountKey;
      const account = value.account || accountKey;
      normalized.profiles[profileName] = {
        account: String(account),
        ...(value.password ? { password: String(value.password) } : {}),
        ...(value.passwordMd5
          ? { passwordMd5: String(value.passwordMd5).toLowerCase() }
          : {}),
      };
    }
  }

  if (parsed.defaultProfile && normalized.profiles[parsed.defaultProfile]) {
    normalized.defaultProfile = parsed.defaultProfile;
  } else if (parsed.defaultAccount) {
    const byAccount = Object.entries(normalized.profiles).find(
      ([, value]) => value.account === parsed.defaultAccount,
    );
    if (byAccount) {
      normalized.defaultProfile = byAccount[0];
    }
  }

  if (!normalized.defaultProfile) {
    const firstProfile = Object.keys(normalized.profiles)[0];
    normalized.defaultProfile = firstProfile || null;
  }

  return normalized;
}

function saveDefaults(defaultsPath, defaults) {
  const dir = path.dirname(defaultsPath);
  fs.mkdirSync(dir, { recursive: true });
  const tmpPath = `${defaultsPath}.tmp-${process.pid}`;
  fs.writeFileSync(tmpPath, JSON.stringify(defaults, null, 2), {
    mode: 0o600,
  });
  fs.renameSync(tmpPath, defaultsPath);
  fs.chmodSync(defaultsPath, 0o600);
}

function saveCache(cachePath, cache) {
  const dir = path.dirname(cachePath);
  fs.mkdirSync(dir, { recursive: true });
  const tmpPath = `${cachePath}.tmp-${process.pid}`;
  fs.writeFileSync(tmpPath, JSON.stringify(cache, null, 2), {
    mode: 0o600,
  });
  fs.renameSync(tmpPath, cachePath);
  fs.chmodSync(cachePath, 0o600);
}

function buildSignedHeaders({
  userAgent = DEFAULT_USER_AGENT,
  browserLanguage = DEFAULT_BROWSER_LANGUAGE,
  platform = DEFAULT_PLATFORM,
  token,
} = {}) {
  const timestamp = String(Date.now());
  const nonce = md5Hex(`1${timestamp}`);
  const signatureText =
    "POST\n" +
    `x-ca-timestamp:${timestamp}\n` +
    `x-ca-nonce:${nonce}\n` +
    "x-scope:manager\n" +
    "x-client:web\n" +
    "x-client-version:9.0.0\n";
  const signature = crypto
    .createHmac("sha256", SIGNING_SECRET)
    .update(signatureText, "utf8")
    .digest("base64");

  const headers = {
    accept: "application/json",
    "x-app-code-name": "Mozilla",
    "x-app-name": "Netscape",
    "x-app-version": userAgent.replace(/^Mozilla\//, ""),
    "x-browser-language": browserLanguage,
    "x-ca-key": "83579288",
    "x-ca-nonce": nonce,
    "x-ca-signature": signature,
    "x-ca-timestamp": timestamp,
    "x-city-id": "",
    "x-city-name": "",
    "x-client": "web",
    "x-client-version": "9.0.0",
    "x-ip": "",
    "x-platform": platform,
    "x-scope": "manager",
    "x-user-agent": userAgent,
  };

  if (token) {
    headers["x-token"] = token;
  }

  return headers;
}

function httpsRequestJson(url, { headers, body }) {
  return new Promise((resolve, reject) => {
    const bodyText = body ? JSON.stringify(body) : "";
    const requestHeaders = {
      origin: MANAGER_ORIGIN,
      referer: `${MANAGER_ORIGIN}/`,
      "user-agent": DEFAULT_USER_AGENT,
      ...headers,
    };

    if (bodyText) {
      requestHeaders["content-type"] = "application/json;charset=UTF-8";
      requestHeaders["content-length"] = Buffer.byteLength(bodyText);
    }

    const request = https.request(
      url,
      {
        method: "POST",
        headers: requestHeaders,
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          resolve({
            statusCode: response.statusCode || 0,
            headers: response.headers,
            text,
            json: safeJsonParse(text),
          });
        });
      },
    );

    request.on("error", reject);
    if (bodyText) {
      request.write(bodyText);
    }
    request.end();
  });
}

function isApiError(payload) {
  if (!payload || typeof payload !== "object") {
    return true;
  }
  const code = payload.code;
  if (typeof code === "number") {
    return code < 0;
  }
  if (typeof code === "string" && /^-\d+$/.test(code)) {
    return true;
  }
  return false;
}

function validationSucceeded(response) {
  if (response.statusCode < 200 || response.statusCode >= 300) {
    return false;
  }
  if (!response.json || typeof response.json !== "object") {
    return false;
  }
  if (isApiError(response.json)) {
    return false;
  }
  const payloads = [response.json, response.json.data, response.json.result];
  return payloads.some(
    (item) =>
      item &&
      typeof item === "object" &&
      ("userId" in item ||
        "userName" in item ||
        "name" in item ||
        Object.keys(item).length > 0),
  );
}

function extractTokens(payload) {
  const candidates = [payload, payload && payload.data, payload && payload.result];
  for (const item of candidates) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const token = item.token || item.accessToken;
    const refreshToken = item.refreshToken || item.refresh_token;
    if (token && refreshToken) {
      return {
        token: String(token),
        refreshToken: String(refreshToken),
      };
    }
  }
  return null;
}

function requirePlaywright() {
  const candidates = [
    "playwright",
    path.join(
      os.homedir(),
      ".cache",
      "codex-runtimes",
      "codex-primary-runtime",
      "dependencies",
      "node",
      "node_modules",
      "playwright",
    ),
  ];

  let lastError;
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      lastError = error;
    }
  }

  throw new Error(
    `Unable to load playwright. Set NODE_PATH to a node_modules directory ` +
      `that contains playwright. Last error: ${lastError && lastError.message}`,
  );
}

async function validateCachedToken(token) {
  const headers = buildSignedHeaders({ token });
  return httpsRequestJson(VALIDATE_URL, { headers });
}

async function loginWithBrowserRequest(account, passwordMd5) {
  const { chromium } = requirePlaywright();
  const defaultChromePath =
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  const launchOptions = {
    headless: true,
  };
  const chromePath = process.env.MFOOD_CHROME_PATH || defaultChromePath;
  if (fs.existsSync(chromePath)) {
    launchOptions.executablePath = chromePath;
  }

  const browser = await chromium.launch(launchOptions);
  try {
    const context = await browser.newContext({ locale: "zh-CN" });
    const page = await context.newPage();
    await page.goto(`${MANAGER_ORIGIN}/`, { waitUntil: "domcontentloaded" });

    const browserInfo = await page.evaluate(() => ({
      userAgent: navigator.userAgent,
      browserLanguage: navigator.language,
      platform: navigator.platform,
    }));
    const headers = buildSignedHeaders(browserInfo);

    // `/token/_get` rejects equivalent local HTTP replay in this environment,
    // so the refresh path runs the same request inside a real browser context.
    const response = await page.evaluate(
      async ({ loginUrl, accountValue, passwordMd5Value, requestHeaders }) => {
        const result = await fetch(loginUrl, {
          method: "POST",
          headers: {
            ...requestHeaders,
            accept: "application/json",
            "content-type": "application/json;charset=UTF-8",
          },
          body: JSON.stringify({
            loginType: 1,
            account: accountValue,
            password: passwordMd5Value,
          }),
        });
        return {
          status: result.status,
          text: await result.text(),
        };
      },
      {
        loginUrl: LOGIN_URL,
        accountValue: account,
        passwordMd5Value: passwordMd5,
        requestHeaders: headers,
      },
    );

    const payload = safeJsonParse(response.text);
    const tokens = extractTokens(payload);
    if (response.status < 200 || response.status >= 300 || !tokens) {
      const message = apiMessage(
        payload,
        `mFood login failed with HTTP ${response.status}`,
      );
      const error = new Error(message);
      error.statusCode = response.status;
      error.payload = payload;
      throw error;
    }

    return tokens;
  } finally {
    await browser.close();
  }
}

function formatOutput(result, format) {
  if (format === "external-json") {
    return JSON.stringify(
      {
        token: result.token,
        refreshToken: result.refreshToken,
      },
      null,
      2,
    );
  }
  if (format === "text") {
    return [
      `account=${result.account}`,
      `source=${result.source}`,
      `token=${result.token}`,
      `refreshToken=${result.refreshToken}`,
      `cachedAt=${result.cachedAt}`,
      `validatedAt=${result.validatedAt}`,
    ].join("\n");
  }
  return JSON.stringify(result, null, 2);
}

function formatProfilesOutput(defaults, format) {
  const payload = {
    defaultProfile: defaults.defaultProfile,
    profiles: Object.entries(defaults.profiles).map(([profile, value]) => ({
      profile,
      account: value.account,
      hasPasswordMd5: Boolean(value.passwordMd5),
      hasPassword: Boolean(value.password),
      isDefault: profile === defaults.defaultProfile,
    })),
  };

  if (format === "text") {
    const lines = [];
    lines.push(`defaultProfile=${payload.defaultProfile || ""}`);
    for (const item of payload.profiles) {
      lines.push(
        [
          `profile=${item.profile}`,
          `account=${item.account}`,
          `isDefault=${item.isDefault}`,
          `hasPasswordMd5=${item.hasPasswordMd5}`,
          `hasPassword=${item.hasPassword}`,
        ].join(" "),
      );
    }
    return lines.join("\n");
  }

  return JSON.stringify(payload, null, 2);
}

function findProfileByAccount(defaults, account) {
  for (const [profileName, value] of Object.entries(defaults.profiles)) {
    if (value && value.account === account) {
      return { profileName, value };
    }
  }
  return null;
}

function upsertProfile(defaults, profileName, account, passwordMd5, makeDefault) {
  defaults.profiles[profileName] = {
    account,
    passwordMd5,
  };
  if (makeDefault || !defaults.defaultProfile) {
    defaults.defaultProfile = profileName;
  }
  return defaults;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  const defaults = loadDefaults(args.defaultsPath);
  if (args.listProfiles) {
    process.stdout.write(`${formatProfilesOutput(defaults, args.format)}\n`);
    return;
  }

  let selectedProfileName = args.profile || defaults.defaultProfile || null;
  let selectedProfile = selectedProfileName
    ? defaults.profiles[selectedProfileName] || null
    : null;

  if (args.profile && !selectedProfile) {
    throw new Error(`Unknown profile: ${args.profile}`);
  }

  if (!args.account && selectedProfile) {
    args.account = selectedProfile.account;
  }
  if (!args.account) {
    throw new Error("Missing --account or MFOOD_ACCOUNT");
  }

  if (!selectedProfile) {
    const matched = findProfileByAccount(defaults, args.account);
    if (matched) {
      selectedProfileName = matched.profileName;
      selectedProfile = matched.value;
    }
  }

  const cache = loadCache(args.cachePath);
  const cacheEntry = cache.accounts[args.account];
  if (!args.password && !args.passwordMd5 && selectedProfile) {
    if (selectedProfile.password) {
      args.password = String(selectedProfile.password);
    }
    if (selectedProfile.passwordMd5) {
      args.passwordMd5 = String(selectedProfile.passwordMd5);
    }
  }
  const passwordMd5 = normalizePasswordMd5(args, cacheEntry);
  const now = new Date().toISOString();

  let result;

  if (!args.forceRefresh && cacheEntry && cacheEntry.token && cacheEntry.refreshToken) {
    const validation = await validateCachedToken(cacheEntry.token);
    if (validationSucceeded(validation)) {
      const updatedEntry = {
        ...cacheEntry,
        passwordMd5,
        validatedAt: now,
        lastSource: "cache",
      };
      cache.accounts[args.account] = updatedEntry;
      saveCache(args.cachePath, cache);
      result = {
        profile: selectedProfileName,
        account: args.account,
        source: "cache",
        token: updatedEntry.token,
        refreshToken: updatedEntry.refreshToken,
        cachedAt: updatedEntry.cachedAt,
        validatedAt: updatedEntry.validatedAt,
      };
    }
  }

  if (!result) {
    const freshTokens = await loginWithBrowserRequest(args.account, passwordMd5);
    const newEntry = {
      account: args.account,
      passwordMd5,
      token: freshTokens.token,
      refreshToken: freshTokens.refreshToken,
      cachedAt: now,
      validatedAt: now,
      lastSource: "login",
    };
    cache.accounts[args.account] = newEntry;
    saveCache(args.cachePath, cache);

    result = {
      profile: selectedProfileName,
      account: args.account,
      source: "login",
      token: newEntry.token,
      refreshToken: newEntry.refreshToken,
      cachedAt: newEntry.cachedAt,
      validatedAt: newEntry.validatedAt,
    };
  }

  let profileToPersist = null;
  if (args.saveProfile) {
    profileToPersist = args.saveProfile;
  } else if (args.makeDefault) {
    profileToPersist = selectedProfileName;
    if (!profileToPersist) {
      throw new Error(
        "--make-default requires --profile or --save-profile when no saved profile matches the account",
      );
    }
  }

  if (profileToPersist) {
    upsertProfile(
      defaults,
      profileToPersist,
      args.account,
      passwordMd5,
      Boolean(args.makeDefault),
    );
    saveDefaults(args.defaultsPath, defaults);
    result.profile = profileToPersist;
  }

  process.stdout.write(`${formatOutput(result, args.format)}\n`);
}

main().catch((error) => {
  const output = {
    error: error.message || String(error),
  };
  if (error.statusCode) {
    output.statusCode = error.statusCode;
  }
  if (error.payload && typeof error.payload === "object") {
    output.code = error.payload.code;
    output.note = error.payload.note || error.payload.message || null;
  }
  process.stderr.write(`${JSON.stringify(output, null, 2)}\n`);
  process.exit(1);
});
