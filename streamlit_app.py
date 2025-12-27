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
# 2. 进化引擎核心 (集成爬虫与多路径)
# ===========================

def background_evolution():
    last_full_scan = 0
    db_data = safe_read_json(DB_FILE, {})
    
    while True:
        try:
            now = time.time()
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
            is_full = (now - last_full_scan >= 300) 
            
            # 整合扫描目标：种子 + 历史Top30 + 爬虫池
            targets = []
            targets += [{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS]
            history_ips = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:30]
            targets += [{"ip": i['ip'], "src": "📂 历史"} for i in history_ips]
            targets += [{"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_read_json(CRAWLER_FILE, [])]

            current_results = []
            down_bytes = 100000 if not is_full else 50000
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
                def test_task(t):
                    ip = t['ip']
                    try:
                        # 1. 延迟测试
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.4)
                        t1 = time.perf_counter(); s.connect((ip, int(cfg['port']))); s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                        
                        # 2. 多路径探测
                        p_status, p_weight = "✅ 连接正常", 0
                        if "🤖 GPT" in cfg['mode']:
                            r = requests.head(f"https://{ip}", headers={"Host": "chatgpt.com"}, timeout=0.8, verify=False)
                            p_status, p_weight = ("🤖 GPT 绿色", 25) if r.status_code != 403 else ("🚫 GPT 屏蔽", 0)
                        
                        # 3. 测速测试
                        st_t = time.perf_counter()
                        r = requests.get(f"https://{ip}/__down?bytes={down_bytes}", headers={"Host": cfg['host']}, timeout=1.2, verify=False)
                        speed = round((len(r.content)/1024/1024) / (time.perf_counter() - st_t), 2)
                        
                        # 4. 地理位置
                        g = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=0.8).json()
                        geo = COUNTRY_CN.get(g.get("countryCode"), "海外区域")

                        score = round(100 - p_avg/5 + min(speed*5, 30) + p_weight, 1)
                        return {"score": score, "ip": ip, "status": p_status, "geo": geo, "avg": p_avg, "speed": speed, "src": t['src'], "time": datetime.now().strftime("%H:%M:%S")}
                    except: return None

                unique_targets = {v['ip']:v for v in targets}.values()
                futs = [ex.submit(test_task, i) for i in unique_targets]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result(); 
                    if r: 
                        current_results.append(r)
                        temp_sorted = sorted(current_results, key=lambda x: x['score'], reverse=True)
                        safe_write_json(RESULT_FILE, {"winner": temp_sorted[0], "table": temp_sorted, "is_full": is_full, "mode": cfg['mode']})
            
            if is_full: last_full_scan = now
            safe_write_json(DB_FILE, db_data)
        except: pass
        time.sleep(10)

if "evolution_engine" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.evolution_engine = True

# ===========================
# 3. 前端 UI (固定 10 行展示)
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

if data:
    w = data['winner']
    st.title("🧬 Cloudflare 猎手：进化引擎")
    
    # 顶部状态卡片
    st.success(f"🏆 当前最优节点: `{w['ip']}` | 评分: {w['score']} | 状态: ✅ 基础连接")
    
    # 指标行
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("延迟 ms", w['avg'])
    c2.metric("速度 MB/s", w['speed'])
    c3.metric("爬虫状态", "📡 运行中")
    c4.metric("位置", w['geo'])
    
    st.divider()
    
    # 核心：10 行数据展示
    st.subheader(f"📊 基因库精英排行 (Top 10)")
    df = pd.DataFrame(data['table']).head(10) # 强制截取前 10 行
    
    # 重命名列名以匹配你的截图习惯
    df_show = df[['score', 'ip', 'status', 'geo', 'avg', 'speed', 'time']].copy()
    df_show.columns = ['综合评分', 'IP 地址', '路径状态', '位置', '延迟 ms', '速度 MB/s', '最后更新']

    st.dataframe(
        df_show,
        column_config={
            "综合评分": st.column_config.ProgressColumn("评分", min_value=0, max_value=120),
        },
        use_container_width=True,
        hide_index=True
    )
    
    st.caption(f"🔄 引擎运行中 | 策略: {data.get('mode')} | 更新于: {datetime.now().strftime('%H:%M:%S')}")
    time.sleep(5); st.rerun()
else:
    st.info("🚀 正在同步爬虫池并启动进化扫描...")
    time.sleep(2); st.rerun()
