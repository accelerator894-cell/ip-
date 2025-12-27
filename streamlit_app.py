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
import ssl
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 核心配置
# ===========================
st.set_page_config(page_title="VLESS 极速版 (本地优先)", page_icon="🐼", layout="wide")

VALID_MODES = [
    "☀️ 正常使用排位", 
    "🌙 晚高峰避峰排位", 
    "🤖 GPT 独享专线",
    "🎬 流媒体解锁专线"
]

RESULT_FILE = "scan_results.json"
CONFIG_FILE = "app_config.json"
SAVED_IP_FILE = "good_ips.txt"

# 内置保底种子 (万一你本地文件空了，还有这些能救急)
QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"
]

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #15171e; border: 1px solid #262730; border-radius: 8px; padding: 15px; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 工具函数
# ===========================

def get_config():
    default_conf = {"mode": VALID_MODES[0]}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                if saved.get("mode") not in VALID_MODES: return default_conf
                return saved
        except: return default_conf
    return default_conf

def save_config(mode):
    with open(CONFIG_FILE, "w") as f: json.dump({"mode": mode}, f)

def get_geo_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,isp,hosting"
        r = requests.get(url, timeout=1.5).json()
        cc = r.get("countryCode", "US")
        is_native = not r.get("hosting", True) # hosting=False 为原生
        
        region_map = {'CN': '🇨🇳', 'HK': '🇭🇰', 'US': '🇺🇸', 'JP': '🇯🇵', 'SG': '🇸🇬', 'TW': '🇹🇼'}
        flag = region_map.get(cc, cc)
        
        blocked = ['CN', 'HK', 'RU', 'IR', 'KP']
        gpt = "✅" if cc not in blocked else "❌"
        
        return {"cc": cc, "flag": flag, "gpt": gpt, "is_native": is_native}
    except: return {"cc": "Unk", "flag": "❓", "gpt": "❓", "is_native": False}

def check_tls_handshake(ip):
    try:
        context = ssl.create_default_context()
        context.check_hostname = False; context.verify_mode = ssl.CERT_NONE
        conn = context.wrap_socket(socket.socket(socket.AF_INET), server_hostname="speed.cloudflare.com")
        conn.settimeout(1.0)
        t1 = time.perf_counter(); conn.connect((ip, 443)); dur = (time.perf_counter() - t1) * 1000
        conn.close()
        return {"status": True, "latency": int(dur)}
    except: return {"status": False, "latency": 9999}

def calculate_score(mode, p0, speed, geo, tls_ok):
    if not tls_ok: return 0 
    score = 100.0
    
    score -= (p0['loss'] * 6) # 电信怕丢包
    limit = 280 if mode in ["🤖 GPT 独享专线", "🎬 流媒体解锁专线"] else 180
    if p0['avg'] > limit: score -= (p0['avg'] - limit) / 5
    score -= p0['jitter'] * 1.5
    score += min(speed * 4, 30)
    
    if mode == "🤖 GPT 独享专线":
        if geo['gpt'] == "❌": return 0
        if geo['cc'] in ['US', 'JP', 'SG']: score += 15
    elif mode == "🎬 流媒体解锁专线":
        if geo['is_native']: score += 40 # 原生大幅加分
        else: score -= 20
        
    return max(0, round(score, 1))

def ping0_tcp_test(ip, count=4):
    lats, success = [], 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            t1 = time.perf_counter(); s.connect((ip, 443)); s.close()
            lats.append((time.perf_counter() - t1) * 1000); success += 1
        except: pass
    if not lats: return {"avg": 9999, "jitter": 999, "loss": 100}
    return {"avg": int(statistics.mean(lats)), "jitter": int(statistics.stdev(lats)) if len(lats) > 1 else 0, "loss": int(((count-success)/count)*100)}

def get_china_latency(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4); t1 = time.perf_counter(); s.connect((ip, 443))
        dur = (time.perf_counter() - t1) * 1000; s.close()
        return int(dur)
    except: return 999

# ===========================
# 3. 智能爬虫 (修正：首次运行也加载本地)
# ===========================
def smart_crawler(mode, first_run=False):
    pool = []
    seen = set()
    
    # 1. 无论是否第一次，都优先加载本地文件 (用户积累的IP)
    if os.path.exists(SAVED_IP_FILE):
        with open(SAVED_IP_FILE, "r") as f:
            local_ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read())
            # 加载最近 20 个本地 IP
            for ip in local_ips[-20:]:
                if ip not in seen:
                    pool.append({"ip": ip, "source": "📂 本地固态"})
                    seen.add(ip)

    # 2. 如果是第一次运行，补充内置种子，直接返回 (秒开逻辑)
    if first_run:
        for ip in QUICK_SEEDS:
            if ip not in seen:
                pool.append({"ip": ip, "source": "🚀 极速种子"})
        return pool

    # 3. 如果不是第一次，才去爬全网 (耗时逻辑)
    try:
        urls = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
        for u in urls:
            try: txt = requests.get(u, timeout=2).text
            except: continue
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
            
            if mode == "🤖 GPT 独享专线":
                found = [ip for ip in found if ip.startswith("104.19") or ip.startswith("172.64")] + found
            
            limit = 40 if mode == "🎬 流媒体解锁专线" else 30
            for ip in random.sample(found, min(len(found), limit)):
                if ip not in seen:
                    pool.append({"ip": ip, "source": "🕷️ 全网爬虫"}); seen.add(ip)
    except: pass
    
    return pool

def background_worker():
    is_first_run = True
    while True:
        try:
            cfg = get_config(); mode = cfg["mode"]
            
            # 这里现在会同时包含：本地IP + 内置种子
            pool = smart_crawler(mode, first_run=is_first_run)
            is_first_run = False 
            
            results = []
            # 首次运行开大线程，保证把本地库存也秒测完
            workers = 40 
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                def process_node(node):
                    ip = node['ip']
                    cn_lat = get_china_latency(ip)
                    if cn_lat > 600: return None
                    
                    tls = check_tls_handshake(ip)
                    if not tls['status']: return None 
                    
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=100000", headers={"Host": "speed.cloudflare.com"}, timeout=1.5)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    geo = get_geo_info(ip)
                    p0 = ping0_tcp_test(ip)
                    score = calculate_score(mode, p0, speed, geo, True)
                    if score <= 0: return None
                    
                    return {
                        "ip": ip, "score": score, "cn_lat": cn_lat, "speed": round(speed, 2),
                        "loss": p0['loss'], "source": node['source'], 
                        "flag": geo['flag'], "gpt": geo['gpt'], "is_native": geo['is_native']
                    }

                futs = [ex.submit(process_node, n) for n in pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: results.append(res)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                
                # 更新本地文件 (只存前5，防止膨胀)
                with open(SAVED_IP_FILE, "a") as f:
                    for r in results[:5]: f.write(f"{r['ip']}\n")
                
                state = {
                    "last_run": datetime.now().strftime("%H:%M:%S"), 
                    "mode": mode, "winner": winner, "table": results[:25],
                    "init_done": True
                }
                with open(RESULT_FILE, "w") as f: json.dump(state, f)
                
        except Exception as e: print(f"Worker Error: {e}")
        time.sleep(5 if len(pool) < 20 else 300)

if "bg_thread" not in st.session_state:
    import threading
    threading.Thread(target=background_worker, daemon=True).start()
    st.session_state.bg_thread = True

# ===========================
# 4. 前端展示
# ===========================
with st.sidebar:
    st.header("🐼 四川电信控制台")
    curr = get_config()
    current_mode = curr.get("mode")
    try: idx = VALID_MODES.index(current_mode)
    except: idx = 0
    new_mode = st.radio("排位模式", VALID_MODES, index=idx)
    if new_mode != current_mode:
        save_config(new_mode)
        st.toast(f"切换模式: {new_mode}", icon="🚀")
        time.sleep(0.5); st.rerun()

st.title("🐼 VLESS 电信流媒体版")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f: data = json.load(f)
    winner = data['winner']
    df = pd.DataFrame(data['table'])
    
    st.caption(f"策略: {data['mode']} | 更新: {data['last_run']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👑 冠军 IP", winner['ip'])
    
    # 原生状态显示
    native_text = "原生解锁" if winner.get('is_native') else "非原生"
    c2.metric("🎬 流媒体/GPT", f"{native_text} | {winner['gpt']}")
    c3.metric("📉 延迟/丢包", f"{winner['cn_lat']}ms / {winner['loss']}%")
    c4.metric("📊 得分", f"{winner['score']}")
    
    st.divider()
    st.subheader("📋 详细报告")
    st.dataframe(
        df,
        column_order=("score", "ip", "flag", "is_native", "gpt", "cn_lat", "speed", "source"),
        column_config={
            "score": st.column_config.ProgressColumn("得分", format="%.0f", min_value=0, max_value=100),
            "flag": "地区",
            "is_native": st.column_config.CheckboxColumn("原生?", help="原生IP通常可解锁Netflix"),
            "cn_lat": st.column_config.NumberColumn("延迟", format="%d ms"),
            "speed": st.column_config.NumberColumn("速度", format="%.1f MB/s"),
        },
        use_container_width=True,
        hide_index=True
    )
else:
    # 提示文案修改
    st.info("🚀 极速启动: 正在加载内置种子 + 本地固态 IP (预计 2-3 秒)...")
    time.sleep(2)
    st.rerun()

time.sleep(10)
st.rerun()
