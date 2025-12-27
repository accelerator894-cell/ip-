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

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 页面配置
# ===========================
st.set_page_config(page_title="VLESS 全球指挥官 (Ping0版)", page_icon="🗺️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #15171e; border: 1px solid #262730; border-radius: 8px; padding: 15px; }
    /* 地区标签颜色 */
    .region-asia { color: #00CC96; font-weight: bold; }
    .region-us { color: #636EFA; font-weight: bold; }
    .region-eu { color: #AB63FA; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

RESULT_FILE = "scan_results.json"
CONFIG_FILE = "app_config.json"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 2. 核心算法工具箱
# ===========================

def get_config():
    default = {"mode": "☀️ 正常使用排位"}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f: return json.load(f)
        except: return default
    return default

def save_config(mode):
    with open(CONFIG_FILE, "w") as f: json.dump({"mode": mode}, f)

def get_time_slot():
    h = datetime.now().hour
    if 19 <= h <= 23: return "PEAK"
    if 1 <= h <= 6:   return "IDLE"
    return "NORMAL"

# --- 新增：地缘分类算法 ---
def get_region_info(ip):
    """
    根据 IP 获取国家代码，并归类为 美/亚/欧
    """
    try:
        # 使用 ip-api.com (注意频率限制，实际生产可换离线库)
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,isp,hosting"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "US")
        
        # 归类逻辑
        asia = ['CN','HK','JP','SG','KR','TW','MY','TH','VN','ID','IN','PH']
        americas = ['US','CA','MX','BR','AR','CL']
        europe = ['GB','DE','FR','NL','IT','ES','RU','UA','PL','SE']
        
        region = "🌍 其他"
        if cc in asia: region = "🌏 亚太"
        elif cc in americas: region = "🗽 美洲"
        elif cc in europe: region = "🏰 欧洲"
        
        return {
            "region": region,
            "cc": cc,
            "is_native": not r.get("hosting", True)
        }
    except:
        return {"region": "🗽 美洲", "cc": "US", "is_native": False} # 默认兜底

# --- 新增：Ping0 评分算法 ---
def calculate_ping0_score(avg, jitter, loss, speed):
    """
    【Ping0.cc 核心算法复刻】
    满分 100。
    1. 丢包 (Loss): 毁灭性打击。丢包 > 0 即大幅扣分。
    2. 抖动 (Jitter): 稳定性指标。抖动大说明线路拥塞。
    3. 延迟 (Latency): 基础分，只要不超时都还好。
    """
    score = 100.0
    
    # 1. 丢包扣分 (最严厉)
    # Ping0 逻辑：有丢包基本就不能用。每 1% 丢包扣 5 分。
    score -= (loss * 5)
    
    # 2. 抖动扣分
    # 抖动超过 5ms 开始明显扣分，每 1ms 抖动扣 0.5 分
    if jitter > 5:
        score -= (jitter - 5) * 0.5
    
    # 3. 延迟扣分 (非线性)
    # 200ms 以内不扣分，超过 200ms 每增加 10ms 扣 1 分
    if avg > 200:
        score -= (avg - 200) / 10
        
    # 4. 速度加成 (额外奖励)
    # 速度仅作为锦上添花，不直接决定 Ping0 分数，但为了综合排名，我们按权重加回
    # 限制加分上限，防止速度掩盖丢包问题
    speed_bonus = min(speed * 2, 20) # 最多加20分
    
    score += speed_bonus
    
    return max(0, round(score, 1))

def ping0_tcp_test(ip, count=6):
    """TCP 握手测试 (次数增加到6次以获取更准的丢包率)"""
    lats = []
    success = 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.6)
            t1 = time.perf_counter()
            s.connect((ip, 443))
            s.close()
            lats.append((time.perf_counter() - t1) * 1000)
            success += 1
        except: pass
        time.sleep(0.05)
    
    if not lats: return {"avg": 9999, "jitter": 999, "loss": 100}
    
    avg = statistics.mean(lats)
    jitter = statistics.stdev(lats) if len(lats) > 1 else 0
    loss = ((count - success) / count) * 100
    
    return {"avg": int(avg), "jitter": int(jitter), "loss": int(loss)}

def get_china_latency(ip):
    """模拟国测"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        t1 = time.perf_counter()
        s.connect((ip, 443))
        dur = (time.perf_counter() - t1) * 1000
        s.close()
        return int(dur)
    except: return 999

def sync_dns(ip):
    try:
        if "api_token" not in st.secrets: return "⚠️ 无 Secrets"
        cfg = st.secrets
        url = f"https://api.cloudflare.com/client/v4/zones/{cfg['zone_id']}/dns_records"
        headers = {"Authorization": f"Bearer {cfg['api_token']}", "Content-Type": "application/json"}
        recs = requests.get(url, headers=headers, params={"name": cfg['record_name']}, timeout=5).json()
        if recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == ip: return f"✅ 稳定 ({ip})"
            requests.put(f"{url}/{rid}", headers=headers, json={"type":"A","name":cfg['record_name'],"content":ip,"ttl":60,"proxied":False})
            return f"🚀 切换: {ip}"
    except: return "❌ API 异常"
    return "⚠️ 记录丢失"

# ===========================
# 3. 智能爬虫与后台调度
# ===========================

def smart_crawler(mode, time_slot):
    """智能爬虫 (保留遗传算法)"""
    pool = []
    seen = set()
    
    # 1. 历史优选回捞
    history_ips = []
    if os.path.exists(SAVED_IP_FILE):
        with open(SAVED_IP_FILE, "r") as f:
            history_ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read())
            for ip in history_ips[-15:]:
                if ip not in seen:
                    pool.append({"ip": ip, "type": "🏆 传家宝"})
                    seen.add(ip)

    # 2. 基因衍生 (遗传算法)
    if history_ips:
        parents = history_ips[-5:]
        for ip in parents:
            subnet = ".".join(ip.split(".")[:3])
            for _ in range(3): # 每个优选 IP 衍生 3 个邻居
                child = f"{subnet}.{random.randint(1, 254)}"
                if child not in seen:
                    pool.append({"ip": child, "type": "🧬 衍生"})
                    seen.add(child)

    # 3. 外部源补充
    if time_slot != "PEAK":
        try:
            u = "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"
            txt = requests.get(u, timeout=3).text
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
            for ip in random.sample(found, min(len(found), 25)):
                if ip not in seen:
                    pool.append({"ip": ip, "type": "🔥 热搜"})
                    seen.add(ip)
        except: pass

    # 4. 避峰冷门段
    if time_slot == "PEAK" or mode == "🌙 晚高峰避峰排位":
        cold_prefixes = ["162.159.36", "162.159.46", "198.41.214"]
        for _ in range(25):
            ip = f"{random.choice(cold_prefixes)}.{random.randint(1, 254)}"
            if ip not in seen:
                pool.append({"ip": ip, "type": "🌙 冷门"})
                seen.add(ip)
                
    return pool

def background_worker():
    while True:
        try:
            cfg = get_config()
            mode = cfg["mode"]
            time_slot = get_time_slot()
            pool = smart_crawler(mode, time_slot)
            
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def process_node(node):
                    ip = node['ip']
                    
                    # 1. 国测筛选
                    cn_lat = get_china_latency(ip)
                    if cn_lat > 800: return None
                    
                    # 2. Ping0 深度测试
                    p0 = ping0_tcp_test(ip)
                    if p0['loss'] > 30: return None # 丢包严重直接丢弃
                    
                    # 3. 获取地理位置 (新增)
                    geo = get_region_info(ip)
                    
                    # 4. 测速
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=500000", headers={"Host": "speed.cloudflare.com"}, timeout=3)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 5. Ping0 评分计算
                    score = calculate_ping0_score(p0['avg'], p0['jitter'], p0['loss'], speed)
                    
                    # 模式加成修正
                    final_score = score
                    if mode == "🌙 晚高峰避峰排位":
                        final_score -= p0['loss'] * 2 # 避峰更怕丢包
                    elif mode == "🧬 原生IP分数排位":
                        if geo['is_native']: final_score += 20
                        else: final_score -= 50
                    
                    return {
                        "ip": ip, "score": final_score, "cn_lat": cn_lat, "speed": round(speed, 2),
                        "loss": p0['loss'], "jitter": p0['jitter'], "avg": p0['avg'],
                        "type": node['type'], "region": geo['region'], "cc": geo['cc']
                    }

                futs = [ex.submit(process_node, n) for n in pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res and res['score'] > 40: # 只保留及格的
                        results.append(res)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                
                # 存入历史库
                with open(SAVED_IP_FILE, "a") as f:
                    for r in results[:3]: f.write(f"{r['ip']}\n")
                
                sync_msg = sync_dns(winner['ip'])
                
                state = {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "time_slot": time_slot,
                    "mode": mode,
                    "winner": winner,
                    "sync_msg": sync_msg,
                    "table": results[:25]
                }
                with open(RESULT_FILE, "w") as f: json.dump(state, f)
                
        except Exception as e: print(f"Worker Error: {e}")
        time.sleep(600) # 10分钟

if "bg_thread" not in st.session_state:
    import threading
    threading.Thread(target=background_worker, daemon=True).start()
    st.session_state.bg_thread = True

# ===========================
# 4. 前端可视化
# ===========================
with st.sidebar:
    st.header("🎮 控制台")
    curr = get_config()
    new_mode = st.radio("模式", ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🧬 原生IP分数排位"], index=0)
    if new_mode != curr.get("mode"):
        save_config(new_mode)
        st.toast(f"已切换: {new_mode}", icon="🔄")

st.title("🗺️ VLESS 全球指挥官 (Ping0版)")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f: data = json.load(f)
    winner = data['winner']
    df = pd.DataFrame(data['table'])
    
    # 顶部状态
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👑 冠军 IP", winner['ip'])
    c2.metric("🌏 归属地", f"{winner['region']} ({winner['cc']})")
    c3.metric("📈 Ping0 得分", f"{winner['score']}", delta="及格线: 60")
    c4.metric("💔 丢包率", f"{winner['loss']}%", delta_color="inverse")
    
    st.divider()
    
    # 分区域展示
    tabs = st.tabs(["🌏 亚太 (Asia)", "🗽 美洲 (Americas)", "🏰 欧洲 (Europe)", "📊 全球总览"])
    
    def show_region_table(region_name):
        # 筛选逻辑
        if region_name == "Global":
            sub_df = df
        else:
            sub_df = df[df['region'].str.contains(region_name)]
            
        if sub_df.empty:
            st.info(f"暂无 {region_name} 区域的优质节点")
        else:
            st.dataframe(
                sub_df,
                column_order=("score", "ip", "region", "cn_lat", "loss", "jitter", "speed", "type"),
                column_config={
                    "score": st.column_config.ProgressColumn("Ping0 评分", format="%.0f", min_value=0, max_value=100),
                    "region": st.column_config.TextColumn("区域"),
                    "loss": st.column_config.NumberColumn("丢包%", format="%d%%"),
                    "jitter": st.column_config.NumberColumn("抖动", format="%d ms"),
                    "cn_lat": st.column_config.NumberColumn("CN延迟", format="%d ms"),
                    "speed": st.column_config.NumberColumn("速度", format="%.2f MB/s"),
                },
                use_container_width=True,
                hide_index=True
            )

    with tabs[0]: show_region_table("亚太")
    with tabs[1]: show_region_table("美洲")
    with tabs[2]: show_region_table("欧洲")
    with tabs[3]:
        # 全球总览加一个散点图
        st.subheader("🌐 全球 IP 质量分布")
        st.scatter_chart(df, x='jitter', y='loss', color='region', size='score')
        st.caption("注：越靠近左下角 (低抖动/低丢包) 质量越好")

else:
    st.warning("📡 系统正在进行首次全球扫描与地理定位... 请稍候 20 秒")
    st.progress(0.4)
    time.sleep(5)
    st.rerun()

time.sleep(10)
st.rerun()
