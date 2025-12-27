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
from queue import Queue

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================
#          日志配置
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    handlers=[
        logging.FileHandler("cf_hunter.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==============================
#          文件路径 & 默认配置
# ==============================
BASE_DIR = Path(__file__).parent
FILES = {
    "results": BASE_DIR / "scan_results.json",
    "database": BASE_DIR / "ip_database.json",
    "crawlers": BASE_DIR / "crawler_pool.json",
    "niches": BASE_DIR / "niche_pool.json",
    "config": BASE_DIR / "app_config.json",
    "blacklist": BASE_DIR / "blacklist.json"
}

DEFAULT_CONFIG = {
    "mode": "☀️ 正常使用排位",
    "host": "speed.cloudflare.com",
    "port": 443,
    "uuid": "",
    "ws_path": "/",
    "max_workers": 40,
    "connect_timeout": 0.5,
    "download_timeout": 2.0,
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

# ==============================
#          基础工具函数
# ==============================
def safe_json(file_path: Path, default=None):
    if not file_path.exists():
        return default or {}
    try:
        return json.loads(file_path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f"读取 {file_path} 失败: {e}")
        return default or {}

def safe_write_json(file_path: Path, data):
    try:
        tmp = file_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(file_path)
    except Exception as e:
        logger.error(f"写入 {file_path} 失败: {e}")

# ==============================
#          IP 池管理
# ==============================
class IPPoolManager:
    @staticmethod
    def get_blacklist() -> set:
        return set(safe_json(FILES["blacklist"], []))

    @staticmethod
    def add_to_blacklist(ip: str):
        bl = IPPoolManager.get_blacklist()
        bl.add(ip)
        safe_write_json(FILES["blacklist"], list(bl))

    @staticmethod
    def fill_crawler_pool(max_size=30):
        current = safe_json(FILES["crawlers"], [])
        if len(current) >= max_size:
            return

        sources = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
            "https://cfip.shodan.uk/",
            "https://api.chaoming.cc/cfip",
        ]

        found = set(current)
        blacklist = IPPoolManager.get_blacklist()

        for url in sources:
            try:
                r = requests.get(url, timeout=5)
                ips = re.findall(r'(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)', r.text)
                for ip in ips:
                    if ip not in blacklist and ip not in found:
                        found.add(ip)
            except Exception as e:
                logger.debug(f"爬取源 {url} 失败: {e}")

        safe_write_json(FILES["crawlers"], list(found)[:max_size])

    @staticmethod
    def fill_niche_pool(max_size=30):
        current = safe_json(FILES["niches"], [])
        if len(current) >= max_size:
            return

        blacklist = IPPoolManager.get_blacklist()
        new_ips = []

        for _ in range(max_size * 4):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                candidate = str(net.network_address + random.randint(1, net.num_addresses - 3))
                if candidate not in blacklist and candidate not in current:
                    new_ips.append(candidate)
            except:
                continue

        combined = list(set(current + new_ips))[:max_size]
        safe_write_json(FILES["niches"], combined)


# ==============================
#          主进化引擎
# ==============================
def evolution_engine():
    db = safe_json(FILES["database"])
    geo_cache = {}  # ip -> (cc, country, expire_time)
    last_full_scan = 0

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
            now = time.time()
            is_full_scan = now - last_full_scan >= 300

            # 收集测试目标
            targets = []
            if is_full_scan:
                last_full_scan = now
                targets.extend({"ip": ip, "src": "📂 全量扫描"} for ip in db)
            else:
                # 固定种子
                targets.extend({"ip": ip, "src": "⚡ 优质种子"} for ip in QUICK_SEEDS)
                # 历史优秀
                top = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)[:40]
                targets.extend({"ip": ip, "src": "🏆 历史优秀"} for ip, _ in top)
                # 爬虫 + 冷门
                targets.extend({"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(FILES["crawlers"], []))
                targets.extend({"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], []))

            # 去重 + 黑名单过滤
            blacklist = IPPoolManager.get_blacklist()
            seen = set()
            unique_targets = []
            for t in targets:
                ip = t["ip"]
                if ip in blacklist or ip in seen:
                    continue
                seen.add(ip)
                unique_targets.append(t)

            random.shuffle(unique_targets)

            # 开始并发测试
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
                def test_ip(task):
                    ip = task["ip"]
                    try:
                        # TCP ping
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.settimeout(cfg["connect_timeout"])
                            t1 = time.perf_counter()
                            s.connect((ip, cfg["port"]))
                            tcp_ms = (time.perf_counter() - t1) * 1000

                        # 下载测速
                        bytes_to_test = cfg["test_bytes_by_mode"].get(cfg["mode"], 200_000)
                        speed = 0.0
                        try:
                            st = time.perf_counter()
                            r = requests.get(
                                f"http://{ip}/__down?bytes={bytes_to_test}",
                                headers={"Host": cfg["host"]},
                                timeout=cfg["download_timeout"],
                                stream=True
                            )
                            downloaded = 0
                            for chunk in r.iter_content(chunk_size=128*1024):
                                downloaded += len(chunk)
                                if time.perf_counter() - st > cfg["download_timeout"]:
                                    break
                            elapsed = time.perf_counter() - st
                            speed = downloaded / elapsed / 1024 / 1024 if elapsed > 0 else 0
                        except:
                            pass

                        # 地理信息（带缓存）
                        cc, country = "??", "未知"
                        cache_key = ip
                        if cache_key in geo_cache and geo_cache[cache_key][2] > now:
                            cc, country, _ = geo_cache[cache_key]
                        else:
                            try:
                                g = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode,country", timeout=1.5).json()
                                if g.get("status") == "success":
                                    cc = g["countryCode"]
                                    country = g["country"]
                                    geo_cache[cache_key] = (cc, country, now + 3600 * cfg["geo_cache_hours"])
                            except:
                                pass

                        score = round(100 - tcp_ms / 4 + min(speed * 6, 50), 1)

                        result = {
                            "ip": ip,
                            "score": score,
                            "avg": round(tcp_ms, 1),
                            "speed": round(speed, 2),
                            "src": task["src"],
                            "cc": cc,
                            "country": country,
                            "last_test": datetime.now().strftime("%H:%M:%S")
                        }

                        # 更新数据库（允许小幅波动也更新）
                        old_score = db.get(ip, {}).get("score", 0)
                        if score >= old_score - 4:
                            db[ip] = result

                        return result

                    except Exception as e:
                        logger.debug(f"IP {ip} 测试失败: {e}")
                        return None

                futures = [executor.submit(test_ip, t) for t in unique_targets[:150]]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res:
                        results.append(res)

            # 保存当前最佳结果给前端
            if results:
                sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "winner": sorted_results[0],
                    "table": sorted_results[:60],
                    "is_full": is_full_scan,
                    "mode": cfg["mode"]
                })

            # 定期补充IP池
            if random.random() < 0.35:
                threading.Thread(target=IPPoolManager.fill_crawler_pool, daemon=True).start()
                threading.Thread(target=IPPoolManager.fill_niche_pool, daemon=True).start()

            safe_write_json(FILES["database"], db)

        except Exception as e:
            logger.error(f"进化引擎循环异常: {e}")

        time.sleep(7)


# 启动引擎
if "engine_started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.engine_started = True


# ==============================
#          Streamlit 前端
# ==============================
st.set_page_config(page_title="Cloudflare 猎手 · 进化版", page_icon="🧬", layout="wide")

with st.sidebar:
    st.title("🛠️ 配置中心")
    cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())

    modes = list(DEFAULT_CONFIG["test_bytes_by_mode"].keys())
    current_mode_idx = modes.index(cfg["mode"]) if cfg["mode"] in modes else 0
    new_mode = st.radio("测试策略", modes, index=current_mode_idx)

    with st.expander("高级设置"):
        host = st.text_input("伪装域名", value=cfg["host"])
        port = st.number_input("端口", 80, 65535, cfg["port"])
        uuid = st.text_input("UUID", value=cfg.get("uuid", ""))
        path = st.text_input("WS路径", value=cfg.get("ws_path", "/"))
        workers = st.slider("最大并发", 10, 100, cfg["max_workers"], step=5)

    if st.button("保存配置并重启", type="primary"):
        new_cfg = cfg.copy()
        new_cfg.update({
            "mode": new_mode,
            "host": host,
            "port": port,
            "uuid": uuid,
            "ws_path": path,
            "max_workers": workers
        })
        safe_write_json(FILES["config"], new_cfg)
        if FILES["results"].exists():
            FILES["results"].unlink()
        st.success("配置已保存，引擎重启中...")
        time.sleep(1)
        st.rerun()

    st.caption("后台自动进化中...")

# 主界面
data = safe_json(FILES["results"])

if not data:
    st.title("🧬 Cloudflare 猎手 · 进化版")
    st.info("引擎启动中... 初次加载大约需要 10~30 秒\n请稍候...")
    time.sleep(4)
    st.rerun()
else:
    winner = data["winner"]
    st.title("🧬 Cloudflare 猎手 · 进化版")

    tag = "🚀 全量扫描中" if data.get("is_full") else "⚡ 实时优化"
    st.markdown(f"### 当前最强节点：`{winner['ip']}`　　{tag}")

    cols = st.columns([2.2, 1, 1, 1.3])
    cols[0].metric("综合评分", f"{winner['score']:.1f}")
    cols[1].metric("延迟", f"{winner['avg']:.1f} ms")
    cols[2].metric("速度", f"{winner['speed']:.2f} MB/s")
    cols[3].metric("地区", f"{winner['cc']} {winner['country']}")

    st.divider()

    st.subheader(f"实时排行榜（当前策略：{data['mode']}）")

    df = pd.DataFrame(data["table"])

    df["来源"] = df["src"].replace({
        "⚡ 优质种子": "⚡ 优质种子",
        "🏆 历史优秀": "🏆 历史优秀",
        "🕷️ 爬虫": "🕷️ 网络爬取",
        "💎 冷门": "💎 珍稀挖掘",
        "📂 全量扫描": "📂 全库扫描"
    })

    df["地区"] = df["cc"] + " " + df["country"]

    st.dataframe(
        df,
        column_order=["score", "来源", "ip", "地区", "avg", "speed", "last_test"],
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=140),
            "avg": st.column_config.NumberColumn("延迟 ms", format="%.1f"),
            "speed": st.column_config.NumberColumn("速度 MB/s", format="%.2f"),
        },
        hide_index=True,
        use_container_width=True
    )

    st.caption(f"最后更新: {data['last_run']}　｜　每5分钟全量扫描一次")

    time.sleep(5)
    st.rerun()