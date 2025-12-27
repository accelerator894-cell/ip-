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
# 1. 基础配置与路径
# ===========================
st.set_page_config(page_title="Cloudflare 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
NICHE_FILE = "niche_pool.json"      
CONFIG_FILE = "app_config.json"     

QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]
GOLDEN_SUBNETS = ["104.28.0.0/16", "172.67.128.0/17", "104.21.0.0/16", "172.64.0.0/13"]

# 文件安全读写工具
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
# 2. 爬虫池补位管理
# ===========================

class PoolManager:
    @staticmethod
    def trigger_fill():
        """同时启动爬虫和冷门挖掘"""
        threading.Thread(target=PoolManager.fill_crawler, daemon=True).start()
        threading.Thread(target=PoolManager.fill_niche, daemon=True).start()

    @staticmethod
    def fill_crawler():
        ips = safe_read_json(CRAWLER_FILE, [])
        if len(ips) >= 25: return # 略微扩容以应对全量扫描
        try:
            r = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=3)
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
            random.shuffle(found)
            for ip in found:
                if len(ips) >= 25: break
                if ip not in ips: ips.append(ip)
            safe_write_json(CRAWLER_FILE, ips)
        except: pass

    @staticmethod
    def fill_niche():
        ips = safe_read_json(NICHE_FILE, [])
        if len(ips) >= 25: return
        new_ips = []
        for _ in range(15):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                new_ips.append(str(net.network_address + random.randint(1, net.num_addresses - 2)))
            except: pass
        ips = list(set(ips + new_ips))[:25]
        safe_write_json(NICHE_FILE, ips)

# ===========================
# 3. 独立进化引擎 (5分钟全量扫描核心)
# ===========================

def background_evolution():
    start_time = time.time()
    last_full_scan = 0 # 记录上一次5分钟全量扫描时间
    db_data = safe_read_json(DB_FILE, {})
    
    while True:
        try:
            now = time.time()
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
            
            # --- 阶段 A: 判断是否触发 5 分钟全量扫描 ---
            is_full_scan = (now - last_full_scan >= 300) 
            
            # --- 阶段 B: 目标收集 ---
            targets = []
            if is_full_scan:
                # 全量扫描：测试所有历史、爬虫和本地数据
                all_history = list(db_data.values())
                targets += [{"ip": i['ip'], "src": "📂 基因普查"} for i in all_history]
                targets += [{"ip": ip, "src": "🕷️ 爬虫全检"} for ip in safe_read_json(CRAWLER_FILE, [])]
                targets += [{"ip": ip, "src": "💎 冷门全检"} for ip in safe_read_json(NICHE_FILE, [])]
                last_full_scan = now
            else:
                # 常规扫描：极速轮询
                top_20 = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:20]
                targets += [{"ip": ip, "src": "⚡ 本地种子"} for ip in QUICK_SEEDS]
                targets += [{"ip": i['ip'], "src": "📂 历史优选"} for i in top_20]
                targets += [{"ip": ip, "src": "🕷️ 爬虫发现"} for ip in safe_read_json(CRAWLER_FILE, [])[:10]]

            # --- 阶段 C: 极速并发测试 (自动更换逻辑) ---
            current_results = []
            workers = 40 if is_full_scan else 20 # 全量扫描时加大并发
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                def test_task(t):
                    ip = t['ip']
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.4)
                        t1 = time.perf_counter(); s.connect((ip, int(cfg['port']))); s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                    except: return None
                    
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=150000", headers={"Host": cfg['host']}, timeout=1.5)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 自动评分与质量更换
                    score = round(100 - p_avg/5 + min(speed*5, 35), 1)
                    res = {"ip": ip, "score": score, "avg": p_avg, "speed": round(speed, 2), 
                           "src": t['src'], "last_test": datetime.now().strftime("%H:%M:%S")}
                    
                    # 【自动更换】若新评分更高，则立即覆盖精英库数据
                    if score >= db_data.get(ip, {}).get('score', 0): db_data[ip] = res
                    return res

                unique_targets = {v['ip']:v for v in targets}.values()
                futs = [ex.submit(test_task, i) for i in unique_targets]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: 
                        current_results.append(r)
                        temp_sorted = sorted(current_results, key=lambda x: x['score'], reverse=True)
                        safe_write_json(RESULT_FILE, {
                            "last_run": datetime.now().strftime("%H:%M:%S"), 
                            "winner": temp_sorted[0], "table": temp_sorted,
                            "is_full": is_full_scan
                        })

            # 周期性补充爬虫数据
            PoolManager.trigger_fill()
            safe_write_json(DB_FILE, db_data)
            
        except: pass
        time.sleep(10 if not is_full_scan else 30) # 全量扫描后多休息一会儿

# 启动后台引擎
if "evolution_engine" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.evolution_engine = True

# ===========================
# 4. 前端展示 (可视化全量扫描状态)
# ===========================

with st.sidebar:
    st.header("🛠️ 配置控制台")
    cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
    new_mode = st.radio("优选策略", ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"], 
                        index=0)
    
    if st.button("💾 保存配置并应用"):
        safe_write_json(CONFIG_FILE, {"mode": new_mode, "host": cfg['host'], "port": cfg['port']})
        st.toast(f"✅ 策略已更新: {new_mode}")
        time.sleep(0.5); st.rerun()

st.title("🧬 Cloudflare 猎手进化版")
data = safe_read_json(RESULT_FILE, None)

if data:
    w = data['winner']
    # 动态显示扫描模式
    scan_tag = "🚀 全量普查中" if data.get('is_full') else "📡 实时监测中"
    st.markdown(f"### 🏆 当前最强 IP: `{w['ip']}` | 状态: `{scan_tag}`")
    
    st.divider()
    df = pd.DataFrame(data['table'])
    st.dataframe(
        df[['score', 'src', 'ip', 'avg', 'speed', 'last_test']],
        column_config={
            "score": st.column_config.ProgressColumn("进化评分", min_value=0, max_value=100),
            "src": "分类标记",
        },
        use_container_width=True, hide_index=True
    )
    st.caption(f"上次演化更新: {data['last_run']} | 每 5 分钟执行一次全量数据普查与自动更换")
    time.sleep(5); st.rerun()
else:
    st.info("🚀 正在激活三级跳引擎... 首次加载约需 10 秒。")
    time.sleep(2); st.rerun()
