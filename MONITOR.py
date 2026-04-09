import asyncio
import json
import os
from datetime import datetime
from playwright.async_api import async_playwright
import requests

# --- 配置 ---
URL = "https://m.steamdt.com/inventory/d665bb297e6a858920e00181e5ff327f"
BARK_KEY = os.environ.get("BARK_KEY")  # 从 GitHub Secrets 读取
BARK_URL = f"https://api.day.app/{BARK_KEY}"
DATA_FILE = "inventory_data.json"
CHANGES_LOG_FILE = "changes_log.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

async def fetch_inventory():
    """使用 Playwright 渲染页面并提取饰品数据"""
    print(f"[{datetime.now()}] 启动浏览器...")
    async with async_playwright() as p:
        # 启动 Chromium，无头模式
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(URL, timeout=30000)
            # 等待饰品容器加载
            await page.wait_for_selector('.item-container', timeout=10000)
            
            # 提取所有饰品项
            items = await page.evaluate('''() => {
                const containers = document.querySelectorAll('.item-container');
                const result = [];
                containers.forEach(el => {
                    const img = el.querySelector('img');
                    const name = img ? img.getAttribute('alt') : 'Unknown Item';
                    // 尝试查找数量元素，如果没有就默认为 1
                    let count = 1;
                    // 这里可以根据实际页面结构调整数量查找逻辑
                    // 例如：const countEl = el.querySelector('.count');
                    result.push({ name: name.trim(), count: count });
                });
                return result;
            }''')
            
            print(f"[{datetime.now()}] 抓取到 {len(items)} 件饰品")
            return items
        except Exception as e:
            print(f"[{datetime.now()}] 抓取失败: {e}")
            return None
        finally:
            await browser.close()

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
    """核心监控逻辑"""
    print(f"\n--- 监控任务 {datetime.now()} ---")
    current = asyncio.run(fetch_inventory())
    if not current:
        return
    
    previous = load_json(DATA_FILE)
    if previous is None:
        save_json(DATA_FILE, current)
        print("首次运行，已保存基准数据")
        return
    
    changes = compare_data(previous, current)
    if changes:
        print(f"检测到 {len(changes)} 项变动")
        # 记录变动日志
        log = load_json(CHANGES_LOG_FILE) or []
        timestamp = datetime.now().strftime("%H:%M")
        for c in changes:
            log.append(f"[{timestamp}] {c}")
        save_json(CHANGES_LOG_FILE, log)
    else:
        print("无变动")
    
    save_json(DATA_FILE, current)

def run_daily_report():
    """每日汇总报告（由独立工作流触发）"""
    print(f"\n--- 每日报告 {datetime.now()} ---")
    log = load_json(CHANGES_LOG_FILE) or []
    date_str = datetime.now().strftime("%Y年%m月%d日")
    if not log:
        body = f"截止 {date_str} 12:00，库存无变动。"
    else:
        body = f"【{date_str} 库存变动汇总】\n\n" + "\n".join(log)
    send_bark(f"📦 每日库存报告 ({date_str})", body)
    # 清空日志
    save_json(CHANGES_LOG_FILE, [])

if __name__ == "__main__":
    # 根据命令行参数决定执行哪个任务
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        run_daily_report()
    else:
        run_monitor()
