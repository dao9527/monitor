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

async def close_popups(page):
    """尝试关闭常见的弹窗和遮罩层"""
    # 常见关闭按钮选择器
    close_selectors = [
        '.el-dialog__close',           # Element UI 弹窗关闭按钮
        '.el-message-box__close',      # Element UI 消息框关闭
        '.close',                      # 通用 close 类
        '[aria-label="Close"]',
        'button:has-text("确定")',
        'button:has-text("知道了")',
        'button:has-text("关闭")',
        '.notice-dialog .close',
        '.agreement-wrapper button',   # 协议弹窗的按钮
    ]
    for selector in close_selectors:
        try:
            elements = await page.query_selector_all(selector)
            for el in elements:
                if await el.is_visible():
                    await el.click(timeout=2000)
                    print(f"[{datetime.now()}] 已关闭弹窗: {selector}")
                    await page.wait_for_timeout(500)
        except:
            pass

async def fetch_all_inventory():
    """通过修改 URL 参数翻页抓取全部饰品"""
    print(f"[{datetime.now()}] 启动浏览器...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        all_items = []
        page_num = 1
        max_pages = 50  # 防止无限循环

        try:
            while page_num <= max_pages:
                url = f"{BASE_URL}?page={page_num}"
                print(f"[{datetime.now()}] 正在抓取第 {page_num} 页: {url}")
                
                await page.goto(url, timeout=30000)
                await page.wait_for_selector('.item-container', timeout=10000)
                
                # 尝试关闭可能出现的弹窗
                await close_popups(page)
                
                # 提取当前页饰品
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
                
                print(f"[{datetime.now()}] 第 {page_num} 页抓取到 {len(items)} 件饰品")
                
                if len(items) == 0:
                    print(f"[{datetime.now()}] 第 {page_num} 页没有饰品，可能已到末尾")
                    break
                    
                all_items.extend(items)
                
                # 检查是否还有下一页（通过判断当前页饰品数量是否小于30，或查看分页器状态）
                if len(items) < 30:
                    # 如果不足一页，说明是最后一页
                    print(f"[{datetime.now()}] 当前页不足30件，视为最后一页")
                    break
                    
                page_num += 1
                
        except Exception as e:
            print(f"[{datetime.now()}] 抓取过程中出错: {e}")
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
    if not current:
        print("抓取失败，本次监控终止")
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
