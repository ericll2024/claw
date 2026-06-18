#!/usr/bin/env python3
"""
Navigate to Facebook groups and check for yesterday's posts - v3 with discussion tabs
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
    result = await call_cdp(page_ws_url, "Runtime.evaluate", {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": True
    })
    return result.get("result", {}).get("value", "")

async def navigate(page_ws_url, url):
    await call_cdp(page_ws_url, "Page.enable")
    await call_cdp(page_ws_url, "Page.navigate", {"url": url})
    await asyncio.sleep(8)
    try:
        await evaluate(page_ws_url, 
            "new Promise(r => { if(document.readyState==='complete') r(); else document.addEventListener('readystatechange',()=>{if(document.readyState==='complete')r()}) })")
    except:
        pass
    await asyncio.sleep(3)

async def scroll_multiple(page_ws_url, count=8):
    for i in range(count):
        await evaluate(page_ws_url, f"window.scrollBy(0, 2000)")
        await asyncio.sleep(2)

async def group_group_nav(page_ws_url, group_url):
    """Navigate and try to click on '讨论' tab for chronological sorting"""
    
    # Navigate to the group
    await navigate(page_ws_url, group_url)
    
    # Check for recent sort options - click on "最新" link if visible
    # FB groups have a sort dropdown
    js_click_recent = """
    (() => {
        // Look for "最新帖子" or "Recent" or sorting dropdown
        let links = document.querySelectorAll('a, span, div[role="button"]');
        for (let el of links) {
            let text = el.innerText || '';
            if (text.includes('最新') || text.includes('Recent') || text.includes('New')) {
                if (el.tagName === 'A' || el.getAttribute('role') === 'button') {
                    el.click();
                    return 'Clicked: ' + text;
                }
            }
        }
        return 'No sort option found';
    })()
    """
    result = await evaluate(page_ws_url, js_click_recent)
    print(f"  Sort click result: {result}", file=sys.stderr)
    await asyncio.sleep(3)
    
    # Try clicking on the group's discussion/posts tab
    js_tabs = """
    (() => {
        // Look for tab links like "讨论", "帖子", "Discussion", "Posts"
        let items = document.querySelectorAll('a[role="tab"], div[role="tab"], a:not([role])');
        for (let el of items) {
            let text = el.innerText || el.getAttribute('aria-label') || '';
            if (text.includes('讨论') || text.includes('帖子') || text.includes('Discussion') || text.includes('Posts') || text.includes('話題')) {
                if (el.tagName === 'A') {
                    return 'Found tab: ' + text + ' href=' + (el.href || '');
                }
            }
        }
        // Also look for "posts" or "讨论" in URL path
        return 'No discussion tab found';
    })()
    """
    result = await evaluate(page_ws_url, js_tabs)
    print(f"  Tab search: {result}", file=sys.stderr)
    
    # Try going to the discussion URL directly
    discussion_url = group_url.rstrip('/') + '/posts/'
    print(f"  Trying discussion URL: {discussion_url}", file=sys.stderr)
    await navigate(page_ws_url, discussion_url)
    await scroll_multiple(page_ws_url, 6)
    
    # Get content
    text = await evaluate(page_ws_url, "document.body ? document.body.innerText.substring(0, 120000) : ''")
    title = await evaluate(page_ws_url, "document.title")
    
    return title, text

async def extract_posts_with_dates(page_ws_url, text):
    """Try to extract posts with their dates from the full text"""
    lines = text.split('\n')
    yesterday = datetime.now(SHA_TZ) - timedelta(days=1)
    
    # Build date markers for yesterday
    y_date_str = yesterday.strftime("%Y年%m月%d日")
    y_month_day = yesterday.strftime("%m月%d日")
    y_date_eng = yesterday.strftime("%B %d, %Y")
    y_date_eng2 = yesterday.strftime("%b %d, %Y")
    
    markers = [
        y_date_str, y_month_day, y_date_eng, y_date_eng2,
        "昨天", "1天", "1 天前", "2 天前", "2天前",
        "分鐘前", "小时前", "小時前",
        "刚刚", "Just now"
    ]
    
    # Add "X天前" for 1-7 days
    for d in range(1, 8):
        markers.append(f"{d}天前")
        markers.append(f"{d} 天前")
    
    # Add "X小时前" for 1-24 hours
    for h in range(1, 24):
        markers.append(f"{h}小时前")
        markers.append(f"{h} 小時前")
        markers.append(f"{h} 小时")
        markers.append(f"{h} 小時")
    
    # Also check for time patterns like "3月14日" that match yesterday
    yesterday_m = yesterday.month
    yesterday_d = yesterday.day
    markers.append(f"{yesterday_m}月{yesterday_d}日")
    
    # Find posts with recent markers
    found_sections = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        for marker in markers:
            if marker and marker in stripped:
                # Capture context
                start = max(0, i-8)
                end = min(len(lines), i+30)
                ctx = lines[start:end]
                section = '\n'.join(ctx)
                if section not in found_sections:
                    found_sections.append(section)
                break
    
    return found_sections

async def main():
    yesterday = (datetime.now(SHA_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Yesterday: {yesterday}", file=sys.stderr)
    
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
    
    all_results = [
        "# 📊 Facebook 群组昨日帖子日报", 
        f"*报告日期*: **2026年5月14日（周四）**", 
        f"*生成时间*: {datetime.now(SHA_TZ).strftime('%Y-%m-%d %H:%M')}",
        ""
    ]
    
    for group_url, label in groups:
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Processing: {label}", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)
        
        title, text = await group_group_nav(ws_url, group_url)
        print(f"  Title: {title[:80]}", file=sys.stderr)
        print(f"  Text length: {len(text)}", file=sys.stderr)
        
        results = []
        results.append(f"## 📌 {label}")
        results.append(f"")
        
        if not text.strip():
            results.append("⚠️ 未能读取页面内容")
        else:
            # Find recent posts
            sections = await extract_posts_with_dates(ws_url, text)
            
            if sections:
                results.append("### 近期帖子")
                for i, sec in enumerate(sections[:3]):
                    results.append(f"\n**帖子 {i+1}**")
                    results.append(sec[:3000])
                
                # Also show the raw text for context
                lines = text.split('\n')
                # Filter meaningful lines
                meaningful = [l.strip() for l in lines if len(l.strip()) > 10][-50:]
                results.append("\n### 页面全部文本摘要")
                results.append('\n'.join(meaningful[:100]))
            else:
                # Show whatever visible text we have
                lines = text.split('\n')
                meaningful = [l.strip() for l in lines if len(l.strip()) > 10]
                results.append("### 页面文本内容")
                results.append('\n'.join(meaningful[-100:]))
        
        results.append("")
        all_results.extend(results)
    
    return all_results

if __name__ == "__main__":
    all_results = asyncio.run(main())
    print("\n".join(all_results))
