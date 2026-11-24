"""Bounded public-page diagnostics and ordinary JavaScript rendering.
No credentials, proxies, stealth, CAPTCHA solving, or retry of access denials.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from source_recovery import Page

ALLOWED={"www.uscfinvestments.com","www.invesco.com","www.shfe.com.cn","www.shfe.cn"}
MAX_BYTES=4_000_000

def allowed(url):
    p=urlsplit(url)
    return p.scheme=="https" and p.hostname in ALLOWED and not p.username and not p.password

def evidence(label,url,html,status,content_type,final_url):
    # Only public data markers and bounded surrounding text, never scripts,
    # response headers, cookies, keys, or full copyrighted pages.
    p=Page(html)
    t=p.text
    markers=["Key Facts","Shares Outstanding","Total Net Assets","Fund NAV","Assets Under Management",
             "Creation / Redemption","期货仓单日报","Shanghai Futures Exchange Warehouse Stocks Daily"]
    excerpts={}
    for term in markers:
        hits=list(re.finditer(re.escape(term),t,re.I))
        if hits:
            excerpts[term]=[t[max(0,m.start()-35):m.end()+150] for m in hits[:3]]
    blocked=bool(re.search(r"access denied|verify you are human|captcha|request blocked|security challenge",t[:1200],re.I))
    out=dict(label=label,url=url,final_host=urlsplit(final_url).hostname,status=status,
             content_type=content_type,chars=len(html),sha256=hashlib.sha256(html.encode()).hexdigest(),
             marker_excerpts=excerpts,challenge_detected=blocked)
    # No text from script blocks, even if source markup contains public app keys.
    print("SOURCE_EVIDENCE "+json.dumps(out,ensure_ascii=False),flush=True)
    return blocked

def raw_page(url):
    if not allowed(url):raise ValueError("unapproved public source URL")
    with urlopen(Request(url,headers={"User-Agent":"global-capital-radar/2.3"}),timeout=20) as r:
        final=r.geturl()
        if not allowed(final):raise ValueError("unapproved redirect")
        data=r.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise ValueError("source body exceeds bound")
        status=r.status
        if status!=200:raise ValueError("public page not HTTP 200")
        html=data.decode(r.headers.get_content_charset() or "utf-8",errors="replace")
        if evidence("RAW",url,html,status,r.headers.get_content_type(),final):
            raise ValueError("access challenge; stop")
        return html

def rendered_page(url,selector=None):
    if not allowed(url):raise ValueError("unapproved render URL")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            page=browser.new_page()
            # Normal public browser session; no authenticated state.
            response=page.goto(url,wait_until="domcontentloaded",timeout=20000)
            if not response or response.status!=200 or not allowed(page.url):
                raise ValueError("rendered page unavailable or redirected")
            html=page.content()
            if evidence("RENDER_INITIAL",url,html,response.status,"text/html",page.url):
                raise ValueError("access challenge; stop")
            if selector:
                try:page.locator(selector).first.wait_for(state="attached",timeout=12000)
                except Exception:pass
            # Data can populate existing nodes asynchronously.
            for _ in range(8):
                html=page.content()
                if len(html)>MAX_BYTES:raise ValueError("rendered body exceeds bound")
                if re.search(r'data-key=["\']so["\'][^>]*>\s*[\d,]+',html,re.I):break
                if selector and "期货仓单日报" in Page(html).text:break
                page.wait_for_timeout(1000)
            if not allowed(page.url) or evidence("RENDER_FINAL",url,html,200,"text/html",page.url):
                raise ValueError("render access challenge or redirect")
            return html
        finally:browser.close()

def verified_page(url,parser,selector=None):
    # HTTP exceptions from the raw request propagate; no attempt to bypass them.
    raw=raw_page(url)
    try:return dict(parser(raw),source_sha256=hashlib.sha256(raw.encode()).hexdigest()),"RAW_HTTP_200"
    except (ValueError,AttributeError,TypeError,KeyError) as exc:
        print("SOURCE_PARSE_RAW "+type(exc).__name__+": "+str(exc)[:220],flush=True)
    html=rendered_page(url,selector)
    return dict(parser(html),source_sha256=hashlib.sha256(html.encode()).hexdigest()),"RENDERED_HTTP_200"
