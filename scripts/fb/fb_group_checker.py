#!/usr/bin/env python3
"""
Navigate to Facebook groups via CDP and extract yesterday's posts.
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
    """Send a CDP command and return the result."""
    if params is None:
        params = {}
    msg_id = int(time.time() * 1000) % 100000
    payload = json.dumps({"id": msg_id, "method": method, "params": params})
    async with websockets.connect(page_ws_url, max_size=10_485_760) as ws:
        await ws.send(payload)
        resp = await ws.recv()
        data = json.loads(resp)
        # We may need to read multiple messages
        while data.get("id") != msg_id:
            resp = await ws.recv()
            data = json.loads(resp)
        return data.get("result")

async def navigate_and_wait(page_ws_url, url, timeout=30):
    """Navigate to a URL and wait for the page to load."""
    result = await call_cdp(page_ws_url, "Page.enable")
    result = await call_cdp(page_ws_url, "Page.navigate", {"url": url})
    target_id = result.get("frameId")
    print(f"  Navigating to {url[:60]}... targetId={target_id}", file=sys.stderr)
    # Wait for load
    await asyncio.sleep(8)
    # Wait for DOM content
    try:
        await call_cdp(page_ws_url, "Page.enable")
        # Try waiting via Runtime
        await call_cdp(page_ws_url, "Runtime.evaluate", {
            "expression": "new Promise(r => { if(document.readyState==='complete') r(); else document.addEventListener('readystatechange',()=>{if(document.readyState==='complete')r()}) })",
            "awaitPromise": True,
            "timeout": 20000
        })
    except Exception as e:
        print(f"    Wait warning: {e}", file=sys.stderr)
    await asyncio.sleep(3)
    return True

async def get_page_content(page_ws_url):
    """Get page title and body text."""
    result = await call_cdp(page_ws_url, "Runtime.evaluate", {
        "expression": "document.title",
        "returnByValue": True
    })
    title = result.get("result", {}).get("value", "")
    
    result = await call_cdp(page_ws_url, "Runtime.evaluate", {
        "expression": "document.body ? document.body.innerText.substring(0, 80000) : 'No body'",
        "returnByValue": True,
        "awaitPromise": True
    })
    text = result.get("result", {}).get("value", "")
    
    # Also get all links/text that might contain post content
    result = await call_cdp(page_ws_url, "Runtime.evaluate", {
        "expression": """
        (() => {
            // Get all article elements (common for Facebook posts)
            let articles = document.querySelectorAll('div[role="article"], article');
            let results = [];
            articles.forEach((a, i) => {
                let t = a.innerText || '';
                if (t.length > 20) {
                    results.push(`[Article ${i+1}]\n${t.substring(0, 3000)}`);
                }
            });
            return results.join('\\n\\n---\\n\\n');
        })()
        """,
        "returnByValue": True,
        "awaitPromise": True
    })
    articles = result.get("result", {}).get("value", "")
    
    return title, text, articles

async def scroll_page(page_ws_url, times=5):
    """Scroll down to load more content."""
    for i in range(times):
        await call_cdp(page_ws_url, "Runtime.evaluate", {
            "expression": f"window.scrollBy(0, 1500)",
            "returnByValue": False
        })
        await asyncio.sleep(2)
    return True

async def work_one_group(target_id, group_url, group_label):
    """Process one Facebook group."""
    ws_url = f"ws://localhost:9222/devtools/page/{target_id}"
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Processing: {group_label}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    
    await navigate_and_wait(ws_url, group_url)
    
    # Check if we're logged in
    title, text, articles = await get_page_content(ws_url)
    
    text_lower = text.lower()
    
    # If we see login screen
    if "log in" in text_lower and ("create new account" in text_lower or "email" in text_lower[:500]):
        print(f"  ⚠️ NOT LOGGED IN - showing login page", file=sys.stderr)
        return [f"⚠️ 未登录Facebook，无法查看群组 {group_label}"]
    
    # If we see "group not found" or similar
    if "this content isn't available" in text_lower or "page not found" in text_lower or "sorry" in text_lower[:200]:
        print(f"  ⚠️ Content not available", file=sys.stderr)
        return [f"⚠️ 无法访问群组 {group_label}（可能已失效或无权限）"]
    
    # Scroll to load more posts
    await scroll_page(ws_url, 6)
    
    # Get full content after scroll
    title, text, articles = await get_page_content(ws_url)
    
    print(f"  Title: {title[:80]}", file=sys.stderr)
    print(f"  Text length: {len(text)}", file=sys.stderr)
    print(f"  Articles length: {len(articles)}", file=sys.stderr)
    
    # Check for "Join Group" button (private group we're not in)
    if "join group" in text_lower or "join this group" in text_lower or "request to join" in text_lower:
        print(f"  ⚠️ Join button visible - not a member", file=sys.stderr)
        # Still try to extract what we can see
    
    results = []
    results.append(f"## 📌 {group_label}")
    
    # Try to extract posts
    # Look for date patterns to identify yesterday's posts
    yesterday = (datetime.now(SHA_TZ) - timedelta(days=1))
    yesterday_str = yesterday.strftime("%B %d") + "|" + yesterday.strftime("%b %d") + "|" + yesterday.strftime("%m月%d日")
    day_before = yesterday - timedelta(days=1)
    day_before_str = day_before.strftime("%B %d")
    
    print(f"  Looking for posts from: {yesterday.strftime('%Y-%m-%d')}", file=sys.stderr)
    
    # Save text for analysis
    results.append(f"*页面标题*: {title}")
    results.append(f"*抓取时间*: {datetime.now(SHA_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    results.append("")
    
    # Let's capture what we got
    if articles:
        results.append("### 帖子内容")
        results.append(articles[:15000])
    else:
        # Show raw text summary
        lines = text.split('\n')
        # Filter relevant lines
        relevant = [l.strip() for l in lines if len(l.strip()) > 10]
        text_sample = '\n'.join(relevant[:200])
        results.append("### 页面文本摘要")
        results.append(text_sample[:10000])
    
    results.append("")
    return results

async def main():
    yesterday = (datetime.now(SHA_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Yesterday: {yesterday}", file=sys.stderr)
    print(f"Current: {datetime.now(SHA_TZ).strftime('%Y-%m-%d %H:%M:%S')}", file=sys.stderr)
    
    groups = [
        ("https://www.facebook.com/groups/644345363776357/", "群组1 (644345363776357)"),
        ("https://www.facebook.com/groups/273979355317477/", "群组2 (273979355317477)"),
        ("https://www.facebook.com/groups/982872103263383/", "群组3 (982872103263383)"),
    ]
    
    # Get available pages
    resp = urllib.request.urlopen("http://localhost:9222/json")
    pages = json.loads(resp.read())
    print(f"Available pages: {len(pages)}", file=sys.stderr)
    for p in pages:
        print(f"  - {p['id'][:20]}: {p['title'][:60]}", file=sys.stderr)
    
    # Use the first page
    if not pages:
        print("ERROR: No browser pages available!", file=sys.stderr)
        return []
    
    target_id = pages[0]['id']
    
    all_results = []
    for group_url, label in groups:
        result = await work_one_group(target_id, group_url, label)
        all_results.extend(result)
    
    return all_results

if __name__ == "__main__":
    all_results = asyncio.run(main())
    print("\n".join(all_results))
