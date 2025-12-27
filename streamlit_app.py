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
# 1. 基础配置与文件 IO (全量保留)
# ===========================
st.set_page_config(page_title="Cloudflare 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  # 恢复爬虫文件逻辑
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
# 2. 后台引擎 (功能全开版)
# ===========================

def background_evolution():
    last_full_scan = 0
    db_data = safe_read_json(DB_FILE, {})
    
    while True:
        try:
            now = time.time()
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443, "uuid": "", "ws_path": "/"})
            is_full_scan = (now - last_full_scan >= 300) 
            
            # --- 爬虫与种子目标整合 ---
            targets = []
            if is_full_scan:
                targets += [{"ip": i['ip'], "src": "📂 基因普查"} for i in db_data.values()]
                last_full_scan = now
            else:
                top_20 = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:20]
                targets += [{"ip": ip, "src": "⚡ 本地种子"} for ip in QUICK_SEEDS]
                targets += [{"ip": i['ip'], "src": "📂 历史优选"} for i in top_20]
                # 核心：爬虫发现逻辑
                crawler_ips = safe_read_json(CRAWLER_FILE, [])
                targets += [{"ip": ip, "src": "🕷️ 爬虫发现"} for ip in crawler_ips]

            current_results = []
            down_bytes = 200000 if not is_full_scan else 50000 # 动态调整下载量
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
                def test_task(t):
                    ip = t['ip']
                    # 1. TCP 延迟 (优先)
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.4)
                        t1 = time.perf_counter(); s.connect((ip, int(cfg['port']))); s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                    except: return None
                    
                    # 2. 多路径探测 (不冲突执行)
                    p_status, p_weight = "✅ 基础连接", 0
                    if "🤖 GPT" in cfg['mode']:
                        try:
                            r = requests.head(f"https://{ip}", headers={"Host": "chatgpt.com"}, timeout=0.8, verify=False)
                            if r.status_code != 403: p_status, p_weight = "🤖 GPT 绿色", 30
                            else: p_status = "🚫 GPT 屏蔽"
                        except: p_status = "❌ 路径不通"
                    elif "🎬 流媒体" in cfg['mode']:
                        try:
                            r = requests.head(f"https://{ip}", headers={"Host": "www.netflix.com"}, timeout=0.8, verify=False)
                            p_status = "🎬 允许解锁" if r.status_code < 500 else "⚠️ 限制访问"
                            p_weight = 20 if "允许" in p_status else 0
                        except: p_status = "❌ 路径不通"

                    # 3. 测速
                    speed = 0.0
                    if p_avg < 500:
                        try:
                            st_t = time.perf_counter()
                            r = requests.get(f"https://{ip}/__down?bytes={down_bytes}", headers={"Host": cfg['host']}, timeout=1.2, verify=False)
                            speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                        except: pass
                    
                    # 4. 地理位置
                    geo_cn, cc = "未知", "UN"
                    try:
                        g = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=0.8).json()
                        cc = g.get("countryCode","UN")
                        geo_cn = COUNTRY_CN.get(cc, "海外区域")
                    except: pass

                    score = round(100 - p_avg/5 + min(speed*5, 30) + p_weight, 1)
                    res = {"ip": ip, "score": score, "avg": p_avg, "speed": round(speed, 2), 
                           "src": t['src'], "cc": cc, "country_cn": geo_cn, "status": p_status,
                           "uuid": cfg['uuid'], "host": cfg['host'], # 存入配置信息供排行显示
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
# 3. UI 界面 (完整复原 + 10列扩展)
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
        
    if st.button("💾 保存配置并重启进化"):
        safe_write_json(CONFIG_FILE, {"mode": new_mode, "host": new_host, "port": new_port, "uuid": new_uuid, "ws_path": new_path})
        st.toast(f"切换至: {new_mode}", icon="⚡")
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(0.5); st.rerun()

data = safe_read_json(RESULT_FILE, None)

if data:
    w = data['winner']
    st.title("🧬 Cloudflare 猎手进化版")
    
    # 顶部冠军卡片 (复原)
    scan_tag = "实时监测中" if not data.get('is_full') else "全量普查中"
    st.success(f"🏆 当前最优节点: `{w['ip']}` | 评分: {w['score']} | 状态: `{scan_tag}`")
    
    st.code(w['ip'], language="text")
    st.caption("👆 点击快速复制冠军 IP")
    
    # 指标行 (复原四列)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("进化评分", w['score'])
    c2.metric("延迟 ms", w['avg'])
    c3.metric("速度 MB/s", w['speed'])
    c4.metric("位置", w['country_cn'])
    
    st.divider()
    
    # 基因库排行 (扩展至 10 列)
    st.subheader(f"🧬 基因库精英排行 (Top 10 | 策略: {data.get('mode', '默认')})")
    
    df = pd.DataFrame(data['table']).head(10)
    # 整合 UI 要求的 10 列数据
    df_display = df.copy()
    df_display['来源标记'] = df_display['src']
    df_display['国家/区域'] = df_display['country_cn']
    df_display['路径状态'] = df_display['status']

    st.dataframe(
        df_display,
        column_order=("score", "路径状态", "ip", "国家/区域", "avg", "speed", "来源标记", "uuid", "host", "last_test"),
        column_config={
            "score": st.column_config.ProgressColumn("综合评分", min_value=0, max_value=130),
            "ip": "IP 地址",
            "avg": st.column_config.NumberColumn("延迟 (ms)"),
            "speed": st.column_config.NumberColumn("测速 (MB/s)"),
            "uuid": "当前 UUID",
            "host": "伪装域名",
            "last_test": "更新时间"
        },
        use_container_width=True, hide_index=True
    )
    st.caption(f"上次更新: {data['last_run']} | 爬虫引擎: 正常运行 | 每 5 分钟进行一次全量普查")
    time.sleep(5); st.rerun()
else:
    st.title("🧬 Cloudflare 猎手进化版")
    st.info("🚀 引擎初始化中，正在同步爬虫 IP 池并启动进化扫描...")
    time.sleep(3); st.rerun()
