import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd
import concurrent.futures
import statistics
import socket
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 页面配置
# ===========================
st.set_page_config(page_title="VLESS 竞速排位版", page_icon="🏎️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #001f3f; color: #E0E0E0; }
    div[data-testid="column"] { background-color: #003366; border: 1px solid #0074D9; border-radius: 8px; padding: 15px; }
    button[data-baseweb="tab"] { font-size: 16px; font-weight: bold; color: #7FDBFF; }
    div[data-testid="stMetricValue"] { color: #2ECC40 !important; }
    
    /* 来源标签颜色 */
    .source-local { color: #FF851B; font-weight: bold; }
    .source-saved { color: #2ECC40; font-weight: bold; }
    .source-cloud { color: #7FDBFF; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 配置与文件
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失！请检查 secrets.toml")
    st.stop()

DB_FILE = "racing_history.log"
SAVED_IP_FILE = "good_ips.txt" # 💾 精英节点库

# ===========================
# 3. 核心工具函数
# ===========================

@st.cache_data(ttl=3600)
def get_ip_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG']: return "🌏 亚洲", r.get("country")
        if cc in ['US', 'CA', 'MX']: return "🇺🇸 美洲", r.get("country")
        if cc in ['DE', 'GB', 'FR', 'NL', 'RU']: return "🇪🇺 欧洲", r.get("country")
        return "🌍 其他", r.get("country")
    except: return "🛸 未知", "Unknown"

def tcp_ping(ip, port=443):
    """Ping0: 纯 TCP 握手延迟测试 (不带SSL)"""
    try:
        start = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0) # 1秒超时，快速筛选
        s.connect((ip, port))
        s.close()
        return int((time.time() - start) * 1000)
    except:
        return 9999

def load_saved_ips():
    """读取已保存的精英 IP"""
    if not os.path.exists(SAVED_IP_FILE): return []
    with open(SAVED_IP_FILE, "r") as f:
        content = f.read()
        return list(set(re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', content)))

def save_good_ip(ip):
    """保存表现好的 IP 到本地文件"""
    existing = load_saved_ips()
    if ip not in existing:
        with open(SAVED_IP_FILE, "a") as f:
            f.write(f"{ip}\n")
            
def get_competitor_pool():
    """构建竞技场选手池 (不分贵贱，只标记来源)"""
    competitors = []
    seen_ips = set()
    
    # 1. 本地种子选手 (Local)
    locals = ["108.162.194.1", "172.64.32.12", "162.159.61.1"]
    for ip in locals:
        competitors.append({"ip": ip, "source": "🏠 本地"})
        seen_ips.add(ip)
        
    # 2. 历史精英选手 (Saved)
    saved = load_saved_ips()
    for ip in saved:
        if ip not in seen_ips:
            competitors.append({"ip": ip, "source": "💾 历史"})
            seen_ips.add(ip)
            
    # 3. 网络海选选手 (Scraped)
    # 我们希望海选选手多一点，给它们逆袭的机会
    target_total = 80 # 总参赛人数
    needed = target_total - len(competitors)
    
    if needed > 0:
        urls = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", 
            "https://www.cloudflare.com/ips-v4"
        ]
        scraped_pool = set()
        
        def fetch(url):
            try: return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(url, timeout=3).text)
            except: return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            for res in ex.map(fetch, urls):
                for ip in res: scraped_pool.add(ip)
        
        scraped_list = list(scraped_pool)
        # 随机抽取填满名额
        if scraped_list:
            picked = random.sample(scraped_list, min(len(scraped_list), needed))
            for ip in picked:
                if ip not in seen_ips:
                    competitors.append({"ip": ip, "source": "☁️ 爬虫"})
    
    return competitors

# ===========================
# 4. 深度评测 (绝对公平版)
# ===========================

def calculate_fair_score(tcp_lat, http_lat, jitter, loss, speed):
    """
    公平评分公式：无任何来源加成！
    完全由网络指标决定分数。
    """
    score = 100
    
    # 1. 速度权重 (最高 +60分) - 鼓励大带宽
    score += min(speed * 3, 60)
    
    # 2. 延迟权重 (TCP与HTTP加权平均)
    # 延迟越低越好，超过 150ms 开始扣分
    lat_metric = (tcp_lat * 0.4) + (http_lat * 0.6)
    if lat_metric > 150:
        score -= (lat_metric - 150) / 3
        
    # 3. 稳定性权重 (抖动)
    score -= jitter * 1.5
    
    # 4. 丢包权重 (重罚)
    if loss > 0:
        score -= loss * 2.5
        score -= 20 # 只要丢包直接扣20基础分
        
    return round(score, 1)

def deep_test_node(node):
    ip = node['ip']
    
    # 1. Ping0 (TCP)
    tcp_lat = tcp_ping(ip)
    if tcp_lat > 2000: return None # 连通性太差直接淘汰

    # 2. HTTP/HTTPS Latency
    delays = []
    success_count = 0
    
    # 测 3 次
    for _ in range(3):
        try:
            s = time.time()
            requests.head(f"https://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5, verify=False)
            delays.append((time.time() - s) * 1000)
            success_count += 1
        except: pass

    # 补救措施：如果HTTPS全挂，试一次HTTP
    if not delays:
        try:
            s = time.time()
            requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5)
            delays.append((time.time() - s) * 1000)
            http_lat = delays[0]
        except: return None # 彻底没救
    else:
        http_lat = statistics.mean(delays)

    loss_rate = ((3 - success_count) / 3) * 100
    jitter = statistics.stdev(delays) if len(delays) > 1 else 0
    region, country = get_ip_info(ip)

    # 3. 速度测试 (1MB)
    speed_mb = 0.0
    try:
        s_time = time.time()
        r = requests.get(f"http://{ip}/__down?bytes=1000000", headers={"Host": "speed.cloudflare.com"}, timeout=4)
        if r.status_code == 200:
            speed_mb = (len(r.content)/1024/1024) / (time.time() - s_time)
    except: pass

    # 4. 评分 (无偏见)
    score = calculate_fair_score(tcp_lat, http_lat, jitter, loss_rate, speed_mb)
    
    # === 关键逻辑：优胜劣汰保存 ===
    # 只有来源是爬虫，且分数极高 (>80)，才保存
    # 这样能保证本地库里都是精品
    is_new_discovery = False
    if score > 80 and node['source'] == "☁️ 爬虫":
        save_good_ip(ip)
        is_new_discovery = True

    return {
        "ip": ip, "region": region, "country": country, 
        "source": node['source'], "is_new": is_new_discovery,
        "tcp": int(tcp_lat), "http": int(http_lat), 
        "jitter": int(jitter), "loss": int(loss_rate), 
        "speed": round(speed_mb, 2), "score": score
    }

def sync_dns(ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        recs = requests.get(url, headers=headers, params=params, timeout=5).json()
        if not recs.get("result"): return "❌ 无记录"
        rid = recs["result"][0]["id"]
        if recs["result"][0]["content"] == ip: return "✅ IP未变"
        requests.put(f"{url}/{rid}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": ip, "ttl": 60, "proxied": False
        })
        return f"🚀 已同步: {ip}"
    except: return "⚠️ API异常"

# ===========================
# 5. 主界面
# ===========================

st.title("🏎️ VLESS 竞速排位版")

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    st.info("💡 机制：完全按质量评分 (无来源加成) + 自动保存优选爬虫节点 + Ping0显示")
with c2:
    if st.button("🗑️ 清空精英库"):
        if os.path.exists(SAVED_IP_FILE): os.remove(SAVED_IP_FILE)
        st.toast("已清空保存列表")
with c3:
    start = st.button("🚀 开始排位赛", type="primary", use_container_width=True)

if start:
    with st.spinner("🏟️ 选手入场：集结本地、历史、爬虫节点..."):
        tasks = get_competitor_pool()
        
    st.write(f"⚡ 正在对 {len(tasks)} 个节点进行公平竞技...")
    progress = st.progress(0)
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        futs = [ex.submit(deep_test_node, t) for t in tasks]
        for i, fut in enumerate(concurrent.futures.as_completed(futs)):
            progress.progress((i + 1) / len(tasks))
            res = fut.result()
            if res: results.append(res)
            
    if results:
        # === 核心逻辑：完全按分数倒序 ===
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        
        # 如果冠军是爬虫，说明爬虫逆袭了！
        win_source = winner['source']
        if winner.get('is_new'):
            win_source += " (✨新晋精英)"
        
        sync_msg = sync_dns(winner['ip'])
        
        # 冠军展示
        st.success(f"🏆 冠军节点: {winner['ip']} | 来源: {win_source}")
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("综合得分", winner['score'], "质量优先")
        k2.metric("Ping0 (TCP)", f"{winner['tcp']} ms", "物理延迟")
        k3.metric("下载速度", f"{winner['speed']} MB/s")
        k4.metric("丢包率", f"{winner['loss']}%", f"抖动 {winner['jitter']}")
        
        st.caption(f"📝 {sync_msg}")
        st.divider()

        # 表格展示
        df = pd.DataFrame(results)
        
        # 标记新保存的节点
        df['source'] = df.apply(lambda x: x['source'] + " ✨" if x.get('is_new') else x['source'], axis=1)

        display_cols = {
            "score": "评分", "ip": "IP", "source": "来源", "tcp": "Ping0(ms)", 
            "http": "HTTP(ms)", "speed": "速度(MB/s)", "loss": "丢包(%)", "country": "国家"
        }
        
        for k in display_cols.keys(): 
            if k not in df.columns: df[k] = 0

        def show_table(data):
            if data.empty: st.warning("无数据")
            else:
                st.dataframe(
                    data.rename(columns=display_cols)[display_cols.values()],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "评分": st.column_config.ProgressColumn(format="%.1f", min_value=-50, max_value=120),
                        "Ping0(ms)": st.column_config.NumberColumn(format="%d ms"),
                    }
                )

        t1, t2, t3, t4 = st.tabs(["🌐 总榜单", "🌏 亚洲赛区", "🇺🇸 美洲赛区", "🇪🇺 欧洲赛区"])
        with t1: 
            st.caption(f"本次排位赛共 {len(results)} 位选手完赛。新发现的优质爬虫节点已自动保存。")
            show_table(df)
        with t2: show_table(df[df['region'] == "🌏 亚洲"])
        with t3: show_table(df[df['region'] == "🇺🇸 美洲"])
        with t4: show_table(df[df['region'] == "🇪🇺 欧洲"])
        
        # 记录日志
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | TCP:{winner['tcp']} | {winner['source']}\n")

    else:
        st.error("❌ 全员淘汰，无可用节点。")

with st.expander("📜 历史战绩"):
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-5:]))
