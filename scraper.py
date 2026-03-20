"""
招聘信息抓取脚本 v3
使用各公司官网招聘页面，优先 Workday API，其余用浏览器渲染
推送方式：WxPusher
"""

import json
import os
import time
import hashlib
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ── 配置 ──────────────────────────────────────────────
WXPUSHER_APP_TOKEN = os.environ.get("WXPUSHER_APP_TOKEN", "")
WXPUSHER_UID       = os.environ.get("WXPUSHER_UID", "")
CACHE_FILE         = "cache/jobs.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}

# ── Workday API 目标（直接请求 JSON，无需浏览器）──────
# Workday 标准接口：POST /wday/cxs/{tenant}/{instance}/jobs
WORKDAY_TARGETS = [
    {
        "name": "诺华-北京上海",
        "url": "https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/Novartis_Careers/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "", "locations": [{"id": "Beijing"}, {"id": "Shanghai"}]},
    },
    {
        "name": "赛诺菲-北京上海",
        "url": "https://sanofi.wd3.myworkdayjobs.com/wday/cxs/sanofi/SanofiCareers/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "medical", "locations": [{"id": "Beijing"}, {"id": "Shanghai"}]},
    },
    {
        "name": "AZ-医学部",
        "url": "https://astrazeneca.wd3.myworkdayjobs.com/wday/cxs/astrazeneca/Careers/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "medical affairs", "locations": [{"id": "Beijing"}, {"id": "Shanghai"}]},
    },
    {
        "name": "GSK-医学部",
        "url": "https://gsk.wd5.myworkdayjobs.com/wday/cxs/gsk/GSK_External_Career_Site/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "medical", "locations": [{"id": "Beijing"}, {"id": "Shanghai"}]},
    },
    {
        "name": "拜耳-北京上海",
        "url": "https://bayer.wd3.myworkdayjobs.com/wday/cxs/bayer/Bayer/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "", "locations": [{"id": "Beijing"}, {"id": "Shanghai"}]},
    },
    {
        "name": "强生-医学",
        "url": "https://jnj.wd5.myworkdayjobs.com/wday/cxs/jnjgateway/JnJGateway/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "medical affairs China", "locations": []},
    },
    {
        "name": "艾伯维-北京上海",
        "url": "https://abbvie.wd1.myworkdayjobs.com/wday/cxs/abbvie/abbvie_global/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "China medical", "locations": [{"id": "Beijing"}, {"id": "Shanghai"}]},
    },
    {
        "name": "勃林格殷格翰-北京上海",
        "url": "https://boehringer-ingelheim.wd3.myworkdayjobs.com/wday/cxs/boehringer-ingelheim/Boehringer_Ingelheim_External_Career_Site/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "", "locations": [{"id": "Beijing"}, {"id": "Shanghai"}]},
    },
]

# ── 浏览器渲染目标 ────────────────────────────────────
BROWSER_TARGETS = [
    {
        "name": "辉瑞-医学部",
        "url": "https://careers.pfizer.com/zh/search-jobs?orgIds=59&alp=6252001-1796231-1816670&alt=4&ascf=[{%22key%22:%22custom_fields.Category%22,%22value%22:%22Medical%22}]",
        "item_sel": ".job-list-item, .search-result, li.resultItem",
        "title_sel": "h2, h3, .job-title, a",
        "city_sel": ".job-location, .location, span.city",
    },
    {
        "name": "礼来-医学研发",
        "url": "https://jobs.lilly.com/search-jobs?orgIds=1&alp=6252001-1796231-1816670&alt=4&ascf=[{%22key%22:%22custom_fields.JobFunction%22,%22value%22:%22Medical+Affairs%22}]",
        "item_sel": ".job-list-item, li.resultItem, .search-result",
        "title_sel": "h2, h3, .job-title, a",
        "city_sel": ".job-location, .location",
    },
    {
        "name": "诺和诺德-北京上海",
        "url": "https://www.novonordisk.com/careers/job-search.html#country=China",
        "item_sel": ".job-item, .position-item, article, li.job",
        "title_sel": "h3, h2, .job-title, a",
        "city_sel": ".location, .city, .job-location",
    },
    {
        "name": "默克-北京上海",
        "url": "https://jobs.emdgroup.com/jobs?facetcountry=cn&facetcity=beijing,shanghai",
        "item_sel": ".job-tile, .job-item, article.job, li.job-result",
        "title_sel": "h3, h2, .job-title, a",
        "city_sel": ".location, .city",
    },
    {
        "name": "默沙东-北京上海",
        "url": "https://jobs.merck.com/us/en/search-results?location=China&keywords=medical",
        "item_sel": ".job-tile, article, li.job, .search-result-item",
        "title_sel": "h2, h3, .job-title, a",
        "city_sel": ".location, .city, .job-location",
    },
    {
        "name": "百时美施贵宝-北京上海",
        "url": "https://careers.bms.com/jobs?location=China&keywords=medical",
        "item_sel": ".job-list-item, article, li.job, .job-card",
        "title_sel": "h2, h3, .job-title, a",
        "city_sel": ".location, .city",
    },
    {
        "name": "罗氏-北京上海",
        "url": "https://careers.roche.com/cn/zh/china-medical-affairs-and-access-jobs",
        "item_sel": ".job-listing-item, .jobs-list-item, article.job, .job-card",
        "title_sel": "h3, h2, .job-title",
        "city_sel": ".location, .job-location, .city",
    },
]

# ── 工具函数 ─────────────────────────────────────────

def job_key(company: str, title: str, city: str) -> str:
    return hashlib.md5(f"{company}|{title}|{city}".encode()).hexdigest()

def load_cache() -> dict:
    os.makedirs("cache", exist_ok=True)
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

# ── Workday API 抓取 ─────────────────────────────────

def scrape_workday(target: dict) -> list[dict]:
    jobs = []
    try:
        r = requests.post(
            target["url"],
            json=target["body"],
            headers={**HEADERS, "Content-Type": "application/json"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("jobPostings") or data.get("jobs") or []
        for item in items:
            title    = item.get("title") or item.get("name") or ""
            city     = item.get("locationsText") or item.get("location") or ""
            ext_url  = item.get("externalPath") or item.get("url") or ""
            base     = target["url"].split("/wday/")[0]
            link     = base + ext_url if ext_url.startswith("/") else ext_url
            if title:
                jobs.append({"title": title, "city": city, "url": link})
    except Exception as e:
        print(f"  [workday error] {target['name']}: {e}")
    return jobs

# ── 浏览器渲染抓取 ───────────────────────────────────

def scrape_browser(target: dict, page) -> list[dict]:
    jobs = []
    try:
        page.goto(target["url"], wait_until="networkidle", timeout=40000)
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)

        items = page.query_selector_all(target["item_sel"])
        print(f"   → DOM 找到 {len(items)} 个元素")

        for item in items:
            title_el = item.query_selector(target["title_sel"])
            city_el  = item.query_selector(target["city_sel"])
            link_el  = item.query_selector("a")

            title = title_el.inner_text().strip() if title_el else ""
            city  = city_el.inner_text().strip()  if city_el  else ""
            href  = link_el.get_attribute("href") if link_el  else ""

            if href and href.startswith("/"):
                from urllib.parse import urlparse
                p = urlparse(target["url"])
                href = f"{p.scheme}://{p.netloc}{href}"

            if title and len(title) > 1:
                jobs.append({"title": title, "city": city, "url": href or target["url"]})
    except Exception as e:
        print(f"  [browser error] {target['name']}: {e}")
    return jobs

# ── WxPusher 推送 ────────────────────────────────────

def push_wxpusher(new_jobs: list[dict]):
    if not new_jobs:
        print("没有新职位，跳过推送")
        return
    if not WXPUSHER_APP_TOKEN or not WXPUSHER_UID:
        print("未配置 WxPusher，跳过推送")
        return

    groups: dict[str, list] = {}
    for job in new_jobs:
        groups.setdefault(job["company"], []).append(job)

    content = f"<h3>💊 新招聘信息 · {len(new_jobs)} 条</h3>"
    content += f"<p style='color:#888;font-size:12px'>{datetime.now().strftime('%Y-%m-%d %H:%M')}</p><hr>"
    for company, jobs in groups.items():
        content += f"<h4>🏢 {company}</h4><ul>"
        for job in jobs:
            city_tag = f" <span style='color:#888;font-size:12px'>({job['city']})</span>" if job.get("city") else ""
            content += f"<li><a href='{job['url']}'>{job['title']}</a>{city_tag}</li>"
        content += "</ul>"

    payload = {
        "appToken": WXPUSHER_APP_TOKEN,
        "content": content,
        "summary": f"新职位 {len(new_jobs)} 条 | {', '.join(list(groups.keys())[:3])}",
        "contentType": 2,
        "uids": [WXPUSHER_UID],
    }
    try:
        resp = requests.post("https://wxpusher.zjiecode.com/api/send/message", json=payload, timeout=10)
        result = resp.json()
        if result.get("code") == 1000:
            print(f"✅ WxPusher 推送成功，共 {len(new_jobs)} 条新职位")
        else:
            print(f"❌ WxPusher 推送失败: {result}")
    except Exception as e:
        print(f"❌ WxPusher 请求异常: {e}")

# ── 主流程 ───────────────────────────────────────────

def main():
    cache = load_cache()
    new_jobs = []

    # 1. Workday API 抓取（无需浏览器）
    for target in WORKDAY_TARGETS:
        print(f"🔍 抓取(API): {target['name']}")
        jobs = scrape_workday(target)
        print(f"   → 获取到 {len(jobs)} 条职位")
        for job in jobs:
            key = job_key(target["name"], job["title"], job.get("city", ""))
            if key not in cache:
                new_jobs.append({"company": target["name"], **job})
                cache[key] = datetime.now().strftime("%Y-%m-%d")
        time.sleep(1)

    # 2. 浏览器渲染抓取
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        for target in BROWSER_TARGETS:
            print(f"🔍 抓取(浏览器): {target['name']}")
            jobs = scrape_browser(target, page)
            print(f"   → 获取到 {len(jobs)} 条职位")
            for job in jobs:
                key = job_key(target["name"], job["title"], job.get("city", ""))
                if key not in cache:
                    new_jobs.append({"company": target["name"], **job})
                    cache[key] = datetime.now().strftime("%Y-%m-%d")
            time.sleep(2)

        browser.close()

    print(f"\n📊 共发现 {len(new_jobs)} 条新职位")
    save_cache(cache)
    push_wxpusher(new_jobs)

if __name__ == "__main__":
    main()
