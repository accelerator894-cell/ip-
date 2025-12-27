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
# 2. 进化引擎：严格优先级顺序
# ===========================

def background_evolution():
    last_full_scan = 0
    db_data = safe_read_json(DB_FILE, {})
    
    while True:
        try:
            now = time.time()
            # 实时读取配置
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
            is_full = (now - last_full_scan >= 300) 
            
            # 整合扫描目标
            targets = [{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS]
            history = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:30]
            targets += [{"ip": i['ip'], "src": "📂 历史"} for i in history]
            targets += [{"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_read_json(CRAWLER_FILE, [])]

            current_results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
                def test_task(t):
                    ip = t['ip']
                    # --- [顺序 1] TCP 握手：不通则直接断开 ---
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.3)
                        t1 = time.perf_counter(); s.connect((ip, int(cfg['port']))); s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                    except: return None 

                    # --- [顺序 2] 路径拨测 ---
                    p_status, p_weight = "✅ 连接正常", 0
                    if "🤖 GPT" in cfg['mode']:
                        try:
                            r = requests.head(f"https://{ip}", headers={"Host": "chatgpt.com"}, timeout=0.6, verify=False)
                            p_status, p_weight = ("🤖 GPT 绿色", 30) if r.status_code != 403 else ("🚫 GPT 屏蔽", 0)
                        except: p_status = "❌ 路径不通"

                    # --- [顺序 3] 测速：仅对通畅节点 ---
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"https://{ip}/__down?bytes=100000", headers={"Host": cfg['host']}, timeout=1.0, verify=False)
                        speed = round((len(r.content)/1024/1024) / (time.perf_counter() - st_t), 2)
                    except: pass

                    # --- [顺序 4] 位置查询 ---
                    geo = "未知"
                    try:
                        g = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=0.5).json()
                        geo = COUNTRY_CN.get(g.get("countryCode"), "海外区域")
                    except: pass

                    score = round(100 - p_avg/5 + min(speed*5, 30) + p_weight, 1)
                    return {"score": score, "ip": ip, "status": p_status, "geo": geo, "avg": p_avg, "speed": speed, "src": t['src'], "time": datetime.now().strftime("%H:%M:%S")}

                unique_targets = {v['ip']:v for v in targets}.values()
                futs = [ex.submit(test_task, i) for i in unique_targets]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    if res: 
                        current_results.append(res)
                        # 核心修复：确保写入文件时格式绝对正确
                        sorted_res = sorted(current_results, key=lambda x: x['score'], reverse=True)
                        safe_write_json(RESULT_FILE, {
                            "last_run": datetime.now().strftime("%H:%M:%S"),
                            "winner": sorted_res[0],
                            "table": sorted_res, # 这里存储完整列表，前端截取
                            "is_full": is_full,
                            "mode": cfg['mode']
                        })
            
            if is_full: last_full_scan = now
        except: pass
        time.sleep(5)

# 初始化后台线程
if "evo_engine" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.evo_engine = True

# ===========================
# 3. 前端 UI (修复 KeyError)
# ===========================

with st.sidebar:
    st.markdown("### 🛠️ 配置控制台")
    cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443, "uuid": "", "ws_path": "/"})
    m_list = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    new_mode = st.radio("优选策略", m_list, index=m_list.index(cfg['mode']) if cfg['mode'] in m_list else 0)
    
    with st.expander("🔑 VLESS 参数设置", expanded=True):
        new_uuid = st.text_input("UUID", value=cfg.get("uuid", ""))
        new_host = st.text_input("伪装域名 (Host)", value=cfg.get("host", "speed.cloudflare.com"))
        new_path = st.text_input("WS 路径", value=cfg.get("ws_path", "/"))
        new_port = st.number_input("端口", value=cfg.get("port", 443))
        
    if st.button("💾 保存配置"):
        safe_write_json(CONFIG_FILE, {"mode": new_mode, "host": new_host, "port": new_port, "uuid": new_uuid, "ws_path": new_path})
        st.rerun()

data = safe_read_json(RESULT_FILE, None)

if data and "winner" in data:
    w = data['winner']
    st.title("🧬 Cloudflare 猎手：进化引擎")
    
    # 状态横条
    status_icon = "🔥 进行中" if data.get("is_full") else "✅ 实时监测"
    st.success(f"🏆 当前最优节点: `{w['ip']}` | 评分: {w['score']} | 状态: {status_icon}")
    
    # 顶部指标 (保留爬虫状态)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("延迟 ms", f"{w['avg']}")
    c2.metric("速度 MB/s", f"{w['speed']}")
    c3.metric("爬虫状态", "📡 活跃中")
    c4.metric("策略", data.get("mode", "默认").split(" ")[0])
    
    st.divider()
    
    # 强制 10 行排行
    st.subheader("📊 基因库精英排行 (前 10 名)")
    raw_table = data.get("table", [])
    if raw_table:
        df = pd.DataFrame(raw_table).head(10)
        # 确保列名显示整齐
        df_show = df[['score', 'ip', 'status', 'geo', 'avg', 'speed', 'src', 'time']].copy()
        df_show.columns = ['评分', 'IP 地址', '路径状态', '位置', '延迟ms', '速度MBs', '来源', '更新时间']

        st.dataframe(
            df_show,
            column_config={"评分": st.column_config.ProgressColumn("综合评分", min_value=0, max_value=125, format="%.1f")},
            use_container_width=True, hide_index=True
        )
    
    # 底部说明 (安全读取，防止 KeyError)
    count = len(raw_table)
    st.caption(f"🔄 引擎运行中 | 历史 IP 总数: {count} | 策略: {data.get('mode')} | 更新于: {data.get('last_run')}")
    time.sleep(5); st.rerun()
else:
    st.title("🧬 Cloudflare 猎手进化版")
    st.info("🚀 正在同步爬虫池并启动阶梯式进化扫描... 请稍候")
    time.sleep(2); st.rerun()
