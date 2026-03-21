"""
招聘信息抓取脚本 v7
修复：
- 诺华 Workday selector 命中但读值失败 → 改为直接读 jobTitle 元素
- 拜耳/勃林格/GSK/艾伯维 URL 错误 → 修正或暂时移除
- tupu360 IP问题暂时搁置（非代码问题）
"""

import json
import os
import time
import random
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
    # Workday 英文职位常见词（不过滤）
    "director", "manager", "specialist", "associate", "lead",
    "oncology", "cardiology", "immunology", "hematology", "neurology",
    "outcomes", "safety", "pharmacology", "access", "health",
]
TARGET_CITIES = ["北京", "上海", "beijing", "shanghai"]

# ── Workday 目标（只保留能加载的）────────────────────
WORKDAY_TARGETS = [
    {
        "name": "诺华-医学部",
        "url": "https://novartis.wd3.myworkdayjobs.com/zh-CN/Novartis_Careers?q=medical",
        "search_url": "https://novartis.wd3.myworkdayjobs.com/zh-CN/Novartis_Careers?q=medical",
    },
    {
        "name": "拜耳-北京上海",
        "url": "https://bayer.wd3.myworkdayjobs.com/zh-CN/Bayer?q=medical",
        "search_url": "https://bayer.wd3.myworkdayjobs.com/zh-CN/Bayer?q=medical",
    },
    {
        "name": "GSK-医学部",
        "url": "https://gsk.wd5.myworkdayjobs.com/zh-CN/GSK_External_Career_Site?q=medical",
        "search_url": "https://gsk.wd5.myworkdayjobs.com/zh-CN/GSK_External_Career_Site?q=medical",
    },
    {
        "name": "艾伯维-北京上海",
        "url": "https://abbvie.wd1.myworkdayjobs.com/zh-CN/abbvie_global?q=medical",
        "search_url": "https://abbvie.wd1.myworkdayjobs.com/zh-CN/abbvie_global?q=medical",
    },
    {
        "name": "勃林格殷格翰-北京上海",
        "url": "https://boehringer-ingelheim.wd3.myworkdayjobs.com/zh-CN/Boehringer_Ingelheim_External_Career_Site?q=medical",
        "search_url": "https://boehringer-ingelheim.wd3.myworkdayjobs.com/zh-CN/Boehringer_Ingelheim_External_Career_Site?q=medical",
    },
]

# ── 浏览器目标 ────────────────────────────────────────
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
        "item_sel": "a[href*='/job/'], .job-tile, [class*='job-card'], li[class*='job']",
        "title_sel": "h2, h3, .job-title, span[class*='title']",
        "city_sel": ".location, .city, [class*='location']",
        "direct_link": True,
        "extra_wait": 8000,
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

ANTI_DETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
window.chrome = { runtime: {} };
"""

def make_browser(p):
    return p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
    )

def make_pc_context(browser):
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    ctx.add_init_script(ANTI_DETECT_SCRIPT)
    return ctx

def human_behavior(page):
    try:
        page.mouse.move(random.randint(100, 400), random.randint(100, 300))
        page.wait_for_timeout(random.randint(800, 1500))
        for _ in range(3):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)
    except Exception:
        pass

# ── Workday 抓取（关键修复）─────────────────────────

def scrape_workday_browser(target, browser):
    jobs = []
    ctx  = make_pc_context(browser)
    page = ctx.new_page()
    try:
        page.goto(target["url"], wait_until="domcontentloaded", timeout=50000)

        # 等职位列表渲染
        try:
            page.wait_for_selector(
                "[data-automation-id='jobTitle']",
                timeout=15000
            )
        except Exception:
            pass

        page.wait_for_timeout(3000)
        human_behavior(page)

        if DEBUG:
            print(f"  [DEBUG] title: {page.title()}")
            print(f"  [DEBUG] html: {page.content()[:600]}")

        # 直接读所有 jobTitle 元素（诺华已验证命中20个）
        title_els = page.query_selector_all("[data-automation-id='jobTitle']")
        if DEBUG:
            print(f"  [DEBUG] jobTitle elements: {len(title_els)}")

        for el in title_els:
            title = el.inner_text().strip()
            # 找同级或父级的 location
            try:
                parent = el.evaluate_handle("el => el.closest('li') || el.parentElement")
                city_el = parent.as_element().query_selector(
                    "[data-automation-id='locations'], [class*='location'], [class*='city']"
                ) if parent.as_element() else None
                city = city_el.inner_text().strip() if city_el else ""
            except Exception:
                city = ""

            if DEBUG:
                print(f"  [DEBUG] title='{title}' city='{city}'")

            if title and len(title) > 2:
                jobs.append({"title": title, "city": city})

        # 如果 jobTitle 没命中，尝试备用 selector
        if not jobs:
            for sel in ["li[class*='job'] a", "a[href*='/job/']", "a[href*='jobId']"]:
                items = page.query_selector_all(sel)
                if items:
                    if DEBUG:
                        print(f"  [DEBUG] fallback selector '{sel}' → {len(items)} 个")
                    for item in items:
                        title = item.inner_text().strip()
                        href  = item.get_attribute("href") or ""
                        if title and len(title) > 2:
                            jobs.append({"title": title, "city": "", "url": href})
                    break

    except Exception as e:
        print(f"  [workday error] {target['name']}: {e}")
    finally:
        ctx.close()

    if DEBUG:
        print(f"  [DEBUG] raw jobs: {jobs[:5]}")

    # 城市为空时不过滤（Workday 城市字段不稳定），只过滤医学关键词
    return [j for j in jobs if is_medical(j["title"])]

# ── 其他浏览器目标 ───────────────────────────────────

def scrape_browser(target, browser):
    jobs = []
    ctx  = make_pc_context(browser)
    page = ctx.new_page()
    try:
        page.goto(target["url"], wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(target["item_sel"], timeout=12000)
        except Exception:
            pass
        extra = target.get("extra_wait", 3000)
        page.wait_for_timeout(extra)
        human_behavior(page)

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
        browser = make_browser(p)

        # 1. Workday（诺华已验证可加载）
        for target in WORKDAY_TARGETS:
            print(f"🔍 Workday: {target['name']}")
            jobs = scrape_workday_browser(target, browser)
            print(f"   → {len(jobs)} 条")
            process(target["name"], jobs, "workday", target.get("search_url", ""))
            time.sleep(random.uniform(2, 4))

        # 2. 其他（罗氏、默沙东）
        for target in BROWSER_TARGETS:
            print(f"🔍 浏览器: {target['name']}")
            jobs = scrape_browser(target, browser)
            print(f"   → {len(jobs)} 条")
            process(target["name"], jobs, "browser", target.get("search_url", ""))
            time.sleep(random.uniform(2, 4))

        browser.close()

    print(f"\n📊 共发现 {len(new_jobs)} 条新职位")
    save_cache(cache)
    push_wxpusher(new_jobs)

if __name__ == "__main__":
    main()
