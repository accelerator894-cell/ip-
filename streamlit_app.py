import streamlit as st
import requests
import time
import os
import json
import pandas as pd
import concurrent.futures
import socket
import threading
from datetime import datetime
import urllib3

# 禁用 HTTPS 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 基础配置与文件 IO
# ===========================
st.set_page_config(page_title="Cloudflare 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CONFIG_FILE = "app_config.json"     

QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]
COUNTRY_CN = {
    "CN": "中国", "HK": "香港", "TW": "台湾", "US": "美国", "JP": "日本",
    "SG": "新加坡", "KR": "韩国", "DE": "德国", "GB": "英国", "FR": "法国"
}

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
# 2. 进化引擎核心逻辑
# ===========================

def background_evolution():
    db_data = safe_read_json(DB_FILE, {})
    
    while True:
        try:
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
            
            # 构建待测目标
            targets = [{"ip": ip, "src": "⚡ 本地种子"} for ip in QUICK_SEEDS]
            history_ips = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:50]
            targets += [{"ip": i['ip'], "src": "📂 历史优选"} for i in history_ips]

            current_results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                def test_task(t):
                    ip = t['ip']
                    # --- 顺序 1: TCP 握手 (最高优先级) ---
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(0.5)
                        t1 = time.perf_counter()
                        s.connect((ip, int(cfg['port'])))
                        s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                    except: return None
                    
                    # --- 顺序 2: 路径可用性测试 (多路径策略) ---
                    path_status = "✅ 基础连接"
                    path_weight = 0
                    if "🤖 GPT" in cfg['mode']:
                        try:
                            r_gpt = requests.head(f"https://{ip}", headers={"Host": "chatgpt.com"}, timeout=1.0, verify=False)
                            if r_gpt.status_code != 403: 
                                path_status = "🤖 GPT 绿色"; path_weight = 25
                            else: path_status = "🚫 GPT 屏蔽"
                        except: path_status = "❌ 路径不通"
                    elif "🎬 流媒体" in cfg['mode']:
                        try:
                            r_m = requests.head(f"https://{ip}", headers={"Host": "www.netflix.com"}, timeout=1.0, verify=False)
                            if r_m.status_code < 500: 
                                path_status = "🎬 解锁通过"; path_weight = 20
                            else: path_status = "⚠️ 限制访问"
                        except: path_status = "❌ 路径不通"

                    # --- 顺序 3: 速度测试 (仅对延迟合格的 IP) ---
                    speed = 0.0
                    if p_avg < 400:
                        try:
                            st_t = time.perf_counter()
                            r = requests.get(f"https://{ip}/__down?bytes=100000", headers={"Host": cfg['host']}, timeout=1.5, verify=False)
                            speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                        except: pass

                    # --- 顺序 4: 地理位置 ---
                    geo_cn = "未知"
                    try:
                        g = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=0.8).json()
                        geo_cn = COUNTRY_CN.get(g.get("countryCode"), "海外区域")
                    except: pass

                    score = round(100 - p_avg/5 + min(speed*5, 30) + path_weight, 1)
                    res = {"ip": ip, "score": score, "avg": p_avg, "speed": round(speed, 2), 
                           "status": path_status, "src": t['src'], "geo": geo_cn,
                           "last_test": datetime.now().strftime("%H:%M:%S")}
                    
                    db_data[ip] = res
                    return res

                # 任务执行与整合
                unique_targets = {v['ip']:v for v in targets}.values()
                futs = [ex.submit(test_task, i) for i in unique_targets]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: 
                        current_results.append(r)
                        temp_sorted = sorted(current_results, key=lambda x: x['score'], reverse=True)
                        safe_write_json(RESULT_FILE, {
                            "last_run": datetime.now().strftime("%H:%M:%S"), 
                            "table": temp_sorted[:15], # 保存前 15 名备查
                            "mode": cfg['mode']
                        })
            safe_write_json(DB_FILE, db_data)
        except: pass
        time.sleep(15)

# 启动引擎
if "evolution_engine" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.evolution_engine = True

# ===========================
# 3. 前端界面 (排行 Top 10)
# ===========================

with st.sidebar:
    st.header("🛠️ 猎手控制台")
    cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
    modes = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    new_mode = st.radio("优选策略", modes, index=modes.index(cfg['mode']) if cfg['mode'] in modes else 0)
    
    if st.button("💾 应用新策略并重置"):
        cfg['mode'] = new_mode
        safe_write_json(CONFIG_FILE, cfg)
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        st.rerun()

st.title("🧬 Cloudflare 猎手：进化引擎")

data = safe_read_json(RESULT_FILE, None)
if data:
    table = data.get('table', [])
    if table:
        w = table[0]
        st.success(f"🏆 当前最优节点: `{w['ip']}` | 评分: {w['score']} | 状态: {w['status']}")
        
        st.divider()
        st.subheader("📊 基因库精英排行 (Top 10)")
        
        df = pd.DataFrame(table).head(10) # 强制取前 10 位
        st.dataframe(
            df,
            column_order=("score", "ip", "status", "geo", "avg", "speed", "last_test"),
            column_config={
                "score": st.column_config.ProgressColumn("综合评分", min_value=0, max_value=130),
                "ip": "IP 地址",
                "status": "路径状态",
                "geo": "位置",
                "avg": st.column_config.NumberColumn("延迟 (ms)"),
                "speed": st.column_config.NumberColumn("速 (MB/s)"),
            },
            use_container_width=True, hide_index=True
        )
        st.caption(f"🔄 引擎运行中 | 策略: {data['mode']} | 更新于: {data['last_run']}")
    
    time.sleep(5)
    st.rerun()
else:
    st.info("🚀 引擎初始化中，正在进行多路径路径拨测...")
    time.sleep(3)
    st.rerun()