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
# 1. 页面配置 & 样式
# ===========================
st.set_page_config(page_title="VLESS 终极竞速-Ping0加强版", page_icon="🏎️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #001f3f; color: #E0E0E0; }
    div[data-testid="column"] { background-color: #003366; border: 1px solid #0074D9; border-radius: 8px; padding: 15px; }
    div[data-testid="stMetricValue"] { color: #2ECC40 !important; font-family: 'Courier New', monospace; }
    .auto-active { color: #FF851B; font-weight: bold; animation: blinker 1.5s linear infinite; }
    @keyframes blinker { 50% { opacity: 0; } }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 基础配置 (从 Secrets 或本地读取)
# ===========================
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except:
    st.warning("⚠️ 检测到本地运行或 Secrets 缺失，解析同步功能将暂时跳过。")
    CF_CONFIG = None

DB_FILE = "racing_history.log"
SAVED_IP_FILE = "good_ips.txt"

# ===========================
# 3. 核心功能组件 (All-in-One 整合)
# ===========================

@st.cache_data(ttl=3600)
def get_ip_info(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=2).json()
        cc = r.get("countryCode", "UNK")
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG']: return "🌏 亚洲", r.get("country")
        return "🌍 其他", r.get("country")
    except: return "🛸 未知", "Unknown"

def ping0_core_test(ip, port=443, count=4):
    """模拟 Ping0 的 TCP 深度探测"""
    latencies = []
    for _ in range(count):
        try:
            start = time.perf_counter()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.8)
            s.connect((ip, port))
            s.close()
            latencies.append((time.perf_counter() - start) * 1000)
        except: pass
    
    if not latencies: return {"avg": 9999, "jitter": 0, "loss": 100}
    return {
        "avg": int(statistics.mean(latencies)),
        "jitter": int(statistics.stdev(latencies)) if len(latencies) > 1 else 0,
        "loss": int(((count - len(latencies)) / count) * 100)
    }

def get_enhanced_pool():
    """电信级高数量爬虫"""
    competitors = []
    seen_ips = set()
    
    # 1. 电信精选段
    for ip in ["1.0.0.1", "1.1.1.1", "104.16.0.1", "172.67.1.1"]:
        competitors.append({"ip": ip, "source": "💎 电信种子"})
        seen_ips.add(ip)

    # 2. 历史精英
    if os.path.exists(SAVED_IP
