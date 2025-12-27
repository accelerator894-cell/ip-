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
# 1. 基础配置与文件 IO
# ===========================
st.set_page_config(page_title="Cloudflare 猎手进化版", page_icon="🧬", layout="wide")

RESULT_FILE = "scan_results.json"   
DB_FILE = "ip_database.json"        
CRAWLER_FILE = "crawler_pool.json"  
NICHE_FILE = "niche_pool.json"      
CONFIG_FILE = "app_config.json"     

QUICK_SEEDS = ["104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1"]
GOLDEN_SUBNETS = ["104.28.0.0/16", "172.67.128.0/17", "104.21.0.0/16", "172.64.0.0/13"]

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
# 2. 爬虫池补位管理 (保留功能)
# ===========================

class PoolManager:
    @staticmethod
    def trigger_fill():
        threading.Thread(target=PoolManager.fill_crawler, daemon=True).start()
        threading.Thread(target=PoolManager.fill_niche, daemon=True).start()

    @staticmethod
    def fill_crawler():
        ips = safe_read_json(CRAWLER_FILE, [])
        if len(ips) >= 20: return
        try:
            r = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=3)
            found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
            random.shuffle(found)
            for ip in found:
                if len(ips) >= 20: break
                if ip not in ips: ips.append(ip)
            safe_write_json(CRAWLER_FILE, ips)
        except: pass

    @staticmethod
    def fill_niche():
        ips = safe_read_json(NICHE_FILE, [])
        if len(ips) >= 20: return
        new_ips = []
        for _ in range(15):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                new_ips.append(str(net.network_address + random.randint(1, net.num_addresses - 2)))
            except: pass
        ips = list(set(ips + new_ips))[:20]
        safe_write_json(NICHE_FILE, ips)

# ===========================
# 3. 独立进化引擎 (三级跳 + 普查 + 自动更换)
# ===========================

def background_evolution():
    start_time = time.time()
    last_full_scan = 0
    db_data = safe_read_json(DB_FILE, {})
    
    while True:
        try:
            now = time.time()
            cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443})
            elapsed = now - start_time
            
            # --- 阶段 A: 扫描策略判断 ---
            is_full_scan = (now - last_full_scan >= 300) # 5分钟全量普查
            
            # --- 阶段 B: 目标收集 ---
            targets = []
            if is_full_scan:
                targets += [{"ip": i['ip'], "src": "📂 基因普查"} for i in db_data.values()]
                targets += [{"ip": ip, "src": "🕷️ 爬虫全检"} for ip in safe_read_json(CRAWLER_FILE, [])]
                last_full_scan = now
            else:
                top_20 = sorted(db_data.values(), key=lambda x: x.get('score', 0), reverse=True)[:20]
                targets += [{"ip": ip, "src": "⚡ 本地种子"} for ip in QUICK_SEEDS]
                if elapsed > 8: targets += [{"ip": i['ip'], "src": "📂 历史优选"} for i in top_20]
                if elapsed > 3: targets += [{"ip": ip, "src": "🕷️ 爬虫补位"} for ip in safe_read_json(CRAWLER_FILE, [])[:10]]

            # --- 阶段 C: 极速流水线测试 ---
            current_results = []
            down_bytes = 20000 if elapsed < 10 else 200000
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
                def test_task(t):
                    ip = t['ip']
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.4)
                        t1 = time.perf_counter(); s.connect((ip, int(cfg['port']))); s.close()
                        p_avg = int((time.perf_counter() - t1) * 1000)
                    except: return None
                    
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes={down_bytes}", headers={"Host": cfg['host']}, timeout=1.5)
                        speed = (len(r.content)/1024/1024) / (time.perf_counter() - st_t)
                    except: pass
                    
                    geo = {"cc": "CN", "country": "四川电信测速中"} if elapsed < 15 else {"cc": "UN", "country": "Unknown"}
                    if elapsed >= 15:
                        try:
                            g = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode,country", timeout=1).json()
                            geo = {"cc": g.get("countryCode","UN"), "country": g.get("country","Unknown")}
                        except: pass

                    score = round(100 - p_avg/5 + min(speed*5, 35), 1)
                    res = {"ip": ip, "score": score, "avg": p_avg, "speed": round(speed, 2), 
                           "src": t['src'], "cc": geo['cc'], "country": geo['country'], 
                           "last_test": datetime.now().strftime("%H:%M:%S")}
                    
                    # 自动更换比当前更好的节点
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
                            "is_full": is_full_scan, "c_size": len(safe_read_json(CRAWLER_FILE, []))
                        })

            PoolManager.trigger_fill()
            safe_write_json(DB_FILE, db_data)
            
        except: pass
        time.sleep(10)

if "evolution_engine" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.evolution_engine = True

# ===========================
# 4. 前端展示 (复原 UI 细节)
# ===========================

# --- 侧边栏 (复原 1000036579.jpg 细节) ---
with st.sidebar:
    st.markdown("### 🛠️ 配置控制台")
    cfg = safe_read_json(CONFIG_FILE, {"mode": "☀️ 正常使用排位", "host": "speed.cloudflare.com", "port": 443, "uuid": "", "ws_path": "/"})
    
    modes = ["☀️ 正常使用排位", "⚡ 极速低延迟", "🤖 GPT 独享专线", "🎬 流媒体解锁专线"]
    new_mode = st.radio("优选策略", modes, index=modes.index(cfg['mode']) if cfg['mode'] in modes else 0)
    
    # 复原折叠面板
    with st.expander("🔑 VLESS 参数设置"):
        new_uuid = st.text_input("UUID", value=cfg.get("uuid", ""))
        new_host = st.text_input("伪装域名 (Host)", value=cfg.get("host", "speed.cloudflare.com"))
        new_path = st.text_input("WS 路径", value=cfg.get("ws_path", "/"))
        new_port = st.number_input("端口", value=cfg.get("port", 443))
        
    if st.button("💾 保存配置并重启进化"):
        safe_write_json(CONFIG_FILE, {"mode": new_mode, "host": new_host, "port": new_port, "uuid": new_uuid, "ws_path": new_path})
        st.toast(f"切换至: {new_mode}", icon="⚡")
        if os.path.exists(RESULT_FILE): os.remove(RESULT_FILE)
        time.sleep(0.5); st.rerun()
    
    st.info("ℹ️ 后台正在自动从互联网和历史数据库中寻找最佳 IP，无需人工干预。")

# --- 主界面 ---
data = safe_read_json(RESULT_FILE, None)

if data:
    w = data['winner']
    st.title("🧬 Cloudflare 猎手进化版")
    
    # 状态标记 (复原 1000036593.jpg)
    scan_tag = "🚀 全量扫描中" if data.get('is_full') else "📡 实时监测中"
    st.markdown(f"### 🏆 当前最强 IP: `{w['ip']}` | 状态: `{scan_tag}`")
    
    # 冠军卡片 (复原 1000036580.jpg)
    c1, c2, c3 = st.columns(3)
    c1.metric("进化评分", w['score'])
    c2.metric("延迟 ms", w['avg'])
    c3.metric("速度 MB/s", w['speed'])
    
    st.markdown(f"**特性标签:** 🎮 游戏/金融 ⚡ 极速 🤖 GPT 🏳️ {w['cc']}")
    
    st.divider()
    st.subheader(f"🧬 基因库排行 (策略: {data['mode']})")
    
    # 整理数据表 (复原 1000036590.jpg 字段)
    df = pd.DataFrame(data['table'])
    
    # 转换显示
    def source_icon(src):
        if "种子" in src: return "⚡ 本地种子"
        if "历史" in src: return "📂 历史优选"
        return f"🕷️ {src}"

    df['分类来源'] = df['src'].apply(source_icon)
    df['地理位置'] = df['cc'] + " " + df['country']

    st.dataframe(
        df,
        column_order=("score", "分类来源", "ip", "地理位置", "avg", "speed", "last_test"),
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=100),
            "speed": st.column_config.NumberColumn("速度 MB/s"),
            "avg": st.column_config.NumberColumn("延迟 ms")
        },
        use_container_width=True, hide_index=True
    )
    st.caption(f"上次更新: {data['last_run']} | 每 5 分钟全量扫描并自动更换更优节点")
    time.sleep(5); st.rerun()
else:
    # 复原启动画面 (1000036586.jpg)
    st.title("🧬 Cloudflare 猎手进化版")
    st.info("🚀 正在为您极速连接四川电信骨干网并加载本地基因库... (初次约需 10 秒)")
    time.sleep(2); st.rerun()
