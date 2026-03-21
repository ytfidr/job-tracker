"""
招聘信息抓取脚本 v5
- tupu360：Playwright + 微信UA（放弃API）
- Workday：Playwright 浏览器渲染（放弃API）
- 罗氏：Playwright 浏览器渲染（已验证可用）
- 推送：无链接依赖，信息驱动
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
DEBUG              = os.environ.get("DEBUG", "false").lower() == "true"

MEDICAL_KEYWORDS = [
    "医学", "medical", "MSL", "临床", "clinical", "药物警戒",
    "pharmacovigilance", "regulatory", "注册", "研发", "科学",
    "药学", "affairs", "advisor", "scientist", "evidence",
]
TARGET_CITIES = ["北京", "上海", "beijing", "shanghai"]

# ── tupu360 目标 ──────────────────────────────────────
TUPU_TARGETS = [
    {"name": "辉瑞-医学部",           "slug": "pfizer"},
    {"name": "赛诺菲-北京上海",       "slug": "sanofi"},
    {"name": "AZ-医学部",             "slug": "az"},
    {"name": "礼来-医学研发",         "slug": "lilly"},
    {"name": "强生-医学",             "slug": "jnj"},
    {"name": "诺和诺德-北京上海",     "slug": "novonordisk"},
    {"name": "百时美施贵宝-北京上海", "slug": "bms"},
]

# ── Workday 目标 ──────────────────────────────────────
WORKDAY_TARGETS = [
    {
        "name": "诺华-医学部",
        "url": "https://novartis.wd3.myworkdayjobs.com/Novartis_Careers?q=medical&locationCountry=5dab0caf4c2a410c8e5f67e96e7e6a63",
        "search_url": "https://novartis.wd3.myworkdayjobs.com/Novartis_Careers?q=medical",
    },
    {
        "name": "拜耳-北京上海",
        "url": "https://bayer.wd3.myworkdayjobs.com/Bayer?q=medical&locationCountry=a30a87ed25634629aa64ce4da97eff7b",
        "search_url": "https://bayer.wd3.myworkdayjobs.com/Bayer?q=medical",
    },
    {
        "name": "GSK-医学部",
        "url": "https://gsk.wd5.myworkdayjobs.com/GSK_External_Career_Site?q=medical+affairs",
        "search_url": "https://gsk.wd5.myworkdayjobs.com/GSK_External_Career_Site?q=medical+affairs",
    },
    {
        "name": "艾伯维-北京上海",
        "url": "https://abbvie.wd1.myworkdayjobs.com/abbvie_global?q=medical&locationCountry=a30a87ed25634629aa64ce4da97eff7b",
        "search_url": "https://abbvie.wd1.myworkdayjobs.com/abbvie_global?q=medical",
    },
    {
        "name": "勃林格殷格翰-北京上海",
        "url": "https://boehringer-ingelheim.wd3.myworkdayjobs.com/Boehringer_Ingelheim_External_Career_Site?q=medical",
        "search_url": "https://boehringer-ingelheim.wd3.myworkdayjobs.com/Boehringer_Ingelheim_External_Career_Site?q=medical",
    },
]

# ── 其他浏览器目标 ────────────────────────────────────
BROWSER_TARGETS = [
    {
        "name": "罗氏-北京上海",
        "url": "https://careers.roche.com/cn/zh/china-medical-affairs-and-access-jobs",
        "search_url": "https://careers.roche.com/cn/zh/china-medical-affairs-and-access-jobs",
        "item_sel": ".job-listing-item, .jobs-list-item, article.job, .job-card, li.job",
        "title_sel": "h3, h2, .job-title",
        "city_sel": ".location, .job-location, .city",
        "direct_link": True,
    },
    {
        "name": "默沙东-北京上海",
        "url": "https://jobs.merck.com/us/en/search-results?location=China&keywords=medical",
        "search_url": "https://jobs.merck.com/us/en/search-results?location=China&keywords=medical",
        "item_sel": ".job-tile, article, li.job, .search-result-item, [class*='job-card']",
        "title_sel": "h2, h3, .job-title, a",
        "city_sel": ".location, .city, .job-location",
        "direct_link": False,
    },
]

# ── 工具函数 ─────────────────────────────────────────

def job_key(company, title, city):
    return hashlib.md5(f"{company}|{title}|{city}".encode()).hexdigest()

def load_cache():
    os.makedirs("cache", exist_ok=True)
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def is_medical(title):
    t = title.lower()
    return any(kw.lower() in t for kw in MEDICAL_KEYWORDS)

def is_target_city(city):
    c = city.lower()
    return any(f.lower() in c for f in TARGET_CITIES)

def make_wechat_context(browser):
    return browser.new_context(
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.47",
        viewport={"width": 390, "height": 844},
    )

def make_pc_context(browser):
    return browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
    )

def scroll_and_wait(page, times=3):
    for _ in range(times):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)

# ── tupu360 抓取 ─────────────────────────────────────

def scrape_tupu360(target, browser):
    jobs = []
    slug = target["slug"]
    url  = f"https://careersite.tupu360.com/{slug}/social-recruitment"
    ctx  = make_wechat_context(browser)
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=40000)
        scroll_and_wait(page, 4)

        if DEBUG:
            print(f"  [DEBUG] title: {page.title()}")
            print(f"  [DEBUG] url: {page.url}")
            print(f"  [DEBUG] html: {page.content()[:500]}")

        items = []
        for sel in ["a[href*='position']", ".position-item", ".job-item",
                    ".job-card", "li.item", "[class*='position']"]:
            items = page.query_selector_all(sel)
            if items:
                if DEBUG:
                    print(f"  [DEBUG] selector '{sel}' → {len(items)} 个")
                break

        for item in items:
            title_el = item.query_selector(".position-name, .job-name, .name, h3, h2, span")
            city_el  = item.query_selector(".position-city, .city, .location, .work-place")
            title = title_el.inner_text().strip() if title_el else item.inner_text().strip()
            city  = city_el.inner_text().strip()  if city_el  else ""
            title = title.split("\n")[0].strip()
            if title and len(title) > 2:
                jobs.append({"title": title, "city": city})

    except Exception as e:
        print(f"  [tupu360 error] {target['name']}: {e}")
    finally:
        ctx.close()

    if DEBUG:
        print(f"  [DEBUG] raw: {jobs[:3]}")

    return [j for j in jobs if is_medical(j["title"]) and (not j["city"] or is_target_city(j["city"]))]

# ── Workday 浏览器抓取 ───────────────────────────────

def scrape_workday_browser(target, browser):
    jobs = []
    ctx  = make_pc_context(browser)
    page = ctx.new_page()
    try:
        page.goto(target["url"], wait_until="networkidle", timeout=40000)
        scroll_and_wait(page, 3)

        if DEBUG:
            print(f"  [DEBUG] title: {page.title()}")
            print(f"  [DEBUG] html: {page.content()[:500]}")

        items = []
        for sel in ["li[class*='job']", "li[class*='Job']",
                    "[data-automation-id='jobTitle']",
                    ".job-listing-item", "article[class*='job']"]:
            items = page.query_selector_all(sel)
            if items:
                if DEBUG:
                    print(f"  [DEBUG] selector '{sel}' → {len(items)} 个")
                break

        for item in items:
            title_el = item.query_selector("[data-automation-id='jobTitle'], h3, h2, a")
            city_el  = item.query_selector("[data-automation-id='locations'], .location, .city")
            title = title_el.inner_text().strip() if title_el else ""
            city  = city_el.inner_text().strip()  if city_el  else ""
            if title:
                jobs.append({"title": title, "city": city})

    except Exception as e:
        print(f"  [workday error] {target['name']}: {e}")
    finally:
        ctx.close()

    if DEBUG:
        print(f"  [DEBUG] raw: {jobs[:3]}")

    return [j for j in jobs if is_medical(j["title"]) and (not j["city"] or is_target_city(j["city"]))]

# ── 其他浏览器目标 ───────────────────────────────────

def scrape_browser(target, browser):
    jobs = []
    ctx  = make_pc_context(browser)
    page = ctx.new_page()
    try:
        page.goto(target["url"], wait_until="networkidle", timeout=40000)
        scroll_and_wait(page, 3)

        items = page.query_selector_all(target["item_sel"])
        if DEBUG:
            print(f"  [DEBUG] selector → {len(items)} 个")

        for item in items:
            title_el = item.query_selector(target["title_sel"])
            city_el  = item.query_selector(target["city_sel"])
            link_el  = item.query_selector("a") if target.get("direct_link") else None
            title = title_el.inner_text().strip() if title_el else ""
            city  = city_el.inner_text().strip()  if city_el  else ""
            href  = ""
            if link_el:
                href = link_el.get_attribute("href") or ""
                if href.startswith("/"):
                    from urllib.parse import urlparse
                    p = urlparse(target["url"])
                    href = f"{p.scheme}://{p.netloc}{href}"
            if title and len(title) > 1:
                jobs.append({"title": title, "city": city, "url": href})

    except Exception as e:
        print(f"  [browser error] {target['name']}: {e}")
    finally:
        ctx.close()

    return jobs

# ── WxPusher 推送 ────────────────────────────────────

def push_wxpusher(new_jobs):
    if not new_jobs:
        print("没有新职位，跳过推送")
        return
    if not WXPUSHER_APP_TOKEN or not WXPUSHER_UID:
        print("未配置 WxPusher，跳过推送")
        return

    groups = {}
    for job in new_jobs:
        groups.setdefault(job["company"], []).append(job)

    content = f"<h3>💊 新招聘信息 · {len(new_jobs)} 条</h3>"
    content += f"<p style='color:#888;font-size:12px'>{datetime.now().strftime('%Y-%m-%d %H:%M')}</p><hr>"

    for company, jobs in groups.items():
        content += f"<h4>🏢 {company}</h4><ul>"
        for job in jobs:
            city_str   = f"（{job['city']}）" if job.get("city") else ""
            url        = job.get("url", "")
            source     = job.get("source", "browser")
            search_url = job.get("search_url", "")

            if url:
                content += f"<li><a href='{url}'>{job['title']}</a>{city_str}</li>"
            elif search_url:
                tag = "📱 微信渠道" if source == "tupu360" else "🔎 官网搜索"
                content += (
                    f"<li>{job['title']}{city_str}<br>"
                    f"<span style='color:#888;font-size:12px'>{tag}｜"
                    f"<a href='{search_url}'>前往查看</a></span></li>"
                )
            else:
                content += f"<li>{job['title']}{city_str}</li>"
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
            print(f"✅ WxPusher 推送成功，共 {len(new_jobs)} 条")
        else:
            print(f"❌ WxPusher 推送失败: {result}")
    except Exception as e:
        print(f"❌ WxPusher 请求异常: {e}")

# ── 主流程 ───────────────────────────────────────────

def main():
    cache    = load_cache()
    new_jobs = []

    def process(company_name, jobs, source, search_url=""):
        for job in jobs:
            key = job_key(company_name, job["title"], job.get("city", ""))
            if key not in cache:
                new_jobs.append({
                    "company":    company_name,
                    "title":      job["title"],
                    "city":       job.get("city", ""),
                    "url":        job.get("url", ""),
                    "source":     source,
                    "search_url": search_url,
                })
                cache[key] = datetime.now().strftime("%Y-%m-%d")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 1. tupu360（微信UA）
        for target in TUPU_TARGETS:
            print(f"🔍 tupu360: {target['name']}")
            jobs = scrape_tupu360(target, browser)
            print(f"   → {len(jobs)} 条")
            search_url = f"https://careersite.tupu360.com/{target['slug']}/social-recruitment"
            process(target["name"], jobs, "tupu360", search_url)
            time.sleep(2)

        # 2. Workday（浏览器渲染）
        for target in WORKDAY_TARGETS:
            print(f"🔍 Workday: {target['name']}")
            jobs = scrape_workday_browser(target, browser)
            print(f"   → {len(jobs)} 条")
            process(target["name"], jobs, "workday", target.get("search_url", ""))
            time.sleep(2)

        # 3. 其他（罗氏、默沙东）
        for target in BROWSER_TARGETS:
            print(f"🔍 浏览器: {target['name']}")
            jobs = scrape_browser(target, browser)
            print(f"   → {len(jobs)} 条")
            process(target["name"], jobs, "browser", target.get("search_url", ""))
            time.sleep(2)

        browser.close()

    print(f"\n📊 共发现 {len(new_jobs)} 条新职位")
    save_cache(cache)
    push_wxpusher(new_jobs)

if __name__ == "__main__":
    main()
