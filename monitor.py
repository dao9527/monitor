import asyncio
import json
import os
from datetime import datetime
from playwright.async_api import async_playwright
import requests

# --- 配置 ---
URL = "https://m.steamdt.com/inventory/d665bb297e6a858920e00181e5ff327f"
BARK_KEY = os.environ.get("BARK_KEY")
BARK_URL = f"https://api.day.app/{BARK_KEY}"
DATA_FILE = "inventory_data.json"
CHANGES_LOG_FILE = "changes_log.json"

async def fetch_inventory():
    """使用 Playwright 渲染 + 滚动加载所有饰品"""
    print(f"[{datetime.now()}] 启动浏览器抓取...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
        )
        try:
            await page.goto(URL, timeout=60000)
            
            # 等待页面基本框架加载
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(3)  # 额外等待 JS 渲染

            print("开始滚动加载所有物品...")

            # 无限滚动加载直到没有新内容
            last_height = await page.evaluate("document.body.scrollHeight")
            item_count = 0
            max_scroll_attempts = 30  # 防止无限循环

            for attempt in range(max_scroll_attempts):
                # 滚动到底部
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)  # 等待加载

                # 检查新高度
                new_height = await page.evaluate("document.body.scrollHeight")
                current_items = await page.evaluate("""() => document.querySelectorAll('div[class*="item"], div[class*="skin"], img').length""")
                
                if new_height == last_height and current_items > item_count:
                    print(f"已加载完成，共 {current_items} 件饰品")
                    break
                
                last_height = new_height
                item_count = current_items
                print(f"第 {attempt+1} 次滚动，已加载 {item_count} 件...")

            # 提取物品数据（根据实际页面结构调整）
            items = await page.evaluate('''() => {
                const result = [];
                // 常见可能的容器选择器，优先匹配含图片或名称的元素
                const containers = document.querySelectorAll('div[class*="item"], div[class*="skin"], div[class*="inventory"], li');
                
                containers.forEach(el => {
                    const img = el.querySelector('img');
                    const nameEl = el.querySelector('span, div[class*="name"], p, [class*="text"]');
                    let name = 'Unknown';
                    if (nameEl) {
                        name = nameEl.textContent.trim();
                    } else if (img) {
                        name = img.getAttribute('alt') || img.getAttribute('title') || 'Unknown Item';
                    }
                    
                    // 尝试提取数量（常见 class 如 count, num, amount）
                    let count = 1;
                    const countEl = el.querySelector('[class*="count"], [class*="num"], [class*="amount"], .badge, span');
                    if (countEl) {
                        const countText = countEl.textContent.trim();
                        const numMatch = countText.match(/\\d+/);
                        if (numMatch) count = parseInt(numMatch[0]);
                    }
                    
                    if (name && name.length > 2 && !name.includes('加载')) {
                        result.push({ name: name.trim(), count: count });
                    }
                });
                return result;
            }''')
            
            # 去重（按名称）
            unique_items = {}
            for item in items:
                key = item['name']
                if key in unique_items:
                    unique_items[key]['count'] += item['count']
                else:
                    unique_items[key] = item
            final_items = list(unique_items.values())
            
            print(f"[{datetime.now()}] 最终抓取到 {len(final_items)} 件唯一饰品")
            return final_items

        except Exception as e:
            print(f"[{datetime.now()}] 抓取失败: {e}")
            # 调试：保存页面截图和HTML（GitHub Actions 日志可见）
            await page.screenshot(path="error_screenshot.png")
            with open("error_page.html", "w", encoding="utf-8") as f:
                f.write(await page.content())
            return None
        finally:
            await browser.close()

# 其余函数（load_json, save_json, compare_data, send_bark, run_monitor, run_daily_report）保持原样不变
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
        requests.post(BARK_URL, json={"title": title, "body": body, "group": "SteamDT监控", "sound": "birdsong"}, timeout=10)
        print(f"[{datetime.now()}] Bark 通知已发送")
    except Exception as e:
        print(f"[{datetime.now()}] Bark 发送失败: {e}")

def run_monitor():
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
        body = f"【{date_str} 库存变动汇总】\n\n" + "\n".join(log[-50:])  # 只取最近50条避免太长
    send_bark(f"📦 每日库存报告 ({date_str})", body)
    save_json(CHANGES_LOG_FILE, [])  # 清空

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
