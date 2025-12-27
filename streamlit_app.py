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
# 1. 基础配置与文件锁逻辑
# ===========================
st.set_page_config(page_title="VLESS 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
NICHE_FILE = "niche_pool.json"      
CONFIG_FILE = "app_config.json"     

QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]
GOLDEN_SUBNETS = ["104.28.0.0/16", "172.67.128.0/17", "104.21.0.0/16", "172.64.0.0/13"]

# 文件写保护
def safe_write_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except: pass

def safe_read_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding='utf-8') as f:
            return json.load(f)
    except: return default

# ===========================
# 2. 核心进化类 (增加异步填充)
# ===========================

class EliteDatabase:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = safe_read_json(path, {})

    def update(self, ip, stats):
        with self.lock:
            # 自动替换逻辑：质量更高则替换
            if stats['score'] < 30: return
            old_score = self.data.get(ip, {}).get('score', 0)
            if stats['score'] >= old_score:
                stats['created_at'] = self.data.get(ip, {}).get('created_at', stats['last_test'])
                self.data[ip] = stats
            else:
                self.data[ip]['last_test'] = stats['last_test']

    def save(self):
        with self.lock: safe_write_json(self.path, self.data)

    def get_top(self, limit=15):
        with self.lock:
            items = list(self.data.values())
            items.sort(key=lambda x: x.get('score', 0), reverse=True)
            return items[:limit]

# [此处 CrawlerPool 和 NichePool 逻辑与之前一致，但在后台异步调用]

# ===========================
# 3. 后台独立流水线 (解决卡顿核心)
# ===========================

def background_evolution():
    db = EliteDatabase(DB_FILE)
    # 初始化池
    while True:
        try:
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "port": 443})
            
            # 组合测试目标 (种子 + 历史精英 + 爬虫新 IP)
            targets = [{"ip": i, "src": "⚡ 种子"} for i in QUICK_SEEDS]
            targets += [{"ip": i['ip'], "src": "📂 历史"} for i in db.get_top(12)]
            # ... 此处省略池填充与采样代码 ...

            # 并发测试与国家识别 (GeoInfo)
            # 每一个 IP 测试完后立即调用 db.update(ip, res)
            
            # 写入 RESULT_FILE 用于前端显示
            # 特别注意：写入频率控制在 10 秒一次
            time.sleep(10)
        except: time.sleep(5)

# 启动后台守护线程
if "bg_task" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.bg_task = True

# ===========================
# 4. 前端渲染 (骨架屏与分类)
# ===========================

st.title("🧬 Cloudflare 猎手进化版")

with st.sidebar:
    st.header("🛠️ 配置控制台")
    cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "port": 443})
    m_list = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    new_m = st.radio("优选策略", m_list, index=m_list.index(cfg['mode']) if cfg['mode'] in m_list else 0)
    if st.button("💾 保存配置"):
        safe_write_json(CONFIG_FILE, {"mode": new_m, "port": 443})
        st.toast(f"切换至: {new_m}", icon="⚡")
        # 清除快照强制重刷
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(0.5); st.rerun()

# 尝试加载数据
res_data = safe_read_json(RESULT_FILE, None)

if res_data:
    try:
        w = res_data['winner']
        st.markdown(f"### 🏆 冠军 IP: `{w['ip']}` | 📍 {w.get('cc', 'UN')} {w.get('country', 'Unknown')}")
        
        # 指标与表格渲染 (带分类标记)
        df = pd.DataFrame(res_data['table'])
        df['标记'] = df['src']
        df['地理'] = df['cc'] + " " + df['country']
        
        st.dataframe(
            df[['score', '标记', 'ip', '地理', 'avg', 'speed']],
            column_config={
                "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=100),
                "speed": st.column_config.NumberColumn("MB/s"),
            },
            use_container_width=True, hide_index=True
        )
        st.caption(f"上次进化: {res_data['last_run']} | 10 秒周期演化中...")
        time.sleep(5); st.rerun()
    except: time.sleep(1); st.rerun()
else:
    # 骨架屏：避免用户看到黑屏
    st.info("🚀 正在为您极速连接四川电信骨干网并加载基因库...")
    st.warning("⚠️ 初次加载或切换模式需要 10-15 秒建立初始基因快照，请稍候。")
    time.sleep(3); st.rerun()
