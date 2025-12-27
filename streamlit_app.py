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

# 禁用 HTTPS 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===========================
# 1. 基础配置
# ===========================
st.set_page_config(page_title="Cloudflare 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
CONFIG_FILE = "app_config.json"     

QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]
COUNTRY_CN = {"CN": "中国", "HK": "香港", "TW": "台湾", "US": "美国", "JP": "日本", "SG": "新加坡", "KR": "韩国", "CA": "加拿大"}

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
# 2. 进化引擎：阶梯优先级 (解决慢的问题)
# ===========================

def background_evolution():
    db_data = safe_read_json(DB_FILE, {})
    last_full_scan = 0
    
    while True:
        try:
            now = time.time()
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
            is_full = (now - last_full_scan >= 300)
            
            # 整合目标
            targets = [{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS]
            history = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:40]
            targets += [{"ip": i['ip'], "src": "📂 历史"} for i in history]
            targets += [{"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_read_json(CRAWLER_FILE, [])]

            current_results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
                def test_task(t):
                    ip = t['ip']
                    # 1. 极速延迟测试 (优先级 1)
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.3)
                        t1 = time.perf_counter(); s.connect((ip, int(cfg['port']))); s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                    except: return None 

                    # 2. 测速与路径 (优先级 2)
                    p_status, speed = "✅ 正常", 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"https://{ip}/__down?bytes=100000", headers={"Host": cfg['host']}, timeout=0.8, verify=False)
                        speed = round((len(r.content)/1024/1024) / (time.perf_counter() - st_t), 2)
                    except: pass
                    
                    # 3. 位置 (优先级 3)
                    geo = "未知"
                    try:
                        g = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=0.5).json()
                        geo = COUNTRY_CN.get(g.get("countryCode"), "海外")
                    except: pass

                    score = round(100 - p_avg/5 + min(speed*5, 30), 1)
                    return {"score": score, "ip": ip, "status": p_status, "geo": geo, "avg": p_avg, "speed": speed, "src": t['src'], "time": datetime.now().strftime("%H:%M:%S")}

                futs = [ex.submit(test_task, i) for i in {v['ip']:v for v in targets}.values()]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: 
                        current_results.append(res)
                        # 实时保存，防止中断
                        sorted_res = sorted(current_results, key=lambda x: x['score'], reverse=True)
                        safe_write_json(RESULT_FILE, {
                            "last_run": datetime.now().strftime("%H:%M:%S"),
                            "winner": sorted_res[0],
                            "table": sorted_res,
                            "is_full": is_full,
                            "mode": cfg['mode']
                        })
            if is_full: last_full_scan = now
        except: pass
        time.sleep(5)

if "evo_engine" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.evo_engine = True

# ===========================
# 3. 前端 UI (修复 10 行与 KeyError)
# ===========================

with st.sidebar:
    st.header("🛠️ 配置控制台")
    cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443, "uuid": "", "ws_path": "/"})
    new_mode = st.radio("模式", ["☀️ 正常使用排位", "🤖 GPT 专线", "🎬 流媒体"], index=0)
    new_uuid = st.text_input("UUID", cfg.get("uuid", ""))
    new_host = st.text_input("Host", cfg.get("host", "speed.cloudflare.com"))
    if st.button("💾 保存配置"):
        cfg.update({"mode": new_mode, "uuid": new_uuid, "host": new_host})
        safe_write_json(CONFIG_FILE, cfg)
        st.rerun()

data = safe_read_json(RESULT_FILE, None)

if data and "table" in data:
    st.title("🧬 Cloudflare 猎手：进化引擎")
    w = data.get("winner", {})
    
    # 顶部指标
    st.success(f"🏆 当前最优: `{w.get('ip', '扫描中')}` | 评分: {w.get('score', 0)}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("延迟 ms", w.get('avg', 0))
    c2.metric("速度 MB/s", w.get('speed', 0))
    c3.metric("爬虫状态", "📡 活跃中")
    c4.metric("策略", data.get("mode", "☀️").split(" ")[0])

    st.divider()
    
    # 强制 10 行展示
    st.subheader("📊 基因库精英排行 (前 10 名)")
    raw_list = data.get("table", [])
    
    # 构造展示数据，确保即便不足 10 条也不崩
    df = pd.DataFrame(raw_list).head(10)
    
    if not df.empty:
        df_show = df[['score', 'ip', 'geo', 'avg', 'speed', 'src', 'time']].copy()
        df_show.columns = ['评分', 'IP 地址', '位置', '延迟ms', '速度MBs', '来源', '更新时间']
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    
    # 安全读取 Caption 避免 KeyError
    last_run = data.get("last_run", "N/A")
    history_count = len(raw_list)
    st.caption(f"🔄 引擎运行中 | 历史 IP 总数: {history_count} | 更新于: {last_run}")
    
    time.sleep(5); st.rerun()
else:
    st.info("🚀 正在同步爬虫池并启动扫描... 请稍候")
    time.sleep(3); st.rerun()
