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
# 1. 页面配置 (Ping0 风格配色)
# ===========================
st.set_page_config(page_title="VLESS 竞速 - Ping0 增强版", page_icon="📶", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    /* 模仿 Ping0 的深蓝色面板 */
    div[data-testid="column"] { 
        background-color: #1a1c24; 
        border: 1px solid #2d3139; 
        border-radius: 10px; 
        padding: 20px; 
    }
    .ping0-label { color: #8a92a6; font-size: 0.8rem; font-weight: bold; }
    .ping0-value { color: #00ff41; font-family: 'Courier New', monospace; font-size: 1.5rem; }
    .stMetricValue { color: #00ff41 !important; font-family: 'Courier New', monospace; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心逻辑：Ping0 (TCP) 模拟引擎
# ===========================

def ping0_tcp_test(ip, port=443, count=5):
    """
    模拟 Ping0.com 的 TCP 探测机制
    进行 5 次高精度握手测试，计算平均值、最小值和抖动
    """
    latencies = []
    success = 0
    for _ in range(count):
        try:
            start = time.perf_counter()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((ip, port))
            s.close()
            # 毫秒级精度
            latencies.append((time.perf_counter() - start) * 1000)
            success += 1
        except:
            pass
        time.sleep(0.02) # 探测间隔
    
    if not latencies:
        return {"avg": 9999, "min": 9999, "jitter": 0, "loss": 100}
    
    return {
        "avg": int(statistics.mean(latencies)),
        "min": int(min(latencies)),
        "jitter": int(statistics.stdev(latencies)) if len(latencies) > 1 else 0,
        "loss": int(((count - success) / count) * 100)
    }

# ===========================
# 3. 增强版深度评测
# ===========================

def deep_test_node(node):
    ip = node['ip']
    
    # --- Ping0 测试环节 ---
    p0 = ping0_tcp_test(ip)
    if p0['avg'] > 1500: return None # 响应太慢直接过滤

    # --- 地理位置识别 ---
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        region = r.get("country", "Unknown")
        cc = r.get("countryCode", "UNK")
        area = "🌏 亚洲" if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG'] else "🌍 其他"
    except:
        area, region = "🛸 未知", "Unknown"

    # --- 速度实测 (2MB) ---
    speed_mb = 0.0
    try:
        s_time = time.perf_counter()
        r = requests.get(f"http://{ip}/__down?bytes=2000000", 
                         headers={"Host": "speed.cloudflare.com"}, timeout=4)
        if r.status_code == 200:
            speed_mb = (len(r.content)/1024/1024) / (time.perf_counter() - s_time)
    except: pass

    # --- 电信专属综合评分 ---
    # 延迟分(40%) + 丢包罚分(30%) + 速度加分(30%)
    score = 100 - (p0['avg'] / 5) - (p0['loss'] * 20) + (speed_mb * 12) - (p0['jitter'] * 2)

    return {
        "ip": ip, "area": area, "country": region, 
        "score": round(score, 1), "tcp_avg": p0['avg'], 
        "tcp_min": p0['min'], "jitter": p0['jitter'],
        "loss": p0['loss'], "speed": round(speed_mb, 2),
        "source": node['source']
    }

# ===========================
# 4. UI 界面与自动化
# ===========================
st.title("🏎️ VLESS 竞速 - Ping0 自动化排位版")

# 侧边栏与 10 分钟自动逻辑
if "last_run" not in st.session_state: st.session_state.last_run = datetime.min

with st.sidebar:
    st.header("⚙️ 自动化中心")
    auto_on = st.toggle("开启 10 分钟自动更新", value=True)
    st.write(f"上次运行: {st.session_state.last_run.strftime('%H:%M:%S')}")
    if st.button("🗑️ 重置本地库"):
        if os.path.exists("good_ips.txt"): os.remove("good_ips.txt")

# 核心触发逻辑
now = datetime.now()
should_run = (auto_on and (now - st.session_state.last_run >= timedelta(minutes=10)))

if st.button("🏁 手动强制排位", type="primary") or should_run:
    st.session_state.last_run = now
    
    # 选手池（复用之前的高质量爬虫）
    from __main__ import get_enhanced_pool # 假设此函数在同文件
    tasks = get_enhanced_pool() 
    
    with st.status("🚀 正在启动 Ping0 级探测...", expanded=True) as status:
        results = []
        progress = st.progress(0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
            futs = [ex.submit(deep_test_node, t) for t in tasks]
            for i, f in enumerate(concurrent.futures.as_completed(futs)):
                progress.progress((i + 1) / len(tasks))
                res = f.result()
                if res: results.append(res)
        status.update(label="✅ 测试完成", state="complete")

    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        winner = results[0]
        
        # 冠军面板：Ping0 风格展示
        st.subheader("🏆 冠军节点 (Ping0 数据)")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown("<p class='ping0-label'>IP 地址</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='ping0-value'>{winner['ip']}</p>", unsafe_allow_html=True)
        with col2:
            st.metric("Ping0 (TCP AVG)", f"{winner['tcp_avg']} ms")
        with col3:
            st.metric("带宽 (2MB Test)", f"{winner['speed']} MB/s")
        with col4:
            st.metric("丢包率", f"{winner['loss']}%")

        # 详细表格
        st.divider()
        df = pd.DataFrame(results)
        st.dataframe(
            df[['score', 'ip', 'tcp_avg', 'tcp_min', 'jitter', 'speed', 'country']],
            use_container_width=True,
            column_config={
                "tcp_avg": "平均延迟",
                "tcp_min": "最小延迟",
                "jitter": "抖动",
                "speed": "测速(MB/s)"
            }
        )
        
        # 自动同步 DNS
        from __main__ import sync_dns
        st.info(sync_dns(winner['ip']))

    if auto_on:
        time.sleep(10) # 缓冲
        st.rerun()

# 自动刷新占位
if auto_on:
    time.sleep(30)
    st.rerun()
