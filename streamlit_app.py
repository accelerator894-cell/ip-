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
from datetime import datetime, timedelta
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 页面配置与黑客风 UI
# ===========================
st.set_page_config(page_title="VLESS 终极全能版", page_icon="🎛️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    div[data-testid="column"] { background-color: #1a1c24; border: 1px solid #2d3139; border-radius: 8px; padding: 15px; }
    
    /* 模式徽章样式 */
    .badge-normal { background-color: #2ECC40; color: #000; padding: 4px 10px; border-radius: 4px; font-weight: bold; }
    .badge-peak { background-color: #0074D9; color: #fff; padding: 4px 10px; border-radius: 4px; font-weight: bold; }
    .badge-native { background-color: #B10DC9; color: #fff; padding: 4px 10px; border-radius: 4px; font-weight: bold; }
    
    /* Ping0 风格数值 */
    .ping0-value { color: #00ff41; font-family: 'Courier New', monospace; font-size: 1.4rem; }
    
    /* 标签 */
    .tag-seed { background-color: #FFDC00; color: #000; padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 配置加载
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.error("❌ 配置缺失！请在 Streamlit Secrets 中配置 api_token, zone_id, record_name")
    st.stop()

SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 3. 核心工具函数
# ===========================

def generate_cold_ips(count=30):
    """生成冷门段 (避峰模式专用)"""
    prefixes = ["162.159.36", "162.159.46", "198.41.214", "172.64.198", "103.21.244"]
    return [f"{random.choice(prefixes)}.{random.randint(1, 254)}" for _ in range(count)]

@st.cache_data(ttl=3600)
def get_ip_extended_info(ip):
    """获取 IP 的 ISP 和是否为原生"""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=country,isp,hosting", timeout=2.5).json()
        return {
            "country": r.get("country", "Unk"),
            "isp": r.get("isp", "Unk"),
            "is_native": not r.get("hosting", True) # hosting=False 即为原生
        }
    except: return {"country": "Unk", "isp": "Unk", "is_native": False}

def ping0_tcp_test(ip, count=5):
    """Ping0 级 TCP 握手测速"""
    lats, success = [], 0
    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.7)
            t1 = time.perf_counter()
            s.connect((ip, 443))
            s.close()
            lats.append((time.perf_counter() - t1) * 1000)
            success += 1
        except: pass
        time.sleep(0.01)
    
    if not lats: return {"avg": 9999, "jitter": 0, "loss": 100}
    return {
        "avg": int(statistics.mean(lats)),
        "jitter": int(statistics.stdev(lats)) if len(lats) > 1 else 0,
        "loss": int(((count - success) / count) * 100)
    }

def get_pool(mode):
    """
    【修复版】构建选手池，包含强制保底机制
    """
    pool = []
    seen = set()
    
    # 1. 历史库
    if os.path.exists(SAVED_IP_FILE):
        with open(SAVED_IP_FILE, "r") as f:
            for ip in re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', f.read()):
                if ip not in seen:
                    pool.append({"ip": ip, "type": "history"})
                    seen.add(ip)

    # 2. 避峰模式注入冷门 IP
    if mode == "🌙 晚高峰避峰排位":
        cold_ips = generate_cold_ips(60)
        for ip in cold_ips:
            if ip not in seen:
                pool.append({"ip": ip, "type": "cold"})
                seen.add(ip)
    
    # 3. 在线爬虫 (增加官方源)
    urls = [
        "https://www.cloudflare.com/ips-v4", # 官方源，最稳
        "https://raw.githubusercontent.com/DerGoogler/CloudFlare-IP-Best/main/ip.txt", 
        "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"
    ]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        def fetch(u):
            try: 
                # 6秒超时，防止爬虫卡死
                return re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', requests.get(u, headers={'User-Agent': 'Mozilla/5.0'}, timeout=6).text)
            except: return []
        
        for res in ex.map(fetch, urls):
            sample_size = 150 if mode == "🧬 原生IP分数排位" else 80
            if res:
                for ip in random.sample(res, min(len(res), sample_size)):
                    if ip not in seen:
                        pool.append({"ip": ip, "type": "hot"})
                        seen.add(ip)
    
    # === 【兜底修复】 ===
    # 如果此时节点过少（比如爬虫失败），强制注入保底种子
    if len(pool) < 5:
        seeds = [
            "1.1.1.1", "1.0.0.1", "104.16.0.1", "104.17.0.1", "104.18.0.1",
            "172.67.1.1", "104.21.1.1", "188.114.96.1", "188.114.97.1",
            "162.159.192.1", "198.41.214.1", "172.64.198.1"
        ]
        for ip in seeds:
            if ip not in seen:
                pool.append({"ip": ip, "type": "seed"})
                seen.add(ip)
                
    return pool

def calculate_score(mode, p0, speed, info, node_type):
    """三模评分引擎"""
    score = 100
    
    # A. 避峰模式：稳字当头
    if mode == "🌙 晚高峰避峰排位":
        score -= (p0['loss'] * 50)     
        score -= (p0['jitter'] * 5)    
        score -= (p0['avg'] / 10)      
        score += (speed * 8)
        if node_type == "cold": score += 20 
        
    # B. 原生模式：原生至上
    elif mode == "🧬 原生IP分数排位":
        score -= (p0['loss'] * 20)
        score -= (p0['avg'] / 4)       
        score += (speed * 10)
        if info['is_native']: score += 1000 # 霸道加分
        
    # C. 均衡模式
    else:
        score -= (p0['loss'] * 20)
        score -= (p0['avg'] / 5)       
        score -= (p0['jitter'] * 1)
        score += (speed * 15)          

    return round(score, 1)

def deep_test_node(node, mode):
    ip = node['ip']
    
    # 1. 基础连通性
    p0 = ping0_tcp_test(ip)
    limit = 800 if mode == "🌙 晚高峰避峰排位" else 600
    if p0['avg'] > limit: return None
    
    # 2. 信息获取
    info = get_ip_extended_info(ip)
    
    # 3. 速度测试 (2MB)
    speed = 0.0
    try:
        s = time.perf_counter()
        r = requests.get(f"http://{ip}/__down?bytes=2000000", headers={"Host": "speed.cloudflare.com"}, timeout=4)
        if r.status_code == 200:
            speed = (len(r.content)/1024/1024) / (time.perf_counter() - s)
    except: pass

    # 4. 计算得分
    score = calculate_score(mode, p0, speed, info, node['type'])
    
    # 入库判断
    should_save = score > 85
    if mode == "🧬 原生IP分数排位" and not info['is_native']: should_save = False
    
    if should_save:
        with open(SAVED_IP_FILE, "a") as f: f.write(f"{ip}\n")

    return {
        "ip": ip, "score": score, "source": node['type'],
        "tcp": p0['avg'], "jitter": p0['jitter'], "loss": p0['loss'],
        "speed": round(speed, 2), "isp": info['isp'], "is_native": info['is_native'], "country": info['country']
    }

def sync_dns(ip):
    """同步 IP 到 Cloudflare"""
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        recs = requests.get(url, headers=headers, params={"name": CF_CONFIG['record_name']}, timeout=5).json()
        if recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == ip: return "✅ IP未变"
            requests.put(f"{url}/{rid}", headers=headers, json={"type":"A","name":CF_CONFIG['record_name'],"content":ip,"ttl":60,"proxied":False})
            return f"🚀 已更新: {ip}"
    except: return "⚠️ API异常"
    return "❌ 记录无效"

# ===========================
# 4. 主控界面
# ===========================
st.title("🎛️ VLESS 终极全能版")

if "last_run" not in st.session_state: st.session_state.last_run = datetime.min
if "auto_enabled" not in st.session_state: st.session_state.auto_enabled = True

with st.sidebar:
    st.header("⚙️ 模式选择")
    mode = st.radio("🎯 请选择排位策略", 
                    ["☀️ 正常使用排位", "🌙 晚高峰避峰排位", "🧬 原生IP分数排位"],
                    captions=["均衡模式 (日间)", "稳定防断流 (夜间)", "解锁流媒体 (Netflix)"])
    
    st.divider()
    st.session_state.auto_enabled = st.toggle("⏱️ 10分钟自动循环", value=st.session_state.auto_enabled)
    if st.button("🗑️ 清空库"):
        if os.path.exists(SAVED_IP_FILE): os.remove(SAVED_IP_FILE)
        st.toast("缓存已清空")

# UI 状态显示
if mode == "☀️ 正常使用排位":
    st.markdown("当前状态: <span class='badge-normal'>BALANCED</span> 均衡模式", unsafe_allow_html=True)
elif mode == "🌙 晚高峰避峰排位":
    st.markdown("当前状态: <span class='badge-peak'>STABLE</span> 避峰模式", unsafe_allow_html=True)
else:
    st.markdown("当前状态: <span class='badge-native'>NATIVE</span> 解锁模式", unsafe_allow_html=True)

# 触发逻辑
now = datetime.now()
trigger = st.session_state.auto_enabled and (now - st.session_state.last_run >= timedelta(minutes=10))
manual = st.button("🏁 开始排位", type="primary", use_container_width=True)

if manual or trigger:
    st.session_state.last_run = now
    
    with st.status(f"🔍 正在执行 [{mode}] 策略...", expanded=True) as status:
        pool = get_pool(mode)
        st.write(f"已加载 {len(pool)} 个候选节点 (含保底种子)...")
        
        results = []
        prog = st.progress(0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            futs = [ex.submit(deep_test_node, x, mode) for x in pool]
            for i, f in enumerate(concurrent.futures.as_completed(futs)):
                prog.progress((i+1)/len(pool))
                res = f.result()
                if res: results.append(res)
        status.update(label="✅ 排位完成", state="complete")

    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        sync_msg = sync_dns(winner['ip'])
        
        # 冠军展示
        st.markdown(f"### 🏆 冠军: {winner['ip']}")
        tags = f"📡 {winner['isp']}"
        if winner['is_native']: tags += " | <span class='badge-native'>🧬 原生IP</span>"
        if winner['source'] == 'seed': tags += " | <span class='tag-seed'>🛡️ 保底种子</span>"
        st.markdown(tags, unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("得分", winner['score'])
        c2.metric("延迟", f"{winner['tcp']} ms", f"±{winner['jitter']}")
        c3.metric("带宽", f"{winner['speed']} MB/s")
        c4.metric("解析", sync_msg)
        
        st.divider()
        df = pd.DataFrame(results)
        cols = ['score', 'ip', 'tcp', 'speed', 'isp']
        if mode == "🌙 晚高峰避峰排位": cols.insert(2, 'loss')
        if mode == "🧬 原生IP分数排位": cols.insert(1, 'is_native')
        
        st.dataframe(
            df[cols],
            use_container_width=True,
            column_config={
                "score": st.column_config.ProgressColumn("得分", format="%.1f"),
                "is_native": st.column_config.CheckboxColumn("原生?"),
                "tcp": st.column_config.NumberColumn("延迟(ms)", format="%d"),
            }
        )

    if st.session_state.auto_enabled:
        time.sleep(2)
        st.rerun()

if st.session_state.auto_enabled:
    time.sleep(30)
    st.rerun()
