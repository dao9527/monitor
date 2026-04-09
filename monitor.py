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
    """强力关闭所有可能的弹窗和遮罩层"""
    close_selectors = [
        '.el-dialog__close',
        '.el-message-box__close',
        '.el-overlay-dialog .el-icon-close',
        '[aria-label="Close"]',
        '[aria-label="关闭"]',
        '.close',
        'button:has-text("确定")',
        'button:has-text("知道了")',
        'button:has-text("关闭")',
        'button:has-text("接受")',
        '.agreement-wrapper button',
        '.notice-dialog .close',
        '.dialog-footer button',
        '.el-button:has-text("确定")',
        '.el-button:has-text("取消")',
    ]
    closed = False
    for selector in close_selectors:
        try:
            elements = await page.query_selector_all(selector)
            for el in elements:
                if await el.is_visible():
                    await el.click(timeout=2000)
                    print(f"[{datetime.now()}] 关闭弹窗: {selector}")
                    closed = True
                    await page.wait_for_timeout(500)
        except:
            pass
    return closed

async def fetch_all_inventory():
    """强化版翻页抓取，增加重试和网络等待"""
    print(f"[{datetime.now()}] 启动浏览器...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        all_items = []
        page_num = 1
        max_pages = 100

        try:
            while page_num <= max_pages:
                url = f"{BASE_URL}?page={page_num}"
                print(f"[{datetime.now()}] 正在请求第 {page_num} 页: {url}")

                await page.goto(url, timeout=30000)
                await page.wait_for_load_state('networkidle', timeout=15000)

                # 多次尝试关闭弹窗
                for _ in range(3):
                    if await close_all_popups(page):
                        await page.wait_for_timeout(1000)

                # 滚动触发懒加载
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)
                await page.evaluate("window.scrollTo(0, 0)")

                # 等待饰品容器出现，最多30秒
                items = []
                retry_count = 0
                while retry_count < 2 and len(items) == 0:
                    try:
                        await page.wait_for_function(
                            'document.querySelectorAll(".item-container").length > 0',
                            timeout=30000
                        )
                    except Exception as e:
                        print(f"[{datetime.now()}] 第 {page_num} 页等待容器超时，重试 {retry_count+1}/2")
                        retry_count += 1
                        if retry_count < 2:
                            await page.reload(timeout=30000)
                            await page.wait_for_load_state('networkidle', timeout=15000)
                            await close_all_popups(page)
                            continue
                        else:
                            print(f"[{datetime.now()}] 重试失败，跳过该页")
                            break

                    items = await page.evaluate('''() => {
                        const containers = document.querySelectorAll('.item-container');
                        const result = [];
                        containers.forEach(el => {
                            const img = el.querySelector('img');
                            const name = img ? img.getAttribute('alt') : 'Unknown Item';
                            let count = 1;
                            result.push({ name: name.trim(), count: count });
                        });
                        return result;
                    }''')
                    if len(items) == 0:
                        retry_count += 1
                        if retry_count < 2:
                            print(f"[{datetime.now()}] 第 {page_num} 页提取为0，重试...")
                            await page.reload(timeout=30000)
                            await page.wait_for_load_state('networkidle', timeout=15000)
                            await close_all_popups(page)

                if len(items) == 0:
                    print(f"[{datetime.now()}] 第 {page_num} 页最终无饰品，停止翻页")
                    break

                print(f"[{datetime.now()}] 第 {page_num} 页抓取到 {len(items)} 件饰品")
                all_items.extend(items)

                if len(items) < 30:
                    print(f"[{datetime.now()}] 当前页不足30件，视为最后一页")
                    break

                page_num += 1

        except Exception as e:
            print(f"[{datetime.now()}] 抓取过程中出现异常: {e}")
        finally:
            await browser.close()

        print(f"[{datetime.now()}] 全部抓取完成，共 {len(all_items)} 件饰品")
        return all_items

def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_json(file_path, data):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def compare_data(old, new):
    changes = []
    if not old:
        return changes
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
    if not BARK_KEY:
        print("未配置 BARK_KEY，跳过通知")
        return
    try:
        requests.post(BARK_URL, data={"title": title, "body": body, "group": "SteamDT监控", "sound": "birdsong"}, timeout=10)
        print(f"[{datetime.now()}] Bark 通知已发送")
    except Exception as e:
        print(f"[{datetime.now()}] Bark 发送失败: {e}")

def run_monitor():
    print(f"\n--- 监控任务 {datetime.now()} ---")
    current = asyncio.run(fetch_all_inventory())
    if not current or len(current) == 0:
        print("抓取失败或返回0件，本次监控终止")
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
    if not log:
        body = f"截止 {date_str} 12:00，库存无变动。"
    else:
        body = f"【{date_str} 库存变动汇总】\n\n" + "\n".join(log)
    send_bark(f"📦 每日库存报告 ({date_str})", body)
    save_json(CHANGES_LOG_FILE, [])

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        run_daily_report()
    else:
        run_monitor()
