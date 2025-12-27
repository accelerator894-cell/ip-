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
    "SG": "新加坡", "KR": "韩国", "DE": "德国", "GB": "英国", "FR": "法国",
    "CA": "加拿大", "AU": "澳大利亚", "NL": "荷兰", "RU": "俄罗斯", "IN": "印度"
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
# 2. 后台进化引擎 (增强多路径逻辑)
# ===========================

def background_evolution():
    last_full_scan = 0
    db_data = safe_read_json(DB_FILE, {})
    
    while True:
        try:
            now = time.time()
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
            is_full_scan = (now - last_full_scan >= 300) 
            
            # 目标收集
            targets = []
            if is_full_scan:
                targets += [{"ip": i['ip'], "src": "📂 基因普查"} for i in db_data.values()]
                last_full_scan = now
            else:
                top_ips = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:30]
                targets += [{"ip": ip, "src": "⚡ 本地种子"} for ip in QUICK_SEEDS]
                targets += [{"ip": i['ip'], "src": "📂 历史优选"} for i in top_ips]
                targets += [{"ip": ip, "src": "🕷️ 爬虫发现"} for ip in safe_read_json(CRAWLER_FILE, [])]

            current_results = []
            down_bytes = 200000 if is_full_scan else 50000
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
                def test_task(t):
                    ip = t['ip']
                    # 1. TCP 延迟
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.4)
                        t1 = time.perf_counter(); s.connect((ip, int(cfg['port']))); s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                    except: return None
                    
                    # 2. 多路径测试 (优先执行)
                    path_status, path_weight = "✅ 连接正常", 0
                    if "🤖 GPT" in cfg['mode']:
                        try:
                            r = requests.head(f"https://{ip}", headers={"Host": "chatgpt.com"}, timeout=1.0, verify=False)
                            if r.status_code != 403: path_status, path_weight = "🤖 GPT 绿色", 25
                            else: path_status = "🚫 GPT 屏蔽"
                        except: path_status = "❌ 路径断开"
                    elif "🎬 流媒体" in cfg['mode']:
                        try:
                            r = requests.head(f"https://{ip}", headers={"Host": "www.netflix.com"}, timeout=1.0, verify=False)
                            if r.status_code < 500: path_status, path_weight = "🎬 流媒体解锁", 20
                            else: path_status = "⚠️ 访问受限"
                        except: path_status = "❌ 路径断开"

                    # 3. 测速
                    speed = 0.0
                    if p_avg < 500:
                        try:
                            st_t = time.perf_counter()
                            r = requests.get(f"https://{ip}/__down?bytes={down_bytes}", headers={"Host": cfg['host']}, timeout=1.5, verify=False)
                            speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                        except: pass
                    
                    # 4. 地理位置
                    geo_cn, cc = "未知", "UN"
                    try:
                        g = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode,country", timeout=1.0).json()
                        cc = g.get("countryCode","UN")
                        geo_cn = COUNTRY_CN.get(cc, g.get("country", "未知"))
                    except: pass

                    score = round(100 - p_avg/5 + min(speed*5, 30) + path_weight, 1)
                    res = {"ip": ip, "score": score, "avg": p_avg, "speed": round(speed, 2), 
                           "src": t['src'], "cc": cc, "country_cn": geo_cn, "status": path_status,
                           "last_test": datetime.now().strftime("%H:%M:%S")}
                    
                    if score >= db_data.get(ip, {}).get('score', 0): db_data[ip] = res
                    return res

                unique_targets = {v['ip']:v for v in targets}.values()
                futs = [ex.submit(test_task, i) for i in unique_targets]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r: 
                        current_results.append(r)
                        temp_sorted = sorted(current_results, key=lambda x: x['score'], reverse=True)
                        safe_write_json(RESULT_FILE, {
                            "last_run": datetime.now().strftime("%H:%M:%S"), 
                            "winner": temp_sorted[0], "table": temp_sorted,
                            "is_full": is_full_scan, "mode": cfg['mode']
                        })
            safe_write_json(DB_FILE, db_data)
        except: pass
        time.sleep(10)

if "evolution_engine" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.evolution_engine = True

# ===========================
# 3. 前端界面 (完全复原 + Top 10)
# ===========================

with st.sidebar:
    st.markdown("### 🛠️ 配置控制台")
    cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443, "uuid": "", "ws_path": "/"})
    m_list = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    new_mode = st.radio("优选策略", m_list, index=m_list.index(cfg['mode']) if cfg['mode'] in m_list else 0)
    
    with st.expander("🔑 VLESS 参数设置", expanded=True): # 恢复参数面板
        new_uuid = st.text_input("UUID", value=cfg.get("uuid", ""))
        new_host = st.text_input("伪装域名 (Host)", value=cfg.get("host", "speed.cloudflare.com"))
        new_path = st.text_input("WS 路径", value=cfg.get("ws_path", "/"))
        new_port = st.number_input("端口", value=cfg.get("port", 443))
        
    if st.button("💾 保存配置并重启进化"):
        safe_write_json(CONFIG_FILE, {"mode": new_mode, "host": new_host, "port": new_port, "uuid": new_uuid, "ws_path": new_path})
        st.toast(f"切换至: {new_mode}", icon="⚡")
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(0.5); st.rerun()

data = safe_read_json(RESULT_FILE, None)

if data:
    w = data['winner']
    st.title("🧬 Cloudflare 猎手进化版")
    
    # 顶部冠军卡片
    scan_tag = "实时监测中" if not data.get('is_full') else "全量普查中"
    st.markdown(f"### 🏆 冠军 IP: `{w['ip']}` | 状态: 🛰️ `{scan_tag}`")
    
    st.code(w['ip'], language="text") # 恢复点击复制功能
    st.caption("👆 点击上方代码框即可快速复制冠军 IP")
    
    st.markdown(f"📍 **当前位置:** {w.get('cc', 'UN')} - {w.get('country_cn', '未知')} | **路径探测:** {w.get('status', '未知')}")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("进化评分", w['score'])
    c2.metric("延迟 ms", w['avg'])
    c3.metric("速度 MB/s", w['speed'])
    c4.metric("策略加权", "ON" if "✅" not in w.get('status','') else "OFF")
    
    st.divider()
    
    # 基因库排行展示 (固定前 10 位)
    st.subheader(f"🧬 基因库精英排行 (Top 10 | 策略: {data.get('mode', '默认')})")
    
    df = pd.DataFrame(data['table']).head(10)
    df['来源'] = df['src']
    df['国家'] = df['country_cn']
    df['路径状态'] = df['status']

    st.dataframe(
        df,
        column_order=("score", "路径状态", "ip", "国家", "avg", "speed", "来源", "last_test"),
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=130),
            "avg": st.column_config.NumberColumn("延迟 ms"),
            "speed": st.column_config.NumberColumn("速度 MB/s"),
        },
        use_container_width=True, hide_index=True
    )
    st.caption(f"上次更新: {data['last_run']} | 数据已整合 | 每 5 分钟全量扫描并自动更换更优节点")
    time.sleep(5); st.rerun()
else:
    st.title("🧬 Cloudflare 猎手进化版")
    st.info("🚀 正在为您加载本地基因库并启动多路径拨测逻辑... (约需 10 秒)")
    time.sleep(2); st.rerun()
