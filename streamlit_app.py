import streamlit as st
import requests
import time
import re
import random
import os
import json
import pandas as pd
import concurrent.futures
import statistics
import socket
from datetime import datetime
import urllib3

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 极速版配置
# ===========================
st.set_page_config(page_title="VLESS 极速版", page_icon="⚡", layout="wide")
RESULT_FILE = "scan_results.json"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 2. 核心函数优化：激进超时控制
# ===========================

def get_china_latency_fast(ip):
    """极速版国测：压缩超时，多端口并发"""
    ports = [443, 2052] # 仅测试最常用的两个端口
    lats = []
    for port in ports:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.4) # 极速超时：400ms 连不上就视为不佳
            t1 = time.perf_counter()
            s.connect((ip, port))
            lats.append((time.perf_counter() - t1) * 1000)
            s.close()
        except: pass
    return int(statistics.mean(lats)) if lats else 888 # 连不上给个高延迟值

# (保留你原有的 ping0_tcp_test, sync_dns 等函数，但增加超时控制)

# ===========================
# 3. 后台逻辑整合：精简扫描池
# ===========================

def background_worker_fast():
    while True:
        try:
            # 1. 智能筛选池：从爬取的几百个里只随机挑 40 个，大大缩短测试总时间
            pool_raw = []
            urls = ["https://www.cloudflare.com/ips-v4", "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
            for u in urls:
                try: 
                    ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(u, timeout=5).text)
                    pool_raw.extend(ips)
                except: pass
            
            # 精简：只取 40 个进行深度测试
            final_pool = [{"ip": ip, "type": "hot"} for ip in random.sample(list(set(pool_raw)), min(len(pool_raw), 40))]

            results = []
            # 提高并发数到 30，几乎瞬间完成
            with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
                def run_quick_test(node):
                    ip = node['ip']
                    cn_lat = get_china_latency_fast(ip)
                    if cn_lat > 500: return None # 过滤国内连通性差的
                    
                    # 快速获取基础信息，不再进行耗时的 2MB 下载测试
                    # 改为小文件测试 (200KB) 提速
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=200000", headers={"Host": "speed.cloudflare.com"}, timeout=2)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    score = 1000 - cn_lat + (speed * 50)
                    return {**node, "score": round(score,1), "cn_lat": cn_lat, "speed": round(speed,2)}

                futs = [ex.submit(run_quick_test, n) for n in final_pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: results.append(res)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                # 写入结果
                with open(RESULT_FILE, "w") as f:
                    json.dump({"last_run": datetime.now().strftime("%H:%M:%S"), "winner": winner, "table": results[:20]}, f)
                # 同步 DNS
                sync_dns(winner['ip'])
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(600)

# ===========================
# 4. 前端优化：缓存优先加载
# ===========================
if "worker_started" not in st.session_state:
    import threading
    threading.Thread(target=background_worker_fast, daemon=True).start()
    st.session_state.worker_started = True

st.title("⚡ VLESS 极速自动化监控")

# 检查是否有历史结果，哪怕是旧的也先显示出来
if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f:
        data = json.load(f)
    # ... 显示逻辑 (同前) ...
    st.success(f"已加载最新优选数据 (更新时间: {data['last_run']})")
    # (展示仪表盘和表格)
else:
    st.info("🚀 极速扫描已启动！首次运行约需 15-20 秒，请稍候...")
    st.progress(0.5)

time.sleep(10)
st.rerun()
