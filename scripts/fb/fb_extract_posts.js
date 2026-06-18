(() => {
  const seen = new Set();
  const articles = [...document.querySelectorAll('[role="article"]')];
  const out = [];
  for (const a of articles) {
    const postA = [...a.querySelectorAll('a[href*="/posts/"]')].find(x => /\/posts\/\d+/.test(x.href) && !x.href.includes('comment_id='));
    if (!postA) continue;
    const id = (postA.href.match(/\/posts\/(\d+)/) || [])[1];
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const text = (a.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
    const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
    const author = lines[0] || '';
    const time = [...a.querySelectorAll('abbr')].map(x => x.getAttribute('aria-label') || x.textContent.trim()).find(Boolean) || '';
    const imgs = [...a.querySelectorAll('img[alt]')].map(img => img.alt).filter(Boolean).slice(0, 6);
    out.push({
      id,
      author,
      time,
      postUrl: postA.href,
      text: lines.slice(0, 40),
      imgs
    });
    if (out.length >= 8) break;
  }
  return out;
})()