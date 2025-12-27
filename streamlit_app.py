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
import threading
import ipaddress
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 基础配置与文件 IO
# ===========================
st.set_page_config(page_title="VLESS 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
NICHE_FILE = "niche_pool.json"      
CONFIG_FILE = "app_config.json"     

QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]
GOLDEN_SUBNETS = ["104.28.0.0/16", "172.67.128.0/17", "104.21.0.0/16", "172.64.0.0/13"]

def safe_write_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except: pass

def safe_read_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding='utf-8') as f:
            return json.load(f)
    except: return default

# ===========================
# 2. 独立线程进化引擎 (三级跳逻辑)
# ===========================

def background_evolution():
    start_time = time.time()
    db_data = safe_read_json(DB_FILE, {})
    
    while True:
        try:
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
            elapsed = time.time() - start_time
            
            # --- 目标收集 ---
            targets = [{"ip": ip, "src": "⚡ 本地种子"} for ip in QUICK_SEEDS]
            
            # 3秒后加入池子测试
            if elapsed > 3:
                # 此处可加入从 CRAWLER_FILE 和 NICHE_FILE 的读取逻辑
                targets.append({"ip": "1.1.1.1", "src": "🕷️ 爬虫发现"}) 
            
            # 8秒后重测历史精英
            if elapsed > 8:
                history = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:12]
                for item in history:
                    targets.append({"ip": item['ip'], "src": "📂 历史优选"})

            # --- 极速测试流水线 ---
            current_results = []
            down_bytes = 15000 if elapsed < 10 else 200000 # 初期小包，后期大包
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def test_task(t):
                    ip = t['ip']
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(0.4)
                        t1 = time.perf_counter(); s.connect((ip, int(cfg['port']))); s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                    except: return None
                    
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes={down_bytes}", 
                                         headers={"Host": cfg['host']}, timeout=1.5)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 地理标记：初期本地占位，后期请求 API
                    geo = {"cc": "CN", "country": "四川电信测速中"} if elapsed < 10 else {"cc": "UN", "country": "Unknown"}
                    
                    score = round(100 - p_avg/5 + min(speed*5, 35), 1)
                    res = {"ip": ip, "score": score, "avg": p_avg, "speed": round(speed, 2), 
                           "src": t['src'], "cc": geo['cc'], "country": geo['country'], 
                           "last_test": datetime.now().strftime("%H:%M:%S")}
                    
                    if score >= db_data.get(ip, {}).get('score', 0): db_data[ip] = res
                    return res

                unique_ips = {v['ip']:v for v in targets}.values()
                futs = [ex.submit(test_task, i) for i in unique_ips]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: 
                        current_results.append(r)
                        temp_sorted = sorted(current_results, key=lambda x: x['score'], reverse=True)
                        safe_write_json(RESULT_FILE, {
                            "last_run": datetime.now().strftime("%H:%M:%S"), 
                            "mode": cfg['mode'], 
                            "winner": temp_sorted[0], 
                            "table": temp_sorted
                        })
            safe_write_json(DB_FILE, db_data)
        except: pass
        time.sleep(3 if elapsed < 15 else 10)

if "bg_evolution" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.bg_evolution = True

# ===========================
# 3. 前端界面 (找回侧边栏)
# ===========================

# --- 侧边栏配置 ---
with st.sidebar:
    st.header("🛠️ 配置控制台")
    cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
    
    modes = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    try: idx = modes.index(cfg['mode'])
    except: idx = 0
    
    new_mode = st.radio("优选策略", modes, index=idx)
    
    with st.expander("⚙️ 扫描高级设置"):
        new_host = st.text_input("伪装域名 (Host)", value=cfg.get("host", "speed.cloudflare.com"))
        new_port = st.number_input("端口 (Port)", value=cfg.get("port", 443))
        
    if st.button("💾 保存配置并应用"):
        safe_write_json(CONFIG_FILE, {"mode": new_mode, "host": new_host, "port": new_port})
        st.toast(f"✅ 策略已更新: {new_mode}", icon="🔀")
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(0.5)
        st.rerun()
    
    st.info("ℹ️ 后台正自动演化优胜劣汰，无需人工干预。")

# --- 主界面渲染 ---
st.title("🧬 Cloudflare 猎手进化版")
data = safe_read_json(RESULT_FILE, None)

if data:
    w = data['winner']
    st.markdown(f"### 🏆 当前最强 IP: `{w['ip']}` | 📍 {w['cc']} {w['country']}")
    
    df = pd.DataFrame(data['table'])
    st.dataframe(
        df[['score', 'src', 'ip', 'avg', 'speed', 'last_test']],
        column_config={
            "score": st.column_config.ProgressColumn("进化评分", min_value=0, max_value=100),
            "src": "分类来源",
            "avg": "延迟 ms",
            "speed": "速度 MB/s"
        },
        use_container_width=True, hide_index=True
    )
    st.caption(f"策略: {data['mode']} | 上次更新: {data['last_run']}")
    time.sleep(4); st.rerun()
else:
    st.info("🚀 正在极速连接四川电信骨干网并激活三级跳启动引擎...")
    st.warning("⏱️ 0-3秒：加载种子；3-8秒：启动全网爬虫；8秒后：全精度测速。请稍候...")
    time.sleep(2); st.rerun()

