import streamlit as st
import requests
import time
import re
import random
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
from urllib.parse import quote

# --- 基础与安全配置 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
FILES = {
    "results": BASE_DIR / "scan_results.json",
    "database": BASE_DIR / "ip_database.json",
    "config": BASE_DIR / "app_config.json",
    "blacklist": BASE_DIR / "blacklist.json",
    "fail_count": BASE_DIR / "fail_count.json",
    "export_vless": BASE_DIR / "best_node.txt" # 新增：导出文件
}

DEFAULT_CONFIG = {
    "mode": "☀️ 正常使用排位",
    "host": "speed.cloudflare.com",
    "port": 443,
    "uuid": "00000000-0000-0000-0000-000000000000",
    "ws_path": "/?ed=2560",
    "max_workers": 80,
    "connect_timeout": 0.8,
    "download_timeout": 5.0,
    "test_bytes": 250000,
}

GOLDEN_SUBNETS = ["104.16.0.0/12", "172.64.0.0/13", "108.162.192.0/18", "162.158.0.0/15"]

# --- 核心逻辑优化 ---

def safe_json(file_path: Path, default=None):
    try: return json.loads(file_path.read_text(encoding='utf-8')) if file_path.exists() else (default or {})
    except: return default or {}

def safe_write_json(file_path: Path, data):
    tmp = file_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(file_path)

def get_vless_link(ip, cfg):
    """生成标准 VLESS 链接"""
    params = f"encryption=none&security=tls&sni={cfg['host']}&type=ws&host={cfg['host']}&path={quote(cfg['ws_path'])}"
    return f"vless://{cfg['uuid']}@{ip}:{cfg['port']}?{params}#CF-Hunter-{ip}"

class EvolutionEngine:
    @staticmethod
    def get_targets():
        # 混合筛选：固定种子 + 历史库 + 随机扫描
        db = safe_json(FILES["database"])
        blacklist = set(safe_json(FILES["blacklist"], []))
        
        seeds = ["104.16.123.96", "172.67.69.1", "104.18.2.1", "172.64.1.1"]
        historical = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)[:50]
        
        # 随机生成 C 段 IP
        random_ips = []
        for _ in range(100):
            net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
            random_ips.append(str(net.network_address + random.randint(10, net.num_addresses - 10)))
            
        all_ips = list(set(seeds + [ip for ip, _ in historical] + random_ips))
        return [ip for ip in all_ips if ip not in blacklist]

    @staticmethod
    def run():
        fail_counts = defaultdict(int, safe_json(FILES["fail_count"]))
        while True:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG)
            ips = EvolutionEngine.get_targets()
            results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
                def test(ip):
                    try:
                        # 1. 延迟测试
                        start = time.perf_counter()
                        with socket.create_connection((ip, cfg["port"]), timeout=cfg["connect_timeout"]):
                            latency = (time.perf_counter() - start) * 1000
                        
                        # 2. 速度测试 (利用 HTTP Range 请求)
                        st = time.perf_counter()
                        r = requests.get(f"https://{cfg['host']}/__down?bytes={cfg['test_bytes']}", 
                                         headers={"Host": cfg["host"]}, timeout=cfg["download_timeout"], verify=False)
                        speed = len(r.content) / (time.perf_counter() - st) / 1024 / 1024
                        
                        score = round(100 - (latency / 5) + (speed * 10), 1)
                        return {"ip": ip, "score": score, "latency": latency, "speed": speed}
                    except:
                        fail_counts[ip] += 1
                        return None

                futures = [executor.submit(test, ip) for ip in ips]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res: results.append(res)

            if results:
                results.sort(key=lambda x: x["score"], reverse=True)
                winner = results[0]
                # 更新结果与导出链接
                safe_write_json(FILES["results"], {"winner": winner, "table": results, "time": datetime.now().strftime("%H:%M:%S")})
                FILES["export_vless"].write_text(get_vless_link(winner["ip"], cfg))
                
                # 更新黑名单（失败次数过多）
                bl = [ip for ip, count in fail_counts.items() if count > 7]
                safe_write_json(FILES["blacklist"], bl)
            
            time.sleep(15)

# --- Streamlit UI 界面 ---

st.set_page_config(page_title="CF Hunter Pro", layout="wide")

if "init" not in st.session_state:
    threading.Thread(target=EvolutionEngine.run, daemon=True).start()
    st.session_state.init = True

cfg = safe_json(FILES["config"], DEFAULT_CONFIG)

with st.sidebar:
    st.title("🛡️ 系统配置")
    with st.form("config"):
        new_uuid = st.text_input("VLESS UUID", cfg["uuid"])
        new_host = st.text_input("伪装域名", cfg["host"])
        new_path = st.text_input("WS 路径", cfg["ws_path"])
        if st.form_submit_button("保存配置"):
            cfg.update({"uuid": new_uuid, "host": new_host, "ws_path": new_path})
            safe_write_json(FILES["config"], cfg)
            st.rerun()

data = safe_json(FILES["results"])

if data and "winner" in data:
    w = data["winner"]
    st.title("🧬 Cloudflare 猎手 Pro")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("当前最优 IP", w["ip"])
    col2.metric("下载速度", f"{w['speed']:.2f} MB/s")
    col3.metric("TCP 延迟", f"{w['latency']:.1f} ms")
    
    st.subheader("🔗 自动生成的 VLESS 链接")
    st.code(get_vless_link(w["ip"], cfg))
    
    st.divider()
    st.subheader("📊 候选节点排名")
    st.dataframe(pd.DataFrame(data["table"]), use_container_width=True)
else:
    st.info("引擎正在初始化并扫描全球边缘节点...")

time.sleep(10)
st.rerun()
