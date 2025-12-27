import json
import random
import ipaddress
from pathlib import Path
import requests
import re

BASE_DIR = Path(__file__).parent
CRAWLER_FILE = BASE_DIR / "crawler_pool.json"
NICHE_FILE = BASE_DIR / "niche_pool.json"

GOLDEN_SUBNETS = [
    "104.16.0.0/12", "104.28.0.0/16", "104.21.0.0/16",
    "172.64.0.0/13", "172.67.0.0/16", "162.158.0.0/15",
    "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
]

def fill_crawler():
    try:
        r = requests.get("https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt", timeout=15)
        ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        random.shuffle(ips)
        ips = list(set(ips))[:60]
        with open(CRAWLER_FILE, "w", encoding="utf-8") as f:
            json.dump(ips, f, ensure_ascii=False, indent=2)
        print(f"爬虫池填充: {len(ips)} 个")
    except Exception as e:
        print("爬虫失败:", e)

def fill_niche():
    ips = []
    for _ in range(600):
        try:
            net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
            candidate = str(net.network_address + random.randint(1, net.num_addresses - 3))
            ips.append(candidate)
        except:
            continue
    ips = list(set(ips))[:60]
    with open(NICHE_FILE, "w", encoding="utf-8") as f:
        json.dump(ips, f, ensure_ascii=False, indent=2)
    print(f"冷门池填充: {len(ips)} 个")

fill_crawler()
fill_niche()