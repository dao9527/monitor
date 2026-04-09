import asyncio
import json
import os
from datetime import datetime
from playwright.async_api import async_playwright
import requests

# --- 配置 ---
BASE_URL = "https://m.steamdt.com/inventory/d665bb297e6a858920e00181e5ff327f"
BARK_KEY = os.environ.get("BARK_KEY")
BARK_URL = f"https://api.day.app/{BARK_KEY}"
DATA_FILE = "inventory_data.json"
CHANGES_LOG_FILE = "changes_log.json"

async def close_all_popups(page):
    """关闭所有可能的弹窗"""
    selectors = [
        '.el-dialog__close', '[aria-label="Close"]', '[aria-label="关闭"]',
        '.close', 'button:has-text("确定")', 'button:has-text("知道了")',
        'button:has-text("关闭")', '.agreement-wrapper button', '.notice-dialog .close'
    ]
    for sel in selectors:
        try:
            for el in await page.query_selector_all(sel):
                if await el.is_visible():
                    await el.click(timeout=2000)
                    await page.wait_for_timeout(500)
        except:
            pass

async def is_last_page_by_pagination(page):
    """通过分页组件判断是否为最后一页（返回True表示无下一页）"""
    # 常见分页选择器
    next_selectors = [
        'button:has-text("下一页")',
        'a:has-text("下一页")',
        '.el-pagination .btn-next',
        '.pagination .next',
        'li.next a',
        '[aria-label="下一页"]',
        '.next:not(.disabled)'
    ]
    for sel in next_selectors:
        try:
            next_btn = await page.query_selector(sel)
            if next_btn:
                # 检查是否禁用
                is_disabled = await next_btn.evaluate(
                    'el => el.hasAttribute("disabled") || el.classList.contains("disabled") || el.getAttribute("aria-disabled") === "true"'
                )
                if not is_disabled:
                    return False  # 存在可用下一页
        except:
            pass
    return True  # 找不到可用下一页，视为最后一页

async def fetch_all_inventory():
    print(f"[{datetime.now()}] 启动浏览器...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        all_items = []
        previous_items = None
        page_num = 1
        max_pages = 30  # 安全上限

        try:
            while page_num <= max_pages:
                url = f"{BASE_URL}?page={page_num}"
                print(f"[{datetime.now()}] 正在请求第 {page_num} 页: {url}")

                await page.goto(url, timeout=30000)
                await page.wait_for_load_state('networkidle', timeout=15000)
                await close_all_popups(page)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)

                # 等待饰品容器出现（最多25秒）
                items = []
                for retry in range(2):
                    try:
                        await page.wait_for_function(
                            'document.querySelectorAll(".item-container").length > 0',
                            timeout=25000
                        )
                    except:
                        if retry == 0:
                            print(f"[{datetime.now()}] 第 {page_num} 页加载超时，刷新重试...")
                            await page.reload(timeout=30000)
                            await page.wait_for_load_state('networkidle', timeout=15000)
                            await close_all_popups(page)
                            continue
                        else:
                            print(f"[{datetime.now()}] 第 {page_num} 页最终无数据，停止翻页")
                            break

                    items = await page.evaluate('''() => {
                        const containers = document.querySelectorAll('.item-container');
                        return Array.from(containers).map(el => {
                            let name = 'Unknown Item';
                            const img = el.querySelector('img');
                            if (img && img.getAttribute('alt')) {
                                name = img.getAttribute('alt').trim();
                            } else {
                                const nameEl = el.querySelector('.name, .item-name, [class*="name"]');
                                if (nameEl) name = nameEl.innerText.trim();
                                else if (img && img.getAttribute('title')) name = img.getAttribute('title').trim();
                            }
                            return { name, count: 1 };
                        });
                    }''')
                    break

                if len(items) == 0:
                    break

                print(f"[{datetime.now()}] 第 {page_num} 页抓取到 {len(items)} 件饰品")

                # --- 智能终止条件 ---
                # 1. 优先使用分页器状态判断
                if page_num > 1 and await is_last_page_by_pagination(page):
                    print(f"[{datetime.now()}] 分页器显示无下一页，停止翻页")
                    all_items.extend(items)
                    break

                # 2. 如果当前页数据与上一页完全相同，且数据量小于30，视为重复结尾
                if previous_items is not None:
                    prev_set = {(i['name'], i['count']) for i in previous_items}
                    curr_set = {(i['name'], i['count']) for i in items}
                    if prev_set == curr_set and len(items) < 30:
                        print(f"[{datetime.now()}] 当前页数据与上一页相同且不足30件，停止翻页")
                        # 不再添加重复数据
                        break

                all_items.extend(items)
                previous_items = items

                # 如果本页不足30件，大概率是最后一页
                if len(items) < 30:
                    print(f"[{datetime.now()}] 当前页不足30件，视为最后一页")
                    break

                page_num += 1

        except Exception as e:
            print(f"[{datetime.now()}] 抓取异常: {e}")
        finally:
            await browser.close()

        print(f"[{datetime.now()}] 全部抓取完成，共 {len(all_items)} 件饰品")
        return all_items

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def compare_data(old, new):
    changes = []
    if not old: return changes
    old_dict = {i['name']: i['count'] for i in old}
    new_dict = {i['name']: i['count'] for i in new}
    for name, cnt in new_dict.items():
        if name not in old_dict:
            changes.append(f"➕ 新增: {name} (数量: {cnt})")
        elif old_dict[name] != cnt:
            changes.append(f"🔄 数量变动: {name} ({old_dict[name]} -> {cnt})")
    for name, cnt in old_dict.items():
        if name not in new_dict:
            changes.append(f"➖ 移除: {name} (数量: {cnt})")
    return changes

def send_bark(title, body):
    if not BARK_KEY: return
    try:
        requests.post(BARK_URL, data={"title": title, "body": body, "group": "SteamDT监控", "sound": "birdsong"}, timeout=10)
        print(f"[{datetime.now()}] Bark 通知已发送")
    except Exception as e:
        print(f"[{datetime.now()}] Bark 发送失败: {e}")

def run_monitor():
    print(f"\n--- 监控任务 {datetime.now()} ---")
    current = asyncio.run(fetch_all_inventory())
    if not current:
        print("抓取失败，终止")
        return
    previous = load_json(DATA_FILE)
    if previous is None:
        save_json(DATA_FILE, current)
        print("首次运行，已保存基准数据")
        return
    changes = compare_data(previous, current)
    if changes:
        print(f"检测到 {len(changes)} 项变动")
        log = load_json(CHANGES_LOG_FILE) or []
        timestamp = datetime.now().strftime("%H:%M")
        for c in changes:
            log.append(f"[{timestamp}] {c}")
        save_json(CHANGES_LOG_FILE, log)
    else:
        print("无变动")
    save_json(DATA_FILE, current)

def run_daily_report():
    print(f"\n--- 每日报告 {datetime.now()} ---")
    log = load_json(CHANGES_LOG_FILE) or []
    date_str = datetime.now().strftime("%Y年%m月%d日")
    body = f"截止 {date_str} 12:00，库存无变动。" if not log else f"【{date_str} 库存变动汇总】\n\n" + "\n".join(log)
    send_bark(f"📦 每日库存报告 ({date_str})", body)
    save_json(CHANGES_LOG_FILE, [])

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        run_daily_report()
    else:
        run_monitor()
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        run_daily_report()
    else:
        run_monitor()
