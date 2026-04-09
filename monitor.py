import json
import os
from datetime import datetime
import requests

# --- 配置 ---
STEAMID = "76561199506993686"          # 目标SteamID64
APPID = 730                            # CS2/CSGO
CONTEXTID = 2                          # 公开库存上下文
BARK_KEY = os.environ.get("BARK_KEY")
BARK_URL = f"https://api.day.app/{BARK_KEY}"
DATA_FILE = "inventory_data.json"
CHANGES_LOG_FILE = "changes_log.json"

def fetch_steam_inventory():
    """
    从Steam官方接口获取库存数据。
    返回值：
        - dict : {饰品名称: 数量}  成功时
        - None : 对方库存私密或请求失败
    """
    url = f"https://steamcommunity.com/inventory/{STEAMID}/{APPID}/{CONTEXTID}?l=schinese&count=2000"
    print(f"[{datetime.now()}] 正在请求Steam接口...")
    
    try:
        response = requests.get(url, timeout=30)
        
        if response.status_code in (403, 404):
            print(f"[{datetime.now()}] 库存当前为私密或不可访问 (HTTP {response.status_code})，跳过本次监控。")
            return None
        
        response.raise_for_status()
        data = response.json()
        
        if not data.get("success"):
            error_msg = data.get("error", "")
            if "private" in error_msg.lower() or "friends" in error_msg.lower():
                print(f"[{datetime.now()}] 库存私密，跳过本次监控。")
            else:
                print(f"[{datetime.now()}] Steam API返回错误: {data}")
            return None
        
        # 构建描述字典：classid_instanceid -> market_hash_name
        desc_map = {}
        for desc in data.get("descriptions", []):
            key = f"{desc.get('classid')}_{desc.get('instanceid')}"
            desc_map[key] = desc.get("market_hash_name", "Unknown Item")
        
        # 按名称统计数量
        inventory = {}
        for asset in data.get("assets", []):
            classid = asset.get("classid")
            instanceid = asset.get("instanceid")
            amount = int(asset.get("amount", 1))
            key = f"{classid}_{instanceid}"
            name = desc_map.get(key, "Unknown Item")
            
            # 累加数量
            inventory[name] = inventory.get(name, 0) + amount
        
        print(f"[{datetime.now()}] 成功获取到 {len(inventory)} 种饰品，总计 {sum(inventory.values())} 件。")
        return inventory
        
    except Exception as e:
        print(f"[{datetime.now()}] 请求异常: {e}")
        return None

def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_json(file_path, data):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def compare_data(old, new):
    """对比两个库存字典，返回变动列表"""
    changes = []
    if not old:
        return changes
    
    all_names = set(old.keys()) | set(new.keys())
    for name in all_names:
        old_count = old.get(name, 0)
        new_count = new.get(name, 0)
        if old_count == 0 and new_count > 0:
            changes.append(f"➕ 新增: {name} (数量: {new_count})")
        elif old_count > 0 and new_count == 0:
            changes.append(f"➖ 移除: {name} (数量: {old_count})")
        elif old_count != new_count:
            changes.append(f"🔄 数量变动: {name} ({old_count} -> {new_count})")
    return changes

def send_bark(title, body):
    if not BARK_KEY:
        print("未配置 BARK_KEY，跳过通知")
        return
    try:
        requests.post(BARK_URL, data={"title": title, "body": body, "group": "Steam监控", "sound": "birdsong"}, timeout=10)
        print(f"[{datetime.now()}] Bark 通知已发送")
    except Exception as e:
        print(f"[{datetime.now()}] Bark 发送失败: {e}")

def run_monitor():
    print(f"\n--- 监控任务 {datetime.now()} ---")
    current = fetch_steam_inventory()
    
    if current is None:
        print("本次监控跳过（库存私密或请求失败），基准数据与变动日志均保持不变。")
        return
    
    previous = load_json(DATA_FILE)
    if previous is None:
        save_json(DATA_FILE, current)
        print("首次成功运行，已保存基准数据。")
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
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        run_daily_report()
    else:
        run_monitor()
