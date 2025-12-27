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
# 1. 页面配置与 UI 风格
# ===========================
st.set_page_config(page_title="VLESS 时空智能指挥官", page_icon="🧬", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #15171e; border: 1px solid #262730; border-radius: 8px; padding: 15px; }
    /* 进度条颜色 */
    div[data-testid="stProgress"] > div > div > div > div { background-color: #00CC96; }
    </style>
    """, unsafe_allow_html=True)

# 核心文件路径
RESULT_FILE = "scan_results.json"
CONFIG_FILE = "app_config.json"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 2. 核心算法工具箱
# ===========================

def get_config():
    """读取配置"""
    default = {"mode": "☀️ 正常使用排位"}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f: return json.load(f)
        except: return default
    return default

def save_config(mode):
    """保存配置"""
    with open(CONFIG_FILE, "w") as f: json.dump({"mode": mode}, f)

def get_time_slot():
    """判断当前网络时段"""
    h = datetime.now().hour
    if 19 <= h <= 23: return "PEAK"  # 晚高峰 (19:00-23:00)
    if 1 <= h <= 6:   return "IDLE"  # 闲时 (01:00-06:00)
    return "NORMAL"                  # 常规时段

def ping0_tcp_test(ip, count=5):
    """
    【Ping0 核心算法】
    计算 TCP 握手的 平均延迟、抖动(Jitter)、丢包率(Loss)
    """
    lats = []
    success = 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.6) # 600ms 超时
            t1 = time.perf_counter()
            s.connect((ip, 443))
            s.close()
            lats.append((time.perf_counter() - t1) * 1000)
            success += 1
        except: pass
        time.sleep(0.02) # 极短间隔
    
    if not lats: return {"avg": 9999, "jitter": 0, "loss": 100}
    
    avg = statistics.mean(lats)
    # 计算抖动 (标准差)
    jitter = statistics.stdev(lats) if len(lats) > 1 else 0
    loss = ((count - success) / count) * 100
    
    return {"avg": int(avg), "jitter": int(jitter), "loss": int(loss)}

def get_china_latency(ip):
    """模拟中国国内连接延迟"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        t1 = time.perf_counter()
        s.connect((ip, 443))
        dur = (time.perf_counter() - t1) * 1000
        s.close()
        return int(dur)
    except: return 999

def calculate_score(mode, p0, cn_lat, speed, info, node_type):
    """
    【综合评分引擎】
    结合 Ping0 (抖动/丢包) + 国测延迟 + 速度 + 模式权重
    """
    score = 1000 # 基础分
    
    # 1. 减分项 (越低越好)
    score -= cn_lat * 1.5          # 国测延迟权重高
    score -= p0['loss'] * 50       # 丢包是致命的，丢1%扣50分
    score -= p0['jitter'] * 5      # 抖动扣分
    score -= p0['avg'] * 0.2       # 基础握手延迟微量扣分
    
    # 2. 加分项 (越高越好)
    score += speed * 40            # 速度每1MB/s 加40分
    
    # 3. 模式加成
    if mode == "🌙 晚高峰避峰排位":
        # 避峰模式极度厌恶丢包
        score -= p0['loss'] * 50   # 再次加倍扣丢包分
        if node_type in ["🌙 避峰冷门", "🧬 基因衍生"]: 
            score += 100           # 扶持冷门和衍生IP
            
    elif mode == "🧬 原生IP分数排位":
        if info.get('is_native'): score += 800 # 原生直接起飞
        else: score -= 500         # 非原生直接淘汰
    
    return round(score, 1)

def sync_dns(ip):
    """Cloudflare DNS 同步"""
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

def genetic_expansion(history_ips):
    """
    🧬 遗传算法：基于历史优选 IP，生成其邻居段
    如果 1.2.3.4 是好的，那么生成 1.2.3.1 ~ 1.2.3.254
    """
    candidates = set()
    if not history_ips: return candidates
    
    # 取最新的 5 个优质 IP 进行繁衍
    parents = history_ips[-5:]
    for ip in parents:
        try:
            subnet = ".".join(ip.split(".")[:3])
            # 随机生成 5 个邻居
            for _ in range(5):
                candidates.add(f"{subnet}.{random.randint(1, 254)}")
        except: pass
    return candidates

def smart_crawler(mode, time_slot):
    """时空智能爬虫"""
    pool = []
    seen = set()
    
    # A. 读取历史基因 (History)
    history_ips = []
    if os.path.exists(SAVED_IP_FILE):
        with open(SAVED_IP_FILE, "r") as f:
            history_ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read())
            # 1. 加入历史传家宝
            for ip in history_ips[-10:]:
                if ip not in seen:
                    pool.append({"ip": ip, "type": "🏆 历史传家宝"})
                    seen.add(ip)

    # B. 基因衍生 (Genetic) - 全时段生效
    genetic_ips = genetic_expansion(history_ips)
    for ip in genetic_ips:
        if ip not in seen:
            pool.append({"ip": ip, "type": "🧬 基因衍生"})
            seen.add(ip)

    # C. 时段特异性策略
    if time_slot == "PEAK":
        # 🌙 晚高峰：强制注入冷门段
        cold_prefixes = ["162.159.36", "162.159.46", "198.41.214", "172.64.198"]
        for _ in range(30):
            ip = f"{random.choice(cold_prefixes)}.{random.randint(1, 254)}"
            if ip not in seen:
                pool.append({"ip": ip, "type": "🌙 避峰冷门"})
                seen.add(ip)
    else:
        # ☀️ 常规/闲时：从 GitHub 爬取热搜 IP
        try:
            urls = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", "https://www.cloudflare.com/ips-v4"]
            for u in urls:
                txt = requests.get(u, timeout=3).text
                found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', txt)
                for ip in random.sample(found, min(len(found), 30)):
                    if ip not in seen:
                        pool.append({"ip": ip, "type": "🔥 每日热搜"})
                        seen.add(ip)
        except: pass
        
    return pool

def background_worker():
    """后台守护主进程"""
    while True:
        try:
            cfg = get_config()
            mode = cfg["mode"]
            time_slot = get_time_slot()
            
            # 1. 智能获取 IP 池
            pool = smart_crawler(mode, time_slot)
            
            # 2. 多线程深度 Ping0 测试
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def process_node(node):
                    ip = node['ip']
                    
                    # 阶段1: 快速国测筛选 (必须能连通中国)
                    cn_lat = get_china_latency(ip)
                    if cn_lat > 600: return None
                    
                    # 阶段2: Ping0 深度测试 (计算抖动/丢包)
                    p0 = ping0_tcp_test(ip)
                    if p0['loss'] > 20: return None # 丢包超过20%直接丢弃
                    
                    # 阶段3: 测速 (小文件 500KB)
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=500000", headers={"Host": "speed.cloudflare.com"}, timeout=3)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 阶段4: 扩展信息 (仅原生模式需要)
                    info = {"is_native": False}
                    if mode == "🧬 原生IP分数排位":
                        try:
                            r = requests.get(f"http://ip-api.com/json/{ip}?fields=hosting", timeout=2).json()
                            info['is_native'] = not r.get("hosting", True)
                        except: pass

                    # 阶段5: 算分
                    score = calculate_score(mode, p0, cn_lat, speed, info, node['type'])
                    
                    return {
                        "ip": ip, "score": score, "cn_lat": cn_lat, "speed": round(speed, 2),
                        "loss": p0['loss'], "jitter": p0['jitter'], "type": node['type']
                    }

                futs = [ex.submit(process_node, n) for n in pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res and res['score'] > 0: results.append(res)

            # 3. 结算
            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                
                # 持久化优质 IP (为遗传算法提供养料)
                with open(SAVED_IP_FILE, "a") as f:
                    for r in results[:3]: f.write(f"{r['ip']}\n")
                
                # 同步 DNS
                sync_msg = sync_dns(winner['ip'])
                
                # 保存状态
                state = {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "time_slot": time_slot,
                    "mode": mode,
                    "winner": winner,
                    "sync_msg": sync_msg,
                    "table": results[:20]
                }
                with open(RESULT_FILE, "w") as f: json.dump(state, f)
                
        except Exception as e: print(f"Worker Error: {e}")
        
        # 智能休眠: 晚高峰跑勤快点(5分)，闲时跑慢点(20分)
        sleep_time = 300 if time_slot == "PEAK" else 1200
        time.sleep(sleep_time)

# 启动后台
if "bg_thread" not in st.session_state:
    import threading
    threading.Thread(target=background_worker, daemon=True).start()
    st.session_state.bg_thread = True

# ===========================
# 4. 前端可视化指挥台
# ===========================
with st.sidebar:
    st.header("🎮 策略中心")
    curr = get_config()
    new_mode = st.radio("选择模式", ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🧬 原生IP分数排位"], index=["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🧬 原生IP分数排位"].index(curr.get("mode", "☀️ 正常使用排位")))
    if new_mode != curr.get("mode"):
        save_config(new_mode)
        st.toast(f"策略已切换: {new_mode}", icon="🔄")

st.title("🧬 VLESS 时空智能指挥官")

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f: data = json.load(f)
    winner = data['winner']
    
    # 状态栏
    slot_map = {"PEAK": "🌙 晚高峰 (激进防御)", "IDLE": "💤 闲时 (休眠维护)", "NORMAL": "☀️ 常规 (广度扫描)"}
    st.info(f"环境: {slot_map.get(data['time_slot'], '未知')} | 策略: {data['mode']} | 更新: {data['last_run']}")
    
    # 核心指标
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👑 冠军 IP", winner['ip'])
    c2.metric("🌏 中国延迟", f"{winner['cn_lat']} ms")
    c3.metric("💔 丢包/抖动", f"{winner['loss']}% / {winner['jitter']}ms")
    c4.metric("🚀 下载速度", f"{winner['speed']} MB/s")
    
    st.divider()
    
    # 图表分析
    df = pd.DataFrame(data['table'])
    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        st.subheader("📊 综合评分排行")
        st.bar_chart(df.head(10).set_index("ip")['score'])
    with col_chart2:
        st.subheader("🧬 IP 来源分布")
        st.scatter_chart(df, x='cn_lat', y='speed', color='type', size='score')

    # 详细表格
    st.subheader("📋 战术排位表")
    st.dataframe(
        df,
        column_order=("score", "ip", "type", "cn_lat", "loss", "jitter", "speed"),
        column_config={
            "score": st.column_config.ProgressColumn("Ping0 得分", format="%.0f", min_value=0, max_value=1200),
            "type": st.column_config.TextColumn("分类标签"),
            "cn_lat": st.column_config.NumberColumn("CN延迟", format="%d ms"),
            "loss": st.column_config.NumberColumn("丢包率", format="%d%%"),
            "jitter": st.column_config.NumberColumn("抖动", format="%d ms"),
            "speed": st.column_config.NumberColumn("速度", format="%.2f MB/s"),
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.warning("🧬 系统正在初始化基因库与首次扫描，请稍候 15-20 秒...")
    st.progress(0.3)
    time.sleep(5)
    st.rerun()

time.sleep(10)
st.rerun()
