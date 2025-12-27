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

# ===========================
# 1. 页面配置 (电信深蓝主题 + 分区支持)
# ===========================
st.set_page_config(page_title="VLESS 终极融合版", page_icon="💎", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #001f3f; color: #E0E0E0; } /* 电信深蓝 */
    div[data-testid="column"] { background-color: #003366; border: 1px solid #0074D9; border-radius: 8px; padding: 15px; }
    
    /* 调整 Tab 样式，使其在深色背景下更明显 */
    button[data-baseweb="tab"] { font-size: 16px; font-weight: bold; color: #7FDBFF; }
    div[data-testid="stMetricValue"] { color: #2ECC40 !important; }
    h1, h2, h3 { color: #ffffff !important; }
    
    /* 进度条 */
    .stProgress > div > div > div > div { background-color: #39CCCC; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心配置
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

DB_FILE = "ultimate_history.log"

# ===========================
# 3. 基础工具 (地理位置 + IP池)
# ===========================

@st.cache_data(ttl=3600)
def get_ip_info(ip):
    """查询 IP 地理位置 (用于分区)"""
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG', 'MY', 'VN']: return "🌏 亚洲", r.get("country")
        if cc in ['US', 'CA', 'MX', 'BR']: return "🇺🇸 美洲", r.get("country")
        if cc in ['DE', 'GB', 'FR', 'NL', 'RU', 'EU']: return "🇪🇺 欧洲", r.get("country")
        return "🌍 其他", r.get("country")
    except:
        return "🛸 未知", "Unknown"

def resolve_commercial_domains():
    """解析商业域名获取高质量 IP"""
    domains = ["www.discord.com", "www.udemy.com", "www.digitalocean.com", "cdn.shopify.com"]
    ips = set()
    for d in domains:
        try:
            # 获取 443 端口的 A 记录
            infos = socket.getaddrinfo(d, 443, proto=socket.IPPROTO_TCP)
            for i in infos: ips.add(i[4][0])
        except: pass
    return list(ips)

def get_ultimate_pool():
    """构建终极 IP 池 (官方电信段 + 商业 + 爬虫)"""
    pool = set()
    
    # 1. 官方电信优选段 (104.16-20 / 172.64-67)
    official_ips = []
    for _ in range(15): official_ips.append(f"104.{random.randint(16, 20)}.{random.randint(0, 255)}.{random.randint(0, 255)}")
    for _ in range(15): official_ips.append(f"172.{random.randint(64, 67)}.{random.randint(0, 255)}.{random.randint(0, 255)}")
    for ip in official_ips: pool.add(ip)

    # 2. 商业解析
    comm_ips = resolve_commercial_domains()
    for ip in comm_ips: pool.add(ip)

    # 3. 爬虫采集
    urls = [
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
        "https://www.cloudflare.com/ips-v4"
    ]
    def fetch(url):
        try:
            return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(url, timeout=3).text)
        except: return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for res in ex.map(fetch, urls):
            for ip in res: pool.add(ip)
            
    # 随机采样，防止数量过多导致卡顿，保留 80 个
    final_list = list(pool)
    return random.sample(final_list, min(len(final_list), 80))

# ===========================
# 4. 电信评分算法 & 测试逻辑
# ===========================

def calculate_telecom_score(lat, jitter, loss, speed):
    """电信评分算法：严打丢包抖动"""
    score = 100
    score += min(speed * 3, 30)       # 速度加分
    if lat > 150: score -= (lat - 150) / 4 # 延迟扣分
    score -= jitter * 3               # 抖动重罚
    if loss > 0:                      # 丢包重罚
        score -= 50
        score -= loss * 2
    return round(score, 1)

def deep_test_node(node_data):
    ip = node_data['ip']
    source_type = "☁️ 采集"
    if ip.startswith("104.") or ip.startswith("172."): source_type = "⭐ 官方"
    if ip in node_data.get('commercial', []): source_type = "💎 商业"

    # 1. 稳定性测试 (HTTPS Ping 5次)
    delays = []
    loss_count = 0
    try:
        for _ in range(5):
            s = time.time()
            requests.head(f"https://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.5, verify=False)
            delays.append((time.time() - s) * 1000)
    except:
        loss_count += 1 # 捕获异常算一次丢包，但不中断循环太复杂，这里简化
        
    # 如果 delays 为空，说明全丢
    if not delays:
        return None 

    # 补充丢包计算 (如果5次里有失败的)
    real_loss_count = 5 - len(delays)
    loss_rate = (real_loss_count / 5) * 100
    
    avg_lat = statistics.mean(delays)
    jitter = statistics.stdev(delays) if len(delays) > 1 else 0
    
    # 2. 获取区域 (为了分区!)
    region, country = get_ip_info(ip)

    # 3. 速度测试 (下载)
    speed_mb = 0.0
    try:
        s_time = time.time()
        r = requests.get(f"https://{ip}/__down?bytes=1500000", headers={"Host": "speed.cloudflare.com"}, timeout=5, verify=False)
        if r.status_code == 200:
            speed_mb = (len(r.content)/1024/1024) / (time.time() - s_time)
    except: pass

    # 4. 评分
    score = calculate_telecom_score(avg_lat, jitter, loss_rate, speed_mb)

    return {
        "ip": ip, "region": region, "country": country, "source": source_type,
        "lat": int(avg_lat), "jitter": int(jitter), "loss": int(loss_rate),
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

st.title("💎 VLESS 终极融合版")

col1, col2 = st.columns([3, 1])
with col1:
    st.info("💡 融合内核：电信QoS评分算法 + 全球分区 + 多源爬虫 + 深度体检")
with col2:
    start = st.button("🚀 开始全面扫描", type="primary", use_container_width=True)

if start:
    with st.spinner("📦 正在聚合资源：官方段 + 商业域名 + GitHub 源..."):
        scan_list = get_ultimate_pool()
        # 标记商业IP用于识别
        comm_list = resolve_commercial_domains()
        tasks = [{"ip": ip, "commercial": comm_list} for ip in scan_list]
        
    st.write(f"⚡ 正在对 {len(tasks)} 个节点进行深度分层测试...")
    progress = st.progress(0)
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        futs = [ex.submit(deep_test_node, t) for t in tasks]
        for i, fut in enumerate(concurrent.futures.as_completed(futs)):
            progress.progress((i + 1) / len(tasks))
            res = fut.result()
            # 过滤掉极差的节点 (延迟>1000 或 负分太严重)
            if res and res['lat'] < 1000 and res['score'] > -200:
                results.append(res)
                
    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        msg = sync_dns(winner['ip'])
        
        # --- 冠军展示 ---
        st.success(f"🏆 综合最优: {winner['ip']} ({winner['region']} - {winner['country']})")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("综合评分", winner['score'], winner['source'])
        c2.metric("下载速度", f"{winner['speed']} MB/s")
        c3.metric("延迟/抖动", f"{winner['lat']} ms", f"±{winner['jitter']}")
        c4.write(f"📝 {msg}")
        
        st.divider()
        
        # --- 分区展示 (Tab 回归!) ---
        df = pd.DataFrame(results)
        # 整理列名
        display_cols = {
            "score": "评分", "ip": "IP 地址", "source": "来源", "speed": "速度(MB/s)",
            "lat": "延迟", "jitter": "抖动", "loss": "丢包(%)", "country": "国家"
        }
        
        # 定义展示函数
        def show_tab_table(data):
            if data.empty:
                st.warning("⚠️ 该区域暂无符合条件的优质节点")
            else:
                st.dataframe(
                    data.rename(columns=display_cols)[display_cols.values()],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "评分": st.column_config.ProgressColumn(format="%.1f", min_value=-100, max_value=150),
                    }
                )

        t_all, t_asia, t_amer, t_euro = st.tabs(["🌐 全部榜单", "🌏 亚洲专区", "🇺🇸 美洲专区", "🇪🇺 欧洲专区"])
        
        with t_all: show_tab_table(df)
        with t_asia: show_tab_table(df[df['region'] == "🌏 亚洲"])
        with t_amer: show_tab_table(df[df['region'] == "🇺🇸 美洲"])
        with t_euro: show_tab_table(df[df['region'] == "🇪🇺 欧洲"])
        
        # 记录日志
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%m-%d %H:%M')} | {winner['ip']} | {winner['score']} | {winner['region']}\n")
            
    else:
        st.error("❌ 未找到可用节点，请检查网络连通性。")

# 历史
with st.expander("📜 扫描历史"):
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-5:]))
