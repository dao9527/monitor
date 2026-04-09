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
    """最终极简版 - 完全避免正则和复杂语法"""
    print(f"[{datetime.now()}] 启动浏览器抓取...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
        )
        try:
            await page.goto(URL, timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=40000)
            await asyncio.sleep(6)

            print("开始滚动加载所有饰品...")

            for attempt in range(35):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)
                if attempt % 8 == 0:
                    print(f"已滚动 {attempt} 次...")

            # 极简 JS：只用 includes 和 split，完全无正则
            items = await page.evaluate('''() => {
                const result = [];
                const seen = new Set();
                const lines = document.body.innerText.split('\n');
                
                for (let line of lines) {
                    line = line.trim();
                    if (line.length > 20 && line.includes('|') && 
                        (line.includes('崭新') || line.includes('磨损') || line.includes('出厂'))) {
                        
                        let name = line;
                        // 简单清理多余空格
                        while (name.includes('  ')) name = name.replace('  ', ' ');
                        name = name.trim();
                        
                        // 简单找数字
                        let count = 1;
                        let i = 0;
                        while (i < line.length) {
                            if (line[i] >= '0' && line[i] <= '9') {
                                let num = '';
                                while (i < line.length && line[i] >= '0' && line[i] <= '9') {
                                    num += line[i];
                                    i++;
                                }
                                if (num.length > 0) {
                                    let n = parseInt(num);
                                    if (n > 1) count = n;
                                    break;
                                }
                            }
                            i++;
                        }
                        
                        if (!seen.has(name)) {
                            seen.add(name);
                            result.push({name: name, count: count});
                        }
                    }
                }
                return result;
            }''')
            
            print(f"[{datetime.now()}] 最终抓取到 {len(items)} 件库存饰品")
            
            if items and len(items) > 0:
                print("前 6 个示例：")
                for item in items[:6]:
                    print(f"   • {item['name']} × {item['count']}")
            else:
                print("未抓取到饰品，请查看 error_page.html")
            
            return items

        except Exception as e:
            print(f"[{datetime.now()}] 抓取失败: {e}")
            try:
                await page.screenshot(path="error_screenshot.png")
                with open("error_page.html", "w", encoding="utf-8") as f:
                    f.write(await page.content())
                print("✅ 已保存 error_screenshot.png 和 error_page.html，请下载查看")
            except:
                pass
            return None
        finally:
            await browser.close()

# ==================== 以下部分无需修改 ====================
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
        requests.post(BARK_URL, json={
            "title": title, 
            "body": body, 
            "group": "SteamDT监控", 
            "sound": "birdsong"
        }, timeout=10)
        print(f"[{datetime.now()}] Bark 通知已发送")
    except Exception as e:
        print(f"[{datetime.now()}] Bark 发送失败: {e}")

def run_monitor():
    print(f"\n--- 监控任务 {datetime.now()} ---")
    current = asyncio.run(fetch_inventory())
    if not current or len(current) < 20:
        print("抓取数量不足，跳过本次更新")
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
        save_json(CHANGES_LOG_FILE, log[-100:])
        send_bark("🔔 SteamDT 库存变动提醒", "\n".join(changes[:8]))
    else:
        print("无变动")
    
    save_json(DATA_FILE, current)

def run_daily_report():
    print(f"\n--- 每日报告 {datetime.now()} ---")
    log = load_json(CHANGES_LOG_FILE) or []
    date_str = datetime.now().strftime("%Y年%m月%d日")
    body = f"【{date_str} 库存变动汇总】\n\n" + "\n".join(log[-50:]) if log else f"截止 {date_str} 12:00，库存无变动。"
    send_bark(f"📦 每日库存报告 ({date_str})", body)
    save_json(CHANGES_LOG_FILE, [])

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        run_daily_report()
    else:
        run_monitor()
