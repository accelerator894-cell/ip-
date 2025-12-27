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

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================
#          日志配置
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    handlers=[logging.FileHandler("cf_hunter.log", encoding='utf-8')]
)
logger = logging.getLogger(__name__)

# ==============================
#          文件路径 & 配置
# ==============================
BASE_DIR = Path(__file__).parent
FILES = {
    "results": BASE_DIR / "scan_results.json",
    "database": BASE_DIR / "ip_database.json",
    "crawlers": BASE_DIR / "crawler_pool.json",
    "niches": BASE_DIR / "niche_pool.json",
    "config": BASE_DIR / "app_config.json",
    "blacklist": BASE_DIR / "blacklist.json",
    "fail_count": BASE_DIR / "fail_count.json"  # 新增：失败计数
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

# 全局缓存
geo_cache = {}
fail_counts = defaultdict(int)  # ip -> 连续失败次数

# ==============================
#          基础工具
# ==============================
def safe_json(file_path: Path, default=None):
    if not file_path.exists():
        return default or {}
    try:
        return json.loads(file_path.read_text(encoding='utf-8'))
    except:
        return default or {}

def safe_write_json(file_path: Path, data):
    try:
        tmp = file_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(file_path)
    except Exception as e:
        logger.error(f"写入 {file_path} 失败: {e}")

# ==============================
#          多源地理位置查询（最重要改进）
# ==============================
def get_geo_info(ip: str, timeout=1.8) -> dict:
    now = time.time()

    # 缓存命中
    if ip in geo_cache and geo_cache[ip]["expire"] > now:
        return geo_cache[ip]["data"]

    methods = [
        # 优先级最高：ipinfo.io （建议注册免费token）
        {
            "name": "ipinfo",
            "url": f"https://ipinfo.io/{ip}/json",
            "headers": {"User-Agent": "cf-hunter/1.0"},
            # 如果你有token可以加在这里： "Authorization": "Bearer xxxxx"
            "parser": lambda d: {
                "cc": d.get("country", "??"),
                "country": d.get("country", "未知"),
                "city": d.get("city", ""),
                "source": "ipinfo"
            }
        },
        # 第二选择：ipapi.co
        {
            "name": "ipapi.co",
            "url": f"https://ipapi.co/{ip}/json/",
            "parser": lambda d: {
                "cc": d.get("country_code", "??"),
                "country": d.get("country_name", "未知"),
                "city": d.get("city", ""),
                "source": "ipapi.co"
            }
        },
        # 第三：ipwhois.app
        {
            "name": "ipwhois",
            "url": f"https://ipwhois.app/json/{ip}",
            "parser": lambda d: {
                "cc": d.get("country_code", "??"),
                "country": d.get("country", "未知"),
                "city": d.get("city", ""),
                "source": "ipwhois"
            }
        },
        # 保底：Cloudflare trace（只能得到 colo）
        {
            "name": "cf_trace",
            "url": f"http://{ip}/cdn-cgi/trace",
            "parser": lambda text: {
                "cc": "??",
                "country": f"CF数据中心: {text.split('colo=')[1].split('\n')[0] if 'colo=' in text else '未知'}",
                "city": "",
                "source": "cf_trace"
            }
        }
    ]

    for method in methods:
        try:
            r = requests.get(
                method["url"],
                timeout=timeout,
                headers=method.get("headers", {"User-Agent": "cf-hunter/1.0"})
            )
            if r.status_code != 200:
                continue

            if method["name"] == "cf_trace":
                data = method["parser"](r.text)
            else:
                data = method["parser"](r.json())

            geo_cache[ip] = {"data": data, "expire": now + 3600 * DEFAULT_CONFIG["geo_cache_hours"]}
            return data
        except:
            continue

    # 全部失败
    return {"cc": "??", "country": "获取失败", "city": "", "source": "failed"}

# ==============================
#          IP池 & 黑名单管理
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
    def fill_crawler_pool(max_size=35):
        # ... 保持原逻辑，略（与之前版本相同）

    @staticmethod
    def fill_niche_pool(max_size=35):
        # ... 保持原逻辑，略

# ==============================
#          进化引擎（核心）
# ==============================
def evolution_engine():
    db = safe_json(FILES["database"])
    global fail_counts
    fail_counts = defaultdict(int, safe_json(FILES["fail_count"]))

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
            now = time.time()
            is_full_scan = now - time.time() % 300 < 10  # 约5分钟一次全扫

            targets = []
            if is_full_scan:
                targets.extend({"ip": ip, "src": "📂 全量扫描"} for ip in db)
            else:
                targets.extend({"ip": ip, "src": "⚡ 优质种子"} for ip in QUICK_SEEDS)
                top = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)[:50]
                targets.extend({"ip": ip, "src": "🏆 历史优秀"} for ip, _ in top)
                targets.extend({"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(FILES["crawlers"], []))
                targets.extend({"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], []))

            blacklist = IPPoolManager.get_blacklist()
            seen = set()
            unique_targets = [t for t in targets if t["ip"] not in blacklist and t["ip"] not in seen and not seen.add(t["ip"])]

            random.shuffle(unique_targets)

            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_workers"]) as ex:
                def test_ip(task):
                    ip = task["ip"]
                    try:
                        # TCP ping
                        with socket.socket() as s:
                            s.settimeout(cfg["connect_timeout"])
                            t1 = time.perf_counter()
                            s.connect((ip, cfg["port"]))
                            tcp_ms = (time.perf_counter() - t1) * 1000

                        # 下载测速
                        bytes_test = cfg["test_bytes_by_mode"].get(cfg["mode"], 200000)
                        speed = 0.0
                        try:
                            st = time.perf_counter()
                            r = requests.get(
                                f"http://{ip}/__down?bytes={bytes_test}",
                                headers={"Host": cfg["host"]},
                                timeout=cfg["download_timeout"],
                                stream=True
                            )
                            size = 0
                            for chunk in r.iter_content(128*1024):
                                size += len(chunk)
                                if time.perf_counter() - st > cfg["download_timeout"]:
                                    break
                            speed = size / (time.perf_counter() - st) / 1024 / 1024
                        except:
                            pass

                        geo = get_geo_info(ip)

                        score = round(100 - tcp_ms / 4 + min(speed * 6, 50), 1)

                        result = {
                            "ip": ip,
                            "score": score,
                            "avg": round(tcp_ms, 1),
                            "speed": round(speed, 2),
                            "src": task["src"],
                            "cc": geo["cc"],
                            "country": geo["country"],
                            "last_test": datetime.now().strftime("%H:%M:%S")
                        }

                        old = db.get(ip, {})
                        if score >= old.get("score", 0) - 5:
                            db[ip] = result
                            fail_counts[ip] = 0
                        else:
                            fail_counts[ip] += 1
                            if fail_counts[ip] >= 3:
                                IPPoolManager.add_to_blacklist(ip)
                                logger.info(f"IP {ip} 连续失败3次，已加入黑名单")

                        return result

                    except Exception:
                        fail_counts[ip] += 1
                        if fail_counts[ip] >= 3:
                            IPPoolManager.add_to_blacklist(ip)
                        return None

                futures = [ex.submit(test_ip, t) for t in unique_targets[:180]]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res:
                        results.append(res)

            if results:
                sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "winner": sorted_results[0] if sorted_results else None,
                    "table": sorted_results[:80],  # 显示前80条
                    "is_full": is_full_scan,
                    "mode": cfg["mode"]
                })

            # 补充池子
            if random.random() < 0.4:
                threading.Thread(target=IPPoolManager.fill_crawler_pool).start()
                threading.Thread(target=IPPoolManager.fill_niche_pool).start()

            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail_count"], dict(fail_counts))

        except Exception as e:
            logger.error(f"引擎异常: {e}")

        time.sleep(6)

# 启动
if "started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.started = True

# ==============================
#          前端界面
# ==============================
st.set_page_config(page_title="Cloudflare 猎手 · 进化版", page_icon="🧬", layout="wide")

with st.sidebar:
    st.title("配置中心")
    cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())

    modes = list(DEFAULT_CONFIG["test_bytes_by_mode"].keys())
    idx = modes.index(cfg["mode"]) if cfg["mode"] in modes else 0
    new_mode = st.radio("策略", modes, index=idx)

    with st.expander("高级设置"):
        host = st.text_input("Host", cfg["host"])
        port = st.number_input("端口", value=cfg["port"])
        max_workers = st.slider("最大并发", 10, 120, cfg["max_workers"])

    if st.button("保存并重启", type="primary"):
        new_cfg = cfg.copy()
        new_cfg.update({"mode": new_mode, "host": host, "port": port, "max_workers": max_workers})
        safe_write_json(FILES["config"], new_cfg)
        if FILES["results"].exists():
            FILES["results"].unlink()
        st.success("已保存，引擎重启...")
        time.sleep(1.2)
        st.rerun()

# 主界面
data = safe_json(FILES["results"])

if not data or not data.get("winner"):
    st.title("🧬 Cloudflare 猎手 · 进化版")
    st.info("引擎启动中... 预计10~40秒完成首次扫描")
    time.sleep(5)
    st.rerun()
else:
    winner = data["winner"]
    st.title("🧬 Cloudflare 猎手 · 进化版")

    tag = "🚀 全量扫描" if data.get("is_full") else "⚡ 实时优化"
    st.markdown(f"### 当前最强节点：`{winner['ip']}`　　{tag}")

    cols = st.columns([2.5, 1.2, 1.2, 1.5])
    cols[0].metric("综合评分", f"{winner['score']:.1f}")
    cols[1].metric("延迟", f"{winner['avg']:.1f} ms")
    cols[2].metric("速度", f"{winner['speed']:.2f} MB/s")
    cols[3].metric("地区", f"{winner['cc']} {winner['country']}")

    st.divider()

    st.subheader(f"实时排行榜（策略：{data['mode']}） - 前 {len(data['table'])} 名")

    df = pd.DataFrame(data["table"])
    df["来源"] = df["src"]
    df["地区"] = df["cc"] + " " + df["country"]

    st.dataframe(
        df,
        column_order=["score", "来源", "ip", "地区", "avg", "speed", "last_test"],
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=140),
            "avg": st.column_config.NumberColumn("延迟 ms", format="%.1f"),
            "speed": st.column_config.NumberColumn("速度 MB/s", format="%.2f"),
        },
        use_container_width=True,
        hide_index=True
    )

    st.caption(f"最后更新: {data['last_run']}　｜　每5分钟全量扫描一次")

    time.sleep(5)
    st.rerun()