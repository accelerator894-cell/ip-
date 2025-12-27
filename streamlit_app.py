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
# 1. 基础配置
# ===========================
st.set_page_config(page_title="VLESS 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
NICHE_FILE = "niche_pool.json"      
CONFIG_FILE = "app_config.json"     

# 极速启动种子
QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]

# 黄金冷门网段
GOLDEN_SUBNETS = ["104.28.0.0/16", "172.67.128.0/17", "104.21.0.0/16", "172.64.0.0/13"]

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="column"] { background-color: #1a1c24; border-radius: 8px; padding: 15px; border: 1px solid #2d2f3b; }
    </style>
    """, unsafe_allow_html=True)

# ===========================
# 2. 核心功能函数
# ===========================

def get_geo_info(ip):
    """获取 IP 国家及位置信息"""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,isp", timeout=1.5).json()
        if r.get("status") == "success":
            return {
                "country": r.get("country", "Unknown"),
                "cc": r.get("countryCode", "UN"),
                "isp": r.get("isp", "")
            }
    except: pass
    return {"country": "Unknown", "cc": "UN", "isp": ""}

def safe_load_json(file_path):
    """稳健的 JSON 读取，防止读取中途崩溃导致黑屏"""
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

# ===========================
# 3. 前端展示逻辑
# ===========================

st.title("🧬 Cloudflare 猎手进化版")

# 获取侧边栏配置
with st.sidebar:
    st.header("🛠️ 配置控制台")
    # 此处省略模式选择代码，逻辑保持不变
    if st.button("💾 保存配置"):
        st.toast("配置已更新，正在进化...", icon="🧬")
        time.sleep(1)
        st.rerun()

# 主界面数据渲染
data = safe_load_json(RESULT_FILE)

if data:
    try:
        winner = data.get('winner', {})
        st.markdown(f"### 🏆 当前最强 IP: `{winner.get('ip')}` | 地区: {winner.get('country', 'Unknown')}")
        
        # 指标展示
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("进化得分", winner.get('score', 0))
        c2.metric("延迟", f"{winner.get('avg', 0)} ms")
        c3.metric("速度", f"{winner.get('speed', 0)} MB/s")
        c4.metric("来源", winner.get('src', 'Unknown'))

        st.divider()
        
        # 数据表格展示与分类标记
        df = pd.DataFrame(data.get('table', []))
        if not df.empty:
            # 格式化国家和来源
            df['国家'] = df.apply(lambda x: f"{x.get('cc', 'UN')} {x.get('country', 'Unknown')}", axis=1)
            
            st.dataframe(
                df,
                column_order=("score", "src", "ip", "国家", "avg", "speed"),
                column_config={
                    "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=100),
                    "src": "分类来源",
                    "ip": "IP 地址",
                    "speed": st.column_config.NumberColumn("下载速度", format="%.2f MB/s"),
                },
                use_container_width=True,
                hide_index=True
            )
        
        st.caption(f"上次进化: {data.get('last_run')} | 10秒轮询中...")
        
        # 自动刷新逻辑
        time.sleep(5)
        st.rerun()

    except Exception as e:
        st.error(f"渲染异常，正在重试... {e}")
        time.sleep(2)
        st.rerun()
else:
    st.info("🚀 引擎初始化中，正在加载本地 IP 段并进行首轮比武...")
    time.sleep(3)
    st.rerun()
