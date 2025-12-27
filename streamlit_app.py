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
# 2. 爬虫池管理逻辑 (可视化核心)
# ===========================

class PoolManager:
    @staticmethod
    def fill_crawler():
        """从 GitHub 爬取大众 IP"""
        ips = safe_read_json(CRAWLER_FILE, [])
        if len(ips) >= 20: return
        try:
            r = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=3)
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
            random.shuffle(found)
            for ip in found:
                if len(ips) >= 20: break
                if ip not in ips: ips.append(ip)
            safe_write_json(CRAWLER_FILE, ips)
        except: pass

    @staticmethod
    def fill_niche():
        """算法生成冷门优质 IP"""
        ips = safe_read_json(NICHE_FILE, [])
        if len(ips) >= 20: return
        new_ips = []
        for _ in range(10):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                new_ips.append(str(net.network_address + random.randint(1, net.num_addresses - 2)))
            except: pass
        ips = list(set(ips + new_ips))[:20]
        safe_write_json(NICHE_FILE, ips)

# ===========================
# 3. 三级跳极速进化引擎
# ===========================

def background_evolution():
    start_time = time.time()
    db_data = safe_read_json(DB_FILE, {})
    
    while True:
        try:
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
            elapsed = time.time() - start_time
            
            # 目标收集
            targets = [{"ip": ip, "src": "⚡ 本地种子"} for ip in QUICK_SEEDS]
            
            # 立即触发爬虫和冷门挖掘 (三级跳动作)
            threading.Thread(target=PoolManager.fill_crawler).start()
            threading.Thread(target=PoolManager.fill_niche).start()
            
            c_ips = safe_read_json(CRAWLER_FILE, [])
            n_ips = safe_read_json(NICHE_FILE, [])
            
            # 启动数秒后立即将爬虫数据加入测试
            if elapsed > 3:
                targets += [{"ip": ip, "src": "🕷️ 爬虫发现"} for ip in c_ips[:8]]
                targets += [{"ip": ip, "src": "💎 冷门挖掘"} for ip in n_ips[:8]]
            
            if elapsed > 8:
                history = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:10]
                targets += [{"ip": i['ip'], "src": "📂 历史优选"} for i in history]

            # 极速流水线测试
            current_results = []
            down_bytes = 15000 if elapsed < 10 else 200000
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def test_task(t):
                    ip = t['ip']
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(0.4); t1 = time.perf_counter(); s.connect((ip, int(cfg['port']))); s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                    except: return None
                    
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes={down_bytes}", headers={"Host": cfg['host']}, timeout=1.5)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 地理信息可视化标记
                    geo = {"cc": "UN", "country": "Unknown"}
                    if elapsed > 10:
                        try:
                            g = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode,country", timeout=1).json()
                            geo = {"cc": g.get("countryCode","UN"), "country": g.get("country","Unknown")}
                        except: pass
                    else:
                        geo = {"cc": "CN", "country": "四川电信测速中"}

                    score = round(100 - p_avg/5 + min(speed*5, 35), 1)
                    res = {"ip": ip, "score": score, "avg": p_avg, "speed": round(speed, 2), 
                           "src": t['src'], "cc": geo['cc'], "country": geo['country'], 
                           "last_test": datetime.now().strftime("%H:%M:%S")}
                    
                    if score >= db_data.get(ip, {}).get('score', 0): db_data[ip] = res
                    return res

                unique_ips = {v['ip']:v for v in targets}.values()
                futs = [ex.submit(test_task, i) for i in unique_ips]
                
                # 实时写入可视化结果
                tested_c, tested_n = [], []
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: 
                        current_results.append(r)
                        if r['src'] == "🕷️ 爬虫发现": tested_c.append(r['ip'])
                        if r['src'] == "💎 冷门挖掘": tested_n.append(r['ip'])
                        temp_sorted = sorted(current_results, key=lambda x: x['score'], reverse=True)
                        safe_write_json(RESULT_FILE, {
                            "last_run": datetime.now().strftime("%H:%M:%S"), 
                            "winner": temp_sorted[0], 
                            "table": temp_sorted,
                            "c_size": len(c_ips), "n_size": len(n_ips)
                        })
            
            # 清理已测爬虫 IP
            safe_write_json(CRAWLER_FILE, [i for i in c_ips if i not in tested_c])
            safe_write_json(NICHE_FILE, [i for i in n_ips if i not in tested_n])
            safe_write_json(DB_FILE, db_data)
            
        except: pass
        time.sleep(10)

if "evolution_engine" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.evolution_engine = True

# ===========================
# 4. 前端展示 (找回侧边栏 + 可视化爬虫数据)
# ===========================

with st.sidebar:
    st.header("🛠️ 配置控制台")
    cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
    new_mode = st.radio("优选策略", ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"], 
                        index=["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"].index(cfg['mode']))
    
    with st.expander("⚙️ 扫描高级设置"):
        new_host = st.text_input("伪装域名", value=cfg.get("host", "speed.cloudflare.com"))
        new_port = st.number_input("端口", value=cfg.get("port", 443))
        
    if st.button("💾 保存配置并应用"):
        safe_write_json(CONFIG_FILE, {"mode": new_mode, "host": new_host, "port": new_port})
        st.toast(f"✅ 策略已更新: {new_mode}", icon="🔀")
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(0.5); st.rerun()

st.title("🧬 Cloudflare 猎手进化版")
data = safe_read_json(RESULT_FILE, None)

if data:
    w = data['winner']
    st.markdown(f"### 🏆 当前最强 IP: `{w['ip']}` | 📍 {w['cc']} {w['country']}")
    
    # 可视化爬虫池状态
    c1, c2 = st.columns(2)
    c1.metric("🕷️ 爬虫池待测数量", f"{data.get('c_size', 0)} / 20")
    c2.metric("💎 冷门池待测数量", f"{data.get('n_size', 0)} / 20")
    
    st.divider()
    
    # 结果表格，包含爬取数据的来源标记
    df = pd.DataFrame(data['table'])
    st.dataframe(
        df[['score', 'src', 'ip', 'avg', 'speed', 'last_test']],
        column_config={
            "score": st.column_config.ProgressColumn("进化评分", min_value=0, max_value=100),
            "src": "数据来源标记",
            "avg": "延迟 ms",
            "speed": "速度 MB/s"
        },
        use_container_width=True, hide_index=True
    )
    st.caption(f"上次演化更新: {data['last_run']} | 历史数据自动优胜劣汰替换中...")
    time.sleep(4); st.rerun()
else:
    st.info("🚀 正在激活三级跳引擎：0-3s 加载种子，3s+ 扫描爬虫数据...")
    time.sleep(2); st.rerun()
