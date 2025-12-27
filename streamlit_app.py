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

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 页面配置
# ===========================
st.set_page_config(page_title="VLESS 可视化监控台", page_icon="📊", layout="wide")

# 注入一点样式让图表更好看
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="metric-container"] {
        background-color: #1a1c24;
        border: 1px solid #333;
        padding: 10px;
        border-radius: 8px;
    }
    </style>
    """, unsafe_allow_html=True)

RESULT_FILE = "scan_results.json"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 2. 核心工具函数 (保持极速版逻辑)
# ===========================

def get_china_latency_fast(ip):
    """极速国测：只测 443 端口，超短超时"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4) # 400ms 极速超时
        t1 = time.perf_counter()
        s.connect((ip, 443))
        dur = (time.perf_counter() - t1) * 1000
        s.close()
        return int(dur)
    except:
        return 999

def sync_dns(ip):
    # 这里保留你的 DNS 同步逻辑，如果未配置 Secrets 则跳过
    try:
        if "api_token" not in st.secrets: return "未配置 API"
        cfg = st.secrets
        url = f"https://api.cloudflare.com/client/v4/zones/{cfg['zone_id']}/dns_records"
        headers = {"Authorization": f"Bearer {cfg['api_token']}", "Content-Type": "application/json"}
        recs = requests.get(url, headers=headers, params={"name": cfg['record_name']}, timeout=5).json()
        if recs["result"]:
            rid = recs["result"][0]["id"]
            if recs["result"][0]["content"] == ip: return "✅ IP未变"
            requests.put(f"{url}/{rid}", headers=headers, json={"type":"A","name":cfg['record_name'],"content":ip,"ttl":60,"proxied":False})
            return f"🚀 已更新: {ip}"
    except: return "⚠️ 同步跳过"

# ===========================
# 3. 后台扫描逻辑
# ===========================

def background_worker_fast():
    while True:
        try:
            # 1. 快速抓取少量 IP
            pool_raw = []
            urls = ["https://www.cloudflare.com/ips-v4", "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
            for u in urls:
                try: 
                    text = requests.get(u, timeout=3).text
                    pool_raw.extend(re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', text))
                except: pass
            
            # 精简样本：只取 30 个，保证秒出结果
            final_pool = [{"ip": ip} for ip in random.sample(list(set(pool_raw)), min(len(pool_raw), 30))]
            
            results = []
            # 2. 高并发测速
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def run_test(node):
                    ip = node['ip']
                    cn_lat = get_china_latency_fast(ip)
                    if cn_lat > 600: return None
                    
                    # 极速测速 (200KB)
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes=200000", headers={"Host": "speed.cloudflare.com"}, timeout=2)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    # 评分：延迟越低分越高，速度越快分越高
                    score = 1000 - cn_lat + (speed * 80)
                    return {"ip": ip, "score": round(score,1), "cn_lat": cn_lat, "speed": round(speed,2)}

                futs = [ex.submit(run_test, n) for n in final_pool]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: results.append(res)

            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                winner = results[0]
                sync_msg = sync_dns(winner['ip'])
                
                # 写入 JSON
                data_to_save = {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "winner": winner,
                    "sync_msg": sync_msg,
                    "table": results[:20] # 只存前20名
                }
                with open(RESULT_FILE, "w") as f:
                    json.dump(data_to_save, f)
                    
        except Exception as e:
            print(f"Worker Error: {e}")
        
        # 每 10 分钟运行一次
        time.sleep(600)

# 启动后台
if "worker_started" not in st.session_state:
    import threading
    threading.Thread(target=background_worker_fast, daemon=True).start()
    st.session_state.worker_started = True

# ===========================
# 4. 前端可视化展示 (这里是你之前缺失的部分)
# ===========================
st.title("📊 VLESS 极速数据面板")

if os.path.exists(RESULT_FILE):
    # 读取数据
    with open(RESULT_FILE, "r") as f:
        data = json.load(f)
    
    winner = data['winner']
    all_data = data['table']
    df = pd.DataFrame(all_data)

    # --- 区域 1: 核心指标卡片 ---
    st.markdown("### 🏆 当前冠军节点")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("优选 IP", winner['ip'], delta="Live")
    c2.metric("中国延迟", f"{winner['cn_lat']} ms", delta_color="inverse")
    c3.metric("下载速度", f"{winner['speed']} MB/s")
    c4.metric("同步状态", data.get('sync_msg', '未开启'))

    st.divider()

    # --- 区域 2: 数据可视化图表 ---
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.subheader("📈 Top 10 得分排行")
        # 取前10名做柱状图
        top_10 = df.head(10).set_index("ip")
        st.bar_chart(top_10['score'], color="#00FF00")

    with col_chart2:
        st.subheader("🎯 延迟 vs 速度分布")
        # 散点图：横轴延迟，纵轴速度，点的大小代表得分
        st.scatter_chart(
            df,
            x='cn_lat',
            y='speed',
            color='score',
            size='score',
            use_container_width=True
        )

    st.divider()

    # --- 区域 3: 详细数据列表 ---
    st.subheader("📋 详细排位表")
    st.dataframe(
        df,
        column_order=("score", "ip", "cn_lat", "speed"),
        column_config={
            "score": st.column_config.ProgressColumn(
                "综合评分",
                help="基于延迟和速度计算",
                format="%.1f",
                min_value=0,
                max_value=1200,
            ),
            "cn_lat": st.column_config.NumberColumn(
                "国内延迟 (ms)",
                format="%d ms"
            ),
            "speed": st.column_config.NumberColumn(
                "速度 (MB/s)",
                format="%.2f MB/s"
            ),
            "ip": "IP 地址"
        },
        use_container_width=True,
        hide_index=True
    )
    
    st.caption(f"上次更新时间: {data['last_run']}")

else:
    # 如果还没有数据文件
    st.warning("⏳ 后台正在初始化首次数据，请稍等 10-15 秒...")
    st.progress(0.3, text="正在爬取节点并测速...")
    time.sleep(5)
    st.rerun()

# 自动刷新机制 (仅刷新 UI，不触发重测)
time.sleep(10)
st.rerun()
