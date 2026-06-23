import requests
from bs4 import BeautifulSoup
import time
import os
import subprocess
import pandas as pd
import threading
from datetime import datetime

# ================== Git 推送配置 ==================
GITHUB_REPO = "Juineii/yuna_yeti0414"        # 请替换为您的仓库名
GITHUB_BRANCH = "main"                          # 分支名（main 或 master）
PUSH_INTERVAL = 60                              # 推送检查间隔（秒）
# GitHub Personal Access Token 优先从环境变量 GITHUB_TOKEN 读取

# CSV 文件配置
CSV_FILE = "AND2BLE澳门签售.csv"
CSV_HEADERS = ["时间", "商品名称", "库存变化", "单笔销量"]

# ================== 全局线程安全变量 ==================
lines_since_last_push = 0          # 自上次推送后新增的CSV行数
lines_lock = threading.Lock()      # 保护计数器的锁
file_lock = threading.Lock()       # 保护CSV文件读写的锁


# ================== Git 推送函数（带超时保护，返回布尔值） ==================
def git_push_update():
    """
    将最新的 CSV 文件提交并推送到 GitHub
    返回: True 表示推送成功, False 表示失败
    """
    try:
        token = os.environ.get('GITHUB_TOKEN')
        if not token:
            print("⚠️ 环境变量 GITHUB_TOKEN 未设置，跳过 Git 推送")
            return False

        remote_url = f"https://{token}@github.com/{GITHUB_REPO}.git"

        subprocess.run(['git', 'add', CSV_FILE], check=True, capture_output=True, timeout=30)

        result = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True, timeout=30)
        if result.returncode != 0:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_msg = f"自动更新数据 {timestamp}"
            subprocess.run(['git', 'commit', '-m', commit_msg], check=True, capture_output=True, timeout=30)
            subprocess.run(
                ['git', 'push', remote_url, f'HEAD:{GITHUB_BRANCH}'],
                check=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            print(f"✅ 已推送到 GitHub: {commit_msg}")
            return True
        else:
            print("⏭️ CSV 文件无变化，跳过推送")
            return True

    except subprocess.TimeoutExpired:
        print("❌ Git 操作超时 (30秒)，推送失败")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ Git 操作失败: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        print(f"❌ 推送过程中发生错误: {e}")
        return False


def write_to_csv(row_data):
    """
    使用 pandas concat 方式写入 CSV，并累加计数器（不触发推送）
    row_data: [时间, 商品名称, 库存变化, 单笔销量]
    """
    global lines_since_last_push
    try:
        columns = CSV_HEADERS
        new_row = pd.DataFrame([row_data], columns=columns)

        with file_lock:   # 防止与推送线程同时操作文件
            if os.path.exists(CSV_FILE):
                df_existing = pd.read_csv(CSV_FILE, encoding='utf-8-sig')
            else:
                df_existing = pd.DataFrame(columns=columns)

            df_updated = pd.concat([df_existing, new_row], ignore_index=True)
            df_updated.to_csv(CSV_FILE, index=False, encoding='utf-8-sig')

        # 增加计数器（线程安全）
        with lines_lock:
            lines_since_last_push += 1

    except Exception as e:
        print(f"写入 CSV 文件时出错: {e}")


# ================== 推送工作线程 ==================
def push_worker():
    global lines_since_last_push
    while True:
        time.sleep(PUSH_INTERVAL)
        with lines_lock:
            pending = lines_since_last_push
        if pending > 0:
            print(f"⏰ 定时推送：有 {pending} 条新数据待推送")
            with file_lock:
                success = git_push_update()
            if success:
                with lines_lock:
                    lines_since_last_push = 0
                print("✅ 推送成功，计数器已归零")
            else:
                print("⚠️ 推送失败，下次再试")


# ================== 主监控逻辑 ==================
if __name__ == "__main__":
    # 启动推送守护线程
    push_thread = threading.Thread(target=push_worker, daemon=True)
    push_thread.start()

    # 监控的目标 URL
    url = "https://yeye.duanjv.top/public/home/store/goodsDetail?id=31647"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0'
    }

    previous_inventory = None
    # 初始获取（保持原有逻辑，包括写入）
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        inventory_span = soup.find('span', class_='inventory')
        if inventory_span:
            initial_inventory = inventory_span.get('data-inventory')
            if initial_inventory is not None:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                change_text = f"初始库存: {initial_inventory}"
                row = [current_time, "yeti", change_text, 0]
                write_to_csv(row)
                print(f"时间: {current_time} 商品: yeti 库存变化: {change_text} 销量: 0")
                previous_inventory = initial_inventory
            else:
                print("未找到 data-inventory 属性")
        else:
            print("未找到 inventory span")
    except requests.exceptions.RequestException as e:
        print(f"获取网页时出错: {e}")

    # 开始监控循环
    try:
        while True:
            time.sleep(10)
            try:
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                inventory_span = soup.find('span', class_='inventory')
                if inventory_span:
                    current_inventory = inventory_span.get('data-inventory')
                    if current_inventory is not None:
                        if previous_inventory is None:
                            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            change_text = f"初始库存: {current_inventory}"
                            row = [current_time, "yeti", change_text, 0]
                            write_to_csv(row)
                            print(f"时间: {current_time} 商品: yeti 库存变化: {change_text} 销量: 0")
                            previous_inventory = current_inventory
                        else:
                            try:
                                prev_int = int(previous_inventory)
                                curr_int = int(current_inventory)
                                if curr_int != prev_int:
                                    difference = prev_int - curr_int
                                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    change_text = f"{previous_inventory}->{current_inventory}"
                                    row = [current_time, "yeti", change_text, difference]
                                    write_to_csv(row)
                                    print(f"时间: {current_time} 商品: yeti 库存变化: {change_text} 销量: {difference}")
                                    previous_inventory = current_inventory
                            except ValueError:
                                print(f"库存值不是整数: {previous_inventory} 和 {current_inventory}")
                    else:
                        print("未找到 data-inventory 属性")
                else:
                    print("未找到 inventory span")
            except requests.exceptions.RequestException as e:
                print(f"获取网页时出错: {e}")
    except KeyboardInterrupt:
        print("\n监控程序被用户终止")
        # 退出前推送剩余数据
        with lines_lock:
            pending = lines_since_last_push
        if pending > 0:
            print(f"正在推送剩余的 {pending} 条数据...")
            with file_lock:
                success = git_push_update()
            if success:
                with lines_lock:
                    lines_since_last_push = 0
                print("✅ 剩余数据已推送")
            else:
                print("⚠️ 剩余数据推送失败，请手动检查")
        else:
            print("无待推送数据")