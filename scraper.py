"""
招聘信息抓取脚本
全部使用 Playwright 浏览器渲染抓取
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
    {
        "name": "辉瑞-医学部",
        "url": "https://pfizer.tupu360.com/position/list?lang=zh_CN&type=SOCIALRECRUITMENT&function=%E5%8C%BB%E5%AD%A6%E7%B1%BB",
    },
    {
        "name": "赛诺菲-北京上海",
        "url": "https://sanofi.tupu360.com/position/list?lang=zh_CN&type=SOCIALRECRUITMENT&city=%E4%B8%8A%E6%B5%B7",
    },
    {
        "name": "AZ-医学部",
        "url": "https://az.tupu360.com/position/list?lang=zh_CN&type=SOCIALRECRUITMENT&department=Medical%20%E5%8C%BB%E5%AD%A6%E4%BA%8B%E5%8A%A1%E9%83%A8",
    },
    {
        "name": "礼来-医学研发",
        "url": "https://lilly.tupu360.com/position/list?lang=zh_CN&type=SOCIALRECRUITMENT&function=%E7%A0%94%E5%8F%91%E4%B8%8E%E5%8C%BB%E5%AD%A6",
    },
    {
        "name": "强生-医学",
        "url": "https://chinacampus.jnj.com.cn/position/list?lang=zh_CN&type=SOCIALRECRUITMENT&function=%E5%8C%BB%E5%AD%A6%E4%BA%8B%E5%8A%A1",
    },
    {
        "name": "诺和诺德-北京上海",
        "url": "https://novonordisk.tupu360.com/position/list?lang=zh_CN&type=SOCIALRECRUITMENT&city=%E4%B8%8A%E6%B5%B7",
    },
    {
        "name": "百时美施贵宝-北京上海",
        "url": "https://bms.tupu360.com/position/list?lang=zh_CN&type=SOCIALRECRUITMENT&city=%E4%B8%8A%E6%B5%B7",
    },
    {
        "name": "葛兰素史克-医学部",
        "url": "https://app.mokahr.com/apply/gsk/148067?sourceToken=59cd93e13cb396c7658c4a487e155561#/jobs?zhineng%5B0%5D=196802",
    },
    {
        "name": "拜耳-北京上海",
        "url": "https://app.mokahr.com/social-recruitment/bayer/148387#/jobs?location%5B0%5D=%E4%B8%8A%E6%B5%B7%E5%B8%82&location%5B1%5D=%E5%8C%97%E4%BA%AC%E5%B8%82",
    },
    {
        "name": "默克-北京上海",
        "url": "https://www.ajinga.com/recruiting/company/12666/job-list?wechatShare=1&aj_source=Merck_WeChat&aj_code=Button#page=1&page_size=10&city=112,131",
    },
    {
        "name": "艾伯维-北京上海",
        "url": "https://www.ajinga.com/recruiting/company/12699/job-list?wechatShare=1#page=1&page_size=10&city=112,131",
    },
    {
        "name": "勃林格殷格翰-北京上海",
        "url": "https://www.ajinga.com/recruiting/company/6143/job-list?lReferId=1089ebT3&aj_source=WeChat_BIsocial&aj_code=landingpage",
    },
    {
        "name": "默沙东-北京上海",
        "url": "https://www.ajinga.com/recruiting/company/13471/job-list?wechatShare=1&aj_source=MSD_WeChat&aj_code=WeChat#page=1&page_size=10&city=112,131",
    },
    {
        "name": "诺华-北京上海",
        "url": "https://wx44ac83c95d1cf3aa.wx.moseeker.com/m/position?wechat_signature=ZDhlNDA0MjNlMmMzZmZkN2M5YzZiZWVjYzZjYjA1ZjM1ZTg0ZjUzZA%3D%3D&recom=HCndexxxxe&share_time=1773980824488#1773984877046",
    },
    {
        "name": "罗氏-北京上海",
        "url": "https://careers.roche.com/cn/zh/china-medical-affairs-and-access-jobs",
    },
]

# 各平台职位选择器配置
SELECTORS = [
    # tupu360
    {
        "host": "tupu360.com",
        "item": ".position-item, .job-item, .position-card, li.item",
        "title": ".position-name, .job-name, .name, h3, h2",
        "city": ".position-city, .job-city, .city, .location",
        "link": "a",
    },
    # jnj (强生，也是 tupu360)
    {
        "host": "jnj.com.cn",
        "item": ".position-item, .job-item, .position-card, li.item",
        "title": ".position-name, .job-name, .name, h3, h2",
        "city": ".position-city, .job-city, .city, .location",
        "link": "a",
    },
    # mokahr
    {
        "host": "mokahr.com",
        "item": ".job-list-item, .position-item, li.job, .job-card",
        "title": ".job-name, .position-name, h3, h2, .name",
        "city": ".job-city, .location, .city",
        "link": "a",
    },
    # ajinga
    {
        "host": "ajinga.com",
        "item": ".job-item, .position-item, .job-card, li.item, .job-list-item",
        "title": ".job-title, .position-name, h3, h2, .title",
        "city": ".job-city, .city, .location, .work-city",
        "link": "a",
    },
    # moseeker
    {
        "host": "moseeker.com",
        "item": ".position-item, .job-item, li.item, .item",
        "title": ".position-name, .job-name, .name, h3, h2",
        "city": ".position-city, .city, .location",
        "link": "a",
    },
    # roche
    {
        "host": "roche.com",
        "item": ".job-listing-item, .jobs-list-item, article.job, .job-card, li.job",
        "title": "h3, h2, .job-title, .position-name",
        "city": ".location, .job-location, .city",
        "link": "a",
    },
]

# ── 工具函数 ─────────────────────────────────────────

def get_selector(url: str) -> dict:
    for s in SELECTORS:
        if s["host"] in url:
            return s
    return SELECTORS[-1]  # 默认用 roche 的选择器


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


# ── 浏览器抓取 ───────────────────────────────────────

def scrape_page(page, target: dict) -> list[dict]:
    jobs = []
    sel = get_selector(target["url"])
    try:
        page.goto(target["url"], wait_until="networkidle", timeout=40000)
        # 等待内容加载，滚动触发懒加载
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)

        items = page.query_selector_all(sel["item"])
        print(f"   → DOM 找到 {len(items)} 个元素")

        for item in items:
            title_el = item.query_selector(sel["title"])
            city_el  = item.query_selector(sel["city"])
            link_el  = item.query_selector(sel["link"])

            title = title_el.inner_text().strip() if title_el else ""
            city  = city_el.inner_text().strip()  if city_el  else ""
            href  = link_el.get_attribute("href") if link_el  else ""

            if href and href.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(target["url"])
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            elif href and not href.startswith("http"):
                href = target["url"]

            if title and len(title) > 1:
                jobs.append({"title": title, "city": city, "url": href or target["url"]})

    except Exception as e:
        print(f"  [error] {target['name']}: {e}")
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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.47",
            viewport={"width": 390, "height": 844},
        )
        page = context.new_page()

        for target in TARGETS:
            print(f"🔍 抓取: {target['name']}")
            jobs = scrape_page(page, target)
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

            time.sleep(2)

        browser.close()

    print(f"\n📊 共发现 {len(new_jobs)} 条新职位")
    save_cache(cache)
    push_wxpusher(new_jobs)


if __name__ == "__main__":
    main()