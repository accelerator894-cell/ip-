import streamlit as st
import requests
import time
import re
import random
import os
import json
import pandas as pd
import concurrent.futures
import socket
import threading
import ipaddress
from datetime import datetime
import urllib3
import logging
from pathlib import Path
from collections import defaultdict
import base64
from urllib.parse import quote

# --- 基础配置 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-5s | %(message)s',
                    handlers=[logging.FileHandler("cf_hunter.log", encoding='utf-8')])
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
FILES = {
    "results": BASE_DIR / "scan_results.json",
    "database": BASE_DIR / "ip_database.json",
    "crawlers": BASE_DIR / "crawler_pool.json",
    "niches": BASE_DIR / "niche_pool.json",
    "config": BASE_DIR / "app_config.json",
    "blacklist": BASE_DIR / "blacklist.json",
    "fail_count": BASE_DIR / "fail_count.json"
}

# 默认配置（请在 UI 界面修改 UUID 等信息）
DEFAULT_CONFIG = {
    "mode": "☀️ 正常使用排位",
    "host": "example.workers.dev", # 修改为你的 Workers 域名
    "port": 443,
    "uuid": "00000000-0000-0000-0000-000000000000", # 你的 VLESS UUID
    "ws_path": "/?ed=2560", # 你的 WS 路径
    "max_workers": 60,
    "connect_timeout": 1.0,
    "download_timeout": 4.0,
    "geo_cache_hours": 6,
    "test_bytes_by_mode": {
        "☀️ 正常使用排位": 200_000,
        "⚡ 极速低延迟": 80_000,
        "🤖 GPT 独享专线": 150_000,
        "🎬 流媒体解锁专线": 400_000,
    }
}

GOLDEN_SUBNETS = [
    "104.16.0.0/12", "104.28.0.0/16", "104.21.0.0/16",
    "172.64.0.0/13", "172.67.0.0/16", "162.158.0.0/15",
    "173.245.48.0/20", "188.114.96.0/20", "190.93.240.0/20",
]

QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1",
    "104.18.20.126", "172.64.155.1", "104.16.123.96", "172.67.69.1"
]

COUNTRY_MAP = {
    "US": "美国", "SG": "新加坡", "HK": "香港", "JP": "日本", "KR": "韩国",
    "TW": "台湾", "DE": "德国", "GB": "英国", "FR": "法国", "NL": "荷兰",
    "CA": "加拿大", "AU": "澳大利亚", "CN": "中国", "RU": "俄罗斯"
}

# --- 工具函数 ---

def safe_json(file_path: Path, default=None):
    if not file_path.exists(): return default or {}
    try:
        return json.loads(file_path.read_text(encoding='utf-8'))
    except: return default or {}

def safe_write_json(file_path: Path, data):
    try:
        tmp = file_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(file_path)
    except Exception as e:
        logger.error(f"写入失败 {file_path}: {e}")

def get_geo_info(ip: str):
    # 简化的地理位置获取（逻辑同原版）
    try:
        r = requests.get(f"http://{ip}/cdn-cgi/trace", timeout=2.0)
        if "colo=" in r.text:
            colo = r.text.split('colo=')[1].split('\n')[0]
            return {"cc": "CF", "country": f"节点: {colo}"}
    except: pass
    return {"cc": "??", "country": "未知地区"}

# --- 核心引擎 ---

class IPPoolManager:
    @staticmethod
    def get_blacklist(): return set(safe_json(FILES["blacklist"], []))

    @staticmethod
    def add_to_blacklist(ip: str):
        bl = IPPoolManager.get_blacklist()
        bl.add(ip)
        safe_write_json(FILES["blacklist"], list(bl))

    @staticmethod
    def fill_pools():
        # 合并填充逻辑
        crawler_ips = []
        sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", "https://api.chaoming.cc/cfip"]
        for url in sources:
            try:
                r = requests.get(url, timeout=5)
                crawler_ips.extend(re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text))
            except: pass
        safe_write_json(FILES["crawlers"], list(set(crawler_ips[:100])))
        
        niche_ips = []
        for _ in range(50):
            net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
            niche_ips.append(str(net.network_address + random.randint(1, net.num_addresses - 2)))
        safe_write_json(FILES["niches"], niche_ips)

def evolution_engine():
    db = safe_json(FILES["database"])
    fail_counts = defaultdict(int, safe_json(FILES["fail_count"]))

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG)
            is_full = (time.time() % 300) < 15
            
            # 更新池
            IPPoolManager.fill_pools()

            # 筛选任务
            targets = [{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS]
            if is_full:
                targets.extend([{"ip": ip, "src": "📂 库"} for ip in db])
            else:
                targets.extend([{"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(FILES["crawlers"])])
                targets.extend([{"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"])])

            blacklist = IPPoolManager.get_blacklist()
            unique_tasks = {t["ip"]: t for t in targets if t["ip"] not in blacklist}.values()
            
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.get("max_workers", 60)) as executor:
                def test_unit(task):
                    ip = task["ip"]
                    try:
                        # 1. TCP 延迟
                        start = time.perf_counter()
                        with socket.create_connection((ip, cfg["port"]), timeout=cfg["connect_timeout"]):
                            tcp_ms = (time.perf_counter() - start) * 1000
                        
                        # 2. 速度测试
                        bytes_target = cfg["test_bytes_by_mode"].get(cfg["mode"], 200000)
                        speed = 0.0
                        st = time.perf_counter()
                        r = requests.get(f"http://{ip}/__down?bytes={bytes_target}", 
                                         headers={"Host": cfg["host"]}, timeout=cfg["download_timeout"])
                        elapsed = time.perf_counter() - st
                        speed = len(r.content) / elapsed / 1024 / 1024 if elapsed > 0 else 0
                        
                        geo = get_geo_info(ip)
                        score = round(100 - tcp_ms / 4 + min(speed * 8, 40), 1)
                        
                        res = {"ip": ip, "score": score, "avg": tcp_ms, "speed": speed, 
                               "src": task["src"], "cc": geo["cc"], "country": geo["country"], 
                               "last_test": datetime.now().strftime("%H:%M")}
                        db[ip] = res
                        return res
                    except:
                        fail_counts[ip] += 1
                        if fail_counts[ip] > 5: IPPoolManager.add_to_blacklist(ip)
                        return None

                futures = [executor.submit(test_unit, t) for t in list(unique_tasks)[:300]]
                for f in concurrent.futures.as_completed(futures):
                    r = f.result()
                    if r: results.append(r)

            if results:
                sorted_res = sorted(results, key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "winner": sorted_res[0],
                    "table": sorted_res,
                    "mode": cfg["mode"]
                })
            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail_count"], dict(fail_counts))
            
        except Exception as e:
            logger.error(f"Engine Error: {e}")
        time.sleep(10)

# --- Streamlit UI ---

st.set_page_config(page_title="CF 猎手 - 进化版", page_icon="🧬", layout="wide")

if "started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.started = True

# 读取配置
current_cfg = safe_json(FILES["config"], DEFAULT_CONFIG)

with st.sidebar:
    st.header("⚙️ 核心配置")
    with st.form("config_form"):
        mode = st.selectbox("优选策略", list(DEFAULT_CONFIG["test_bytes_by_mode"].keys()), 
                            index=list(DEFAULT_CONFIG["test_bytes_by_mode"].keys()).index(current_cfg.get("mode", "☀️ 正常使用排位")))
        v_uuid = st.text_input("VLESS UUID", value=current_cfg.get("uuid", ""))
        v_host = st.text_input("伪装域名 (Host)", value=current_cfg.get("host", ""))
        v_path = st.text_input("WS 路径", value=current_cfg.get("ws_path", "/"))
        v_port = st.number_input("端口", value=current_cfg.get("port", 443))
        
        submitted = st.form_submit_button("保存并应用配置")
        if submitted:
            current_cfg.update({"mode": mode, "uuid": v_uuid, "host": v_host, "ws_path": v_path, "port": v_port})
            safe_write_json(FILES["config"], current_cfg)
            st.success("配置已更新，下轮扫描生效！")

    st.divider()
    if st.button("🗑️ 清空黑名单"):
        safe_write_json(FILES["blacklist"], [])
        st.toast("黑名单已重置")

# 主界面显示
data = safe_json(FILES["results"])

if not data or "winner" not in data:
    st.title("🧬 Cloudflare 猎手")
    st.warning("正在进行首轮扫描，请等待约 30 秒...")
    st.progress(0.5)
    time.sleep(5)
    st.rerun()
else:
    winner = data["winner"]
    st.title("🧬 Cloudflare 猎手 · 进化版")
    
    # 订阅信息展示
    with st.container():
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown(f"### 🏆 最优节点: `{winner['ip']}`")
            # 生成 VLESS 链接
            vless_link = f"vless://{current_cfg['uuid']}@{winner['ip']}:{current_cfg['port']}?encryption=none&security=tls&sni={current_cfg['host']}&type=ws&host={current_cfg['host']}&path={quote(current_cfg['ws_path'])}#CF-Hunter-{winner['ip']}"
            st.code(vless_link, language="text")
        with c2:
            st.metric("实时下载", f"{winner['speed']:.2f} MB/s", f"{winner['score']} pts")
            st.metric("网络延迟", f"{winner['avg']:.1f} ms")

    st.divider()
    
    # 数据表格
    st.subheader(f"📊 实时排行榜 (模式: {data['mode']})")
    df = pd.DataFrame(data["table"])
    st.dataframe(
        df[["score", "ip", "avg", "speed", "country", "src", "last_test"]],
        column_config={
            "score": st.column_config.ProgressColumn("综合评分", min_value=0, max_value=120),
            "speed": "下载速度 (MB/s)",
            "avg": "延迟 (ms)",
            "ip": "IP 地址",
            "country": "物理位置",
            "src": "来源"
        },
        use_container_width=True,
        hide_index=True
    )
    
    st.caption(f"最后同步时间: {data['last_run']} | 自动刷新中...")
    time.sleep(8)
    st.rerun()