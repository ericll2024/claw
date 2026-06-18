#!/usr/bin/env python3
"""
Navigate to Facebook groups via CDP and extract yesterday's posts - v2 with aggressive scroll and date filtering.
"""
import json
import time
import re
import sys
from datetime import datetime, timedelta, timezone
import urllib.request
import asyncio
import websockets

CHROME_DEBUG = "http://localhost:9222"
SHA_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

async def call_cdp(page_ws_url, method, params=None):
    if params is None:
        params = {}
    msg_id = int(time.time() * 1000) % 100000
    payload = json.dumps({"id": msg_id, "method": method, "params": params})
    async with websockets.connect(page_ws_url, max_size=10_485_760) as ws:
        await ws.send(payload)
        resp = await ws.recv()
        data = json.loads(resp)
        while data.get("id") != msg_id:
            resp = await ws.recv()
            data = json.loads(resp)
        return data.get("result")

async def evaluate(page_ws_url, expr):
    """Evaluate JS and return the value."""
    result = await call_cdp(page_ws_url, "Runtime.evaluate", {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": True
    })
    return result.get("result", {}).get("value", "")

async def navigate(page_ws_url, url):
    await call_cdp(page_ws_url, "Page.enable")
    await call_cdp(page_ws_url, "Page.navigate", {"url": url})
    # Wait for page to load
    await asyncio.sleep(10)
    # Wait for DOM ready
    try:
        await evaluate(page_ws_url, 
            "new Promise(r => { if(document.readyState==='complete') r(); else document.addEventListener('readystatechange',()=>{if(document.readyState==='complete')r()}) })")
    except:
        pass
    await asyncio.sleep(3)

async def scroll_aggressively(page_ws_url):
    """Scroll multiple times to load content"""
    for i in range(8):
        await evaluate(page_ws_url, f"window.scrollBy(0, 2000)")
        await asyncio.sleep(3)

async def extract_all_text(page_ws_url):
    """Get all visible text from the page"""
    text = await evaluate(page_ws_url, "document.body ? document.body.innerText.substring(0, 100000) : ''")
    return text

async def extract_post_articles(page_ws_url):
    """Get individual article elements (Facebook posts)"""
    js = """
    (() => {
        // Try various Facebook post selectors
        let selectors = [
            'div[role="article"]',
            'article',
            'div.x1yztbdb:not([role])', 
            'div[data-pagelet="root"] div[style]'
        ];
        let seen = new Set();
        let posts = [];
        
        // Get all visible article-like elements
        let articles = document.querySelectorAll('div[role="article"]');
        articles.forEach((a, i) => {
            let text = a.innerText || '';
            if (text.length > 30) {
                // Try to get the post time
                let timeEls = a.querySelectorAll('a time, span[dir="auto"] time, span:contains("小时"), span:contains("分钟"), span:contains("天"), span:contains("月"), span:contains("年")');
                let timeText = '';
                timeEls.forEach(t => { timeText += t.innerText + ' | '; });
                
                let key = text.substring(0, 100);
                if (!seen.has(key)) {
                    seen.add(key);
                    posts.push(`[Post ${i+1}]\nTime: ${timeText}\n${text.substring(0, 4000)}`);
                }
            }
        });
        
        if (posts.length === 0) {
            // Fallback: get all large text blocks
            let divs = document.querySelectorAll('div');
            divs.forEach((d, i) => {
                let t = d.innerText || '';
                if (t.length > 50 && t.length < 5000 && !seen.has(t.substring(0,100))) {
                    let parentRole = d.closest('[role]') ? d.closest('[role]').getAttribute('role') : '';
                    seen.add(t.substring(0,100));
                    posts.push(`[Block ${i+1}] (role=${parentRole})\n${t.substring(0, 2000)}`);
                }
            });
        }
        
        return posts.join('\n\n---\n\n');
    })()
    """
    return await evaluate(page_ws_url, js)

async def work_group(page_ws_url, group_url, label):
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Processing: {label}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    
    await navigate(page_ws_url, group_url)
    
    # Check login status
    title = await evaluate(page_ws_url, "document.title")
    text = await extract_all_text(page_ws_url)
    
    print(f"  Title: {title[:80]}", file=sys.stderr)
    print(f"  Text length: {len(text)}", file=sys.stderr)
    
    text_lower = text.lower()
    
    if "log in" in text_lower and ("create new account" in text_lower or "email" in text_lower[:500]):
        print(f"  ⚠️ NOT LOGGED IN", file=sys.stderr)
        return [f"⚠️ 未登录Facebook，无法查看群组 {label}"]
    
    if "this content isn't available" in text_lower:
        print(f"  ⚠️ Content unavailable", file=sys.stderr)
        return [f"⚠️ 无法访问群组 {label}"]
    
    # Scroll aggressively
    print(f"  Scrolling...", file=sys.stderr)
    await scroll_aggressively(page_ws_url)
    
    # Get full content
    text = await extract_all_text(page_ws_url)
    
    # Focus on recent posts - look for date markers
    lines = text.split('\n')
    today = datetime.now(SHA_TZ)
    yesterday = today - timedelta(days=1)
    
    # Date patterns for yesterday
    y_date_str = yesterday.strftime("%Y年%m月%d日")
    y_month_day = yesterday.strftime("%m月%d日")
    y_hyphen = yesterday.strftime("%Y-%m-%d")
    y_slash = yesterday.strftime("%Y/%m/%d")
    
    yesterday_markers = [y_date_str, y_month_day, y_hyphen, y_slash, "昨天", "1天", "1 天", "22小时", "23小时", "20小时", "21小时", "19小时", "18小时", "17小时", "16小时", "15小时"]
    
    # Also check for "小时前" patterns (hours ago)
    hours_ago_markers = []
    for h in range(1, 24):
        hours_ago_markers.append(f"{h}小时前")
        hours_ago_markers.append(f"{h} 小时前")
    for h in range(1, 48):
        hours_ago_markers.append(f"{h} 小时")
    
    all_markers = yesterday_markers + hours_ago_markers
    
    # Check if we're logged in and can see the group
    is_logged_in = "log into facebook" not in text_lower[:300]
    is_member = "join group" not in text_lower[:500]
    
    print(f"  Logged in: {is_logged_in}, Member: {not is_member}", file=sys.stderr)
    print(f"  Looking for dates: {y_date_str}, {y_month_day}", file=sys.stderr)
    
    # Try to check if there are any posts visible at all
    # Look for the "昨天" marker or recent comments
    recent_found = False
    for m in all_markers[:15]:
        if m in text:
            recent_found = True
            print(f"  Found date marker: '{m}'", file=sys.stderr)
            break
    
    results = []
    results.append(f"## 📌 {label}")
    results.append(f"*页面*: {title}")
    results.append(f"*抓取时间*: {datetime.now(SHA_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    results.append("")
    
    if not is_logged_in:
        results.append("⚠️ 未登录Facebook账号")
        results.append("")
        return results
    
    if not text.strip():
        results.append("无可见内容")
        results.append("")
        return results
    
    # If we found recent markers or we have content, show posts
    if recent_found or len(text) > 500:
        # Get articles
        articles = await extract_post_articles(page_ws_url)
        
        if articles and len(articles) > 50:
            results.append("### 帖子内容")
            results.append(articles[:20000])
        else:
            # Show filtered text - only lines that seem relevant
            relevant_lines = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                if len(stripped) > 5:
                    relevant_lines.append(stripped)
            
            # Check for yesterday's content
            yesterday_context = []
            for i, line in enumerate(lines):
                if any(m in line for m in all_markers):
                    # Get context around this line
                    start = max(0, i-5)
                    end = min(len(lines), i+15)
                    context = lines[start:end]
                    yesterday_context.extend(context)
                    yesterday_context.append("---")
            
            if yesterday_context:
                results.append("### 昨日相关帖子")
                results.append('\n'.join(yesterday_context[:100]))
            else:
                results.append("### 页面文本（最近内容）")
                # Show last 100 relevant lines (newest content)
                results.append('\n'.join(relevant_lines[-100:]))
    else:
        results.append("无新帖（页面中未发现昨日或24小时内的帖子）")
    
    results.append("")
    return results

async def main():
    yesterday = (datetime.now(SHA_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Yesterday: {yesterday}", file=sys.stderr)
    print(f"Current: {datetime.now(SHA_TZ).strftime('%Y-%m-%d %H:%M:%S')}", file=sys.stderr)
    
    groups = [
        ("https://www.facebook.com/groups/644345363776357/", "KeeTa外賣關注組"),
        ("https://www.facebook.com/groups/273979355317477/", "澳門外賣騎手交流會"),
        ("https://www.facebook.com/groups/982872103263383/", "澳門外賣平台壓榨商家關注組"),
    ]
    
    resp = urllib.request.urlopen("http://localhost:9222/json")
    pages = json.loads(resp.read())
    
    if not pages:
        return ["❌ 无可用浏览器页面"]
    
    target_id = pages[0]['id']
    ws_url = f"ws://localhost:9222/devtools/page/{target_id}"
    
    # First navigate to Facebook to ensure we're logged in with session cookies
    await navigate(ws_url, "https://www.facebook.com/")
    await asyncio.sleep(3)
    title = await evaluate(ws_url, "document.title")
    print(f"Facebook homepage title: {title}", file=sys.stderr)
    text = await extract_all_text(ws_url)
    print(f"Facebook homepage text length: {len(text)}", file=sys.stderr)
    if "log in" in text.lower()[:500]:
        print("❌ STILL NOT LOGGED IN on Facebook!", file=sys.stderr)
    
    all_results = ["# 📊 Facebook 群组昨日帖子日报", f"*报告日期*: {yesterday}", f"*生成时间*: {datetime.now(SHA_TZ).strftime('%Y-%m-%d %H:%M')}", ""]
    
    for group_url, label in groups:
        result = await work_group(ws_url, group_url, label)
        all_results.extend(result)
    
    return all_results

if __name__ == "__main__":
    all_results = asyncio.run(main())
    print("\n".join(all_results))
