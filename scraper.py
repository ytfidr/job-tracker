"""
招聘信息抓取脚本
支持平台：tupu360、mokahr、ajinga、moseeker、roche
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

TARGETS = [
    # ── tupu360 平台 ──
    {
        "name": "辉瑞-医学部",
        "platform": "tupu360",
        "url": "https://pfizer.tupu360.com/api/position/search",
        "params": {"lang": "zh_CN", "type": "SOCIALRECRUITMENT", "function": "医学类", "pageSize": 50, "pageNo": 1},
    },
    {
        "name": "赛诺菲-北京上海",
        "platform": "tupu360",
        "url": "https://sanofi.tupu360.com/api/position/search",
        "params": {"lang": "zh_CN", "type": "SOCIALRECRUITMENT", "city": "上海,北京", "pageSize": 50, "pageNo": 1},
    },
    {
        "name": "AZ-医学部",
        "platform": "tupu360",
        "url": "https://az.tupu360.com/api/position/search",
        "params": {"lang": "zh_CN", "type": "SOCIALRECRUITMENT", "department": "Medical 医学事务部", "pageSize": 50, "pageNo": 1},
    },
    {
        "name": "礼来-医学研发",
        "platform": "tupu360",
        "url": "https://lilly.tupu360.com/api/position/search",
        "params": {"lang": "zh_CN", "type": "SOCIALRECRUITMENT", "function": "研发与医学", "pageSize": 50, "pageNo": 1},
    },
    {
        "name": "强生-医学",
        "platform": "tupu360",
        "url": "https://chinacampus.jnj.com.cn/api/position/search",
        "params": {"lang": "zh_CN", "type": "SOCIALRECRUITMENT", "function": "医学事务", "pageSize": 50, "pageNo": 1},
    },
    {
        "name": "诺和诺德-北京上海",
        "platform": "tupu360",
        "url": "https://novonordisk.tupu360.com/api/position/search",
        "params": {"lang": "zh_CN", "type": "SOCIALRECRUITMENT", "city": "上海,北京", "pageSize": 50, "pageNo": 1},
    },
    {
        "name": "百时美施贵宝-北京上海",
        "platform": "tupu360",
        "url": "https://bms.tupu360.com/api/position/search",
        "params": {"lang": "zh_CN", "type": "SOCIALRECRUITMENT", "city": "上海,北京", "pageSize": 50, "pageNo": 1},
    },
    # ── mokahr 平台 ──
    {
        "name": "葛兰素史克-医学部",
        "platform": "mokahr",
        "url": "https://app.mokahr.com/api/campus/v1/jobs",
        "params": {"orgSlug": "gsk", "zhineng[0]": "196802", "pageSize": 50, "pageNo": 0},
    },
    {
        "name": "拜耳-北京上海",
        "platform": "mokahr",
        "url": "https://app.mokahr.com/api/campus/v1/jobs",
        "params": {"orgSlug": "bayer", "location[0]": "上海市", "location[1]": "北京市", "pageSize": 50, "pageNo": 0},
    },
    # ── ajinga 平台 ──
    {
        "name": "默克-北京上海",
        "platform": "ajinga",
        "url": "https://www.ajinga.com/api/recruiting/company/12666/job-list",
        "params": {"city": "112,131", "page": 1, "page_size": 50},
    },
    {
        "name": "艾伯维-北京上海",
        "platform": "ajinga",
        "url": "https://www.ajinga.com/api/recruiting/company/12699/job-list",
        "params": {"city": "112,131", "page": 1, "page_size": 50},
    },
    {
        "name": "勃林格殷格翰-北京上海",
        "platform": "ajinga",
        "url": "https://www.ajinga.com/api/recruiting/company/6143/job-list",
        "params": {"city": "112,131", "page": 1, "page_size": 50},
    },
    {
        "name": "默沙东-北京上海",
        "platform": "ajinga",
        "url": "https://www.ajinga.com/api/recruiting/company/13471/job-list",
        "params": {"city": "112,131", "page": 1, "page_size": 50},
    },
    # ── 浏览器渲染平台（moseeker / roche）──
    {
        "name": "诺华-北京上海",
        "platform": "browser",
        "url": "https://wx44ac83c95d1cf3aa.wx.moseeker.com/m/position?wechat_signature=ZDhlNDA0MjNlMmMzZmZkN2M5YzZiZWVjYzZjYjA1ZjM1ZTg0ZjUzZA%3D%3D&recom=HCndexxxxe&share_time=1773980824488#1773984877046",
        "selector": ".position-item",
        "title_sel": ".position-name",
        "city_sel": ".position-city",
    },
    {
        "name": "罗氏-北京上海",
        "platform": "browser",
        "url": "https://careers.roche.com/cn/zh/china-medical-affairs-and-access-jobs",
        "selector": ".job-listing-item, .jobs-list-item, article.job",
        "title_sel": "h3, h2, .job-title",
        "city_sel": ".location, .job-location",
    },
]

# ── 工具函数 ─────────────────────────────────────────

def job_key(company: str, title: str, city: str) -> str:
    raw = f"{company}|{title}|{city}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_cache() -> dict:
    os.makedirs("cache", exist_ok=True)
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ── 各平台抓取 ───────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Accept": "application/json",
    "Referer": "https://app.mokahr.com/",
}


def scrape_tupu360(target: dict) -> list[dict]:
    """tupu360 平台直接请求 JSON API"""
    jobs = []
    try:
        r = requests.get(target["url"], params=target["params"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        # 尝试常见 key 路径
        items = (
            data.get("data", {}).get("list")
            or data.get("data", {}).get("content")
            or data.get("list")
            or data.get("content")
            or []
        )
        for item in items:
            title = item.get("positionName") or item.get("name") or item.get("title") or ""
            city  = item.get("cityName")     or item.get("city") or item.get("workPlace") or ""
            pid   = item.get("positionId")   or item.get("id")   or ""
            # 构造招聘页 URL（tupu360 通用格式）
            base  = target["url"].replace("/api/position/search", "")
            link  = f"{base}/position/{pid}" if pid else base
            if title:
                jobs.append({"title": title, "city": city, "url": link})
    except Exception as e:
        print(f"  [tupu360 error] {target['name']}: {e}")
    return jobs


def scrape_mokahr(target: dict) -> list[dict]:
    """mokahr 平台 API"""
    jobs = []
    try:
        r = requests.get(target["url"], params=target["params"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = data.get("result", {}).get("jobs") or data.get("jobs") or []
        for item in items:
            title = item.get("name") or item.get("title") or ""
            city  = item.get("locationName") or item.get("cityName") or ""
            jid   = item.get("code") or item.get("id") or ""
            org   = target["params"].get("orgSlug", "")
            link  = f"https://app.mokahr.com/social-recruitment/{org}/148387#/job/{jid}" if jid else ""
            if title:
                jobs.append({"title": title, "city": city, "url": link})
    except Exception as e:
        print(f"  [mokahr error] {target['name']}: {e}")
    return jobs


def scrape_ajinga(target: dict) -> list[dict]:
    """ajinga 平台 API"""
    jobs = []
    try:
        r = requests.get(target["url"], params=target["params"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = data.get("data", {}).get("list") or data.get("list") or data.get("jobs") or []
        for item in items:
            title = item.get("title") or item.get("name") or item.get("job_title") or ""
            city  = item.get("city_name") or item.get("city") or item.get("work_city") or ""
            jid   = item.get("id") or item.get("job_id") or ""
            link  = f"https://www.ajinga.com/job/{jid}" if jid else target["url"]
            if title:
                jobs.append({"title": title, "city": city, "url": link})
    except Exception as e:
        print(f"  [ajinga error] {target['name']}: {e}")
    return jobs


def scrape_browser(target: dict, page) -> list[dict]:
    """用 Playwright 抓取需要 JS 渲染的页面"""
    jobs = []
    try:
        page.goto(target["url"], wait_until="networkidle", timeout=30000)
        time.sleep(3)
        items = page.query_selector_all(target["selector"])
        for item in items:
            title_el = item.query_selector(target["title_sel"])
            city_el  = item.query_selector(target["city_sel"])
            title = title_el.inner_text().strip() if title_el else ""
            city  = city_el.inner_text().strip()  if city_el  else ""
            link_el = item.query_selector("a")
            href  = link_el.get_attribute("href") if link_el else ""
            if href and not href.startswith("http"):
                from urllib.parse import urljoin
                href = urljoin(target["url"], href)
            if title:
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

    # 按公司分组
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
        "summary": f"新职位 {len(new_jobs)} 条 | {', '.join(list(groups.keys())[:3])}...",
        "contentType": 2,
        "uids": [WXPUSHER_UID],
    }
    try:
        resp = requests.post(
            "https://wxpusher.zjiecode.com/api/send/message",
            json=payload,
            timeout=10,
        )
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

    # 判断是否有需要浏览器的目标
    need_browser = any(t["platform"] == "browser" for t in TARGETS)

    browser_page = None
    playwright_ctx = None

    if need_browser:
        playwright_ctx = sync_playwright().start()
        browser_obj = playwright_ctx.chromium.launch(headless=True)
        browser_page = browser_obj.new_page()

    try:
        for target in TARGETS:
            print(f"🔍 抓取: {target['name']}")
            platform = target["platform"]

            if platform == "tupu360":
                jobs = scrape_tupu360(target)
            elif platform == "mokahr":
                jobs = scrape_mokahr(target)
            elif platform == "ajinga":
                jobs = scrape_ajinga(target)
            elif platform == "browser":
                jobs = scrape_browser(target, browser_page)
            else:
                jobs = []

            print(f"   → 获取到 {len(jobs)} 条职位")

            for job in jobs:
                key = job_key(target["name"], job["title"], job.get("city", ""))
                if key not in cache:
                    new_jobs.append({
                        "company": target["name"],
                        "title":   job["title"],
                        "city":    job.get("city", ""),
                        "url":     job.get("url", ""),
                    })
                    cache[key] = datetime.now().strftime("%Y-%m-%d")

            time.sleep(1)  # 礼貌性延迟

    finally:
        if playwright_ctx:
            browser_page.context.browser.close()
            playwright_ctx.stop()

    print(f"\n📊 共发现 {len(new_jobs)} 条新职位")
    save_cache(cache)
    push_wxpusher(new_jobs)


if __name__ == "__main__":
    main()