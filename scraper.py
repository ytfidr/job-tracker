"""
招聘信息抓取脚本 v4
- tupu360 系列：使用 careersite.tupu360.com（PC端，无需微信）
- Workday：诺华/拜耳/GSK/艾伯维/勃林格
- 浏览器渲染：默克/默沙东/罗氏
筛选：中国区 北京/上海 医学相关岗位
推送：WxPusher
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
    "Accept": "application/json, text/html",
}

# 医学相关关键词过滤
MEDICAL_KEYWORDS = ["医学", "medical", "MSL", "MA ", "药物警戒", "研发", "clinical", "临床", "科学", "药学", "注册"]

# ── tupu360 PC端目标 ──────────────────────────────────
TUPU_TARGETS = [
    {"name": "辉瑞-医学部",       "slug": "pfizer",       "city": ["北京", "上海"], "keyword": "医学"},
    {"name": "赛诺菲-北京上海",   "slug": "sanofi",       "city": ["北京", "上海"], "keyword": ""},
    {"name": "AZ-医学部",         "slug": "az",           "city": ["北京", "上海"], "keyword": "医学"},
    {"name": "礼来-医学研发",     "slug": "lilly",        "city": ["北京", "上海"], "keyword": "医学"},
    {"name": "强生-医学",         "slug": "jnj",          "city": ["北京", "上海"], "keyword": "医学"},
    {"name": "诺和诺德-北京上海", "slug": "novonordisk",  "city": ["北京", "上海"], "keyword": ""},
    {"name": "百时美施贵宝-北京上海", "slug": "bms",      "city": ["北京", "上海"], "keyword": ""},
]

# ── Workday API 目标 ──────────────────────────────────
WORKDAY_TARGETS = [
    {
        "name": "诺华-北京上海",
        "url": "https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/Novartis_Careers/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "medical affairs China", "facets": {}},
        "city_filter": ["beijing", "shanghai", "北京", "上海"],
    },
    {
        "name": "拜耳-北京上海",
        "url": "https://bayer.wd3.myworkdayjobs.com/wday/cxs/bayer/Bayer/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "medical China", "facets": {}},
        "city_filter": ["beijing", "shanghai", "北京", "上海"],
    },
    {
        "name": "GSK-医学部",
        "url": "https://gsk.wd5.myworkdayjobs.com/wday/cxs/gsk/GSK_External_Career_Site/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "medical affairs China", "facets": {}},
        "city_filter": ["beijing", "shanghai", "北京", "上海"],
    },
    {
        "name": "艾伯维-北京上海",
        "url": "https://abbvie.wd1.myworkdayjobs.com/wday/cxs/abbvie/abbvie_global/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "medical China", "facets": {}},
        "city_filter": ["beijing", "shanghai", "北京", "上海"],
    },
    {
        "name": "勃林格殷格翰-北京上海",
        "url": "https://boehringer-ingelheim.wd3.myworkdayjobs.com/wday/cxs/boehringer-ingelheim/Boehringer_Ingelheim_External_Career_Site/jobs",
        "body": {"limit": 20, "offset": 0, "searchText": "medical China", "facets": {}},
        "city_filter": ["beijing", "shanghai", "北京", "上海"],
    },
]

# ── 浏览器渲染目标 ────────────────────────────────────
BROWSER_TARGETS = [
    {
        "name": "默沙东-北京上海",
        "url": "https://jobs.merck.com/us/en/search-results?location=China&keywords=medical+affairs",
        "item_sel": ".job-tile, article, li.job, .search-result-item, [class*='job-card']",
        "title_sel": "h2, h3, .job-title, a",
        "city_sel": ".location, .city, .job-location",
    },
    {
        "name": "罗氏-北京上海",
        "url": "https://careers.roche.com/cn/zh/china-medical-affairs-and-access-jobs",
        "item_sel": ".job-listing-item, .jobs-list-item, article.job, .job-card, li.job",
        "title_sel": "h3, h2, .job-title",
        "city_sel": ".location, .job-location, .city",
    },
    {
        "name": "默克-北京上海",
        "url": "https://jobs.emdgroup.com/jobs?facetcountry=cn&facetcity=beijing,shanghai",
        "item_sel": ".job-tile, .job-item, article.job, [class*='job']",
        "title_sel": "h3, h2, .job-title, a",
        "city_sel": ".location, .city, [class*='location']",
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
    if not MEDICAL_KEYWORDS:
        return True
    t = title.lower()
    return any(kw.lower() in t for kw in MEDICAL_KEYWORDS)

def is_target_city(city, city_filter):
    if not city_filter:
        return True
    c = city.lower()
    return any(f.lower() in c for f in city_filter)

# ── tupu360 PC端 API ─────────────────────────────────

def scrape_tupu360_pc(target):
    jobs = []
    slug = target["slug"]
    cities = target.get("city", [""])
    keyword = target.get("keyword", "")

    for city in (cities or [""]):
        params = {
            "recruitmentType": "SOCIALRECRUITMENT",
            "pageNo": 1,
            "pageSize": 50,
            "currentLang": "zh_CN",
        }
        if city:
            params["cityName"] = city
        if keyword:
            params["positionName"] = keyword

        # 尝试两种常见 API 路径
        for api_path in [
            f"https://careersite.tupu360.com/{slug}/api/position/list",
            f"https://{slug}.tupu360.com/api/position/search",
        ]:
            try:
                r = requests.get(api_path, params=params, headers=HEADERS, timeout=15)
                if r.status_code != 200:
                    continue
                data = r.json()
                items = (
                    data.get("data", {}).get("list")
                    or data.get("data", {}).get("content")
                    or data.get("list")
                    or []
                )
                if not items:
                    continue
                for item in items:
                    title = item.get("positionName") or item.get("name") or ""
                    loc   = item.get("cityName") or item.get("workCity") or city
                    pid   = item.get("positionId") or item.get("id") or ""
                    link  = f"https://careersite.tupu360.com/{slug}/position/detail?positionId={pid}&recruitmentType=SOCIALRECRUITMENT" if pid else ""
                    if title:
                        jobs.append({"title": title, "city": loc, "url": link})
                break  # 成功则不再尝试备用路径
            except Exception as e:
                print(f"  [tupu360 warn] {api_path}: {e}")
                continue

    # 去重
    seen, unique = set(), []
    for j in jobs:
        k = j["title"] + j["city"]
        if k not in seen:
            seen.add(k)
            unique.append(j)
    return unique

# ── Workday API ──────────────────────────────────────

def scrape_workday(target):
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
        city_filter = target.get("city_filter", [])
        for item in items:
            title = item.get("title") or item.get("name") or ""
            city  = item.get("locationsText") or item.get("location") or ""
            ext   = item.get("externalPath") or ""
            base  = target["url"].split("/wday/")[0]
            link  = base + ext if ext.startswith("/") else ext
            if title and is_target_city(city, city_filter) and is_medical(title):
                jobs.append({"title": title, "city": city, "url": link})
    except Exception as e:
        print(f"  [workday error] {target['name']}: {e}")
    return jobs

# ── 浏览器渲染 ───────────────────────────────────────

def scrape_browser(target, page):
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
            print(f"✅ WxPusher 推送成功，共 {len(new_jobs)} 条")
        else:
            print(f"❌ WxPusher 推送失败: {result}")
    except Exception as e:
        print(f"❌ WxPusher 请求异常: {e}")

# ── 主流程 ───────────────────────────────────────────

def main():
    cache = load_cache()
    new_jobs = []

    def process(company_name, jobs):
        for job in jobs:
            key = job_key(company_name, job["title"], job.get("city", ""))
            if key not in cache:
                new_jobs.append({"company": company_name, **job})
                cache[key] = datetime.now().strftime("%Y-%m-%d")

    # 1. tupu360 PC端
    for target in TUPU_TARGETS:
        print(f"🔍 tupu360: {target['name']}")
        jobs = scrape_tupu360_pc(target)
        print(f"   → {len(jobs)} 条")
        process(target["name"], jobs)
        time.sleep(1)

    # 2. Workday API
    for target in WORKDAY_TARGETS:
        print(f"🔍 Workday: {target['name']}")
        jobs = scrape_workday(target)
        print(f"   → {len(jobs)} 条")
        process(target["name"], jobs)
        time.sleep(1)

    # 3. 浏览器渲染
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        for target in BROWSER_TARGETS:
            print(f"🔍 浏览器: {target['name']}")
            jobs = scrape_browser(target, page)
            print(f"   → {len(jobs)} 条")
            process(target["name"], jobs)
            time.sleep(2)
        browser.close()

    print(f"\n📊 共发现 {len(new_jobs)} 条新职位")
    save_cache(cache)
    push_wxpusher(new_jobs)

if __name__ == "__main__":
    main()
