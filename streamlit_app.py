import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime

# ==========================================
# 1. 配置中心 (请务必检查这里引号内的内容)
# ==========================================
CF_CONFIG = {
    # 请确保引号内没有多余的空格
    "api_token": "92os9FwyeG7jQDYpD6Rb0Cxrqu5YjtUjGfY1xKBm", 
    "zone_id": "7aa1c1ddfd9df2690a969d9f977f82ae",
    "record_name": "speed.milet.qzz.io", # 必须与 CF 后台的完整域名一致
}

# 待监测的 VLESS 链接库
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.136.0:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@188.114.97.1:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@141.101.120.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#%E7%BE%8E%E5%9B%BD70",
]

# ==========================================
# 2. 自动化管理逻辑
# ==========================================
class AutoOptimizer:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        # 核心修复：强制清理不可见字符
        self.token = str(config.get("api_token", "")).strip()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self.best_ip = "等待测速..."
        self.last_update = "尚未运行"
        self.status_log = []

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append(f"[{timestamp}] {message}")
        if len(self.status_log) > 12: self.status_log.pop(0)

    def update_cf_dns(self, ip):
        """自动化 DNS 获取与更新"""
        base_url = "https://api.cloudflare.com/client/v4"
        try:
            self.log("🛰️ 正在联络 Cloudflare...")
            # 1. 自动寻找 Record ID
            list_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}"
            res = requests.get(list_url, headers=self.headers, timeout=10).json()
            
            if not res.get("success"):
                err = res.get('errors', [{}])[0].get('message', '未知错误')
                self.log(f"❌ CF 拒绝请求: {err}")
                return False

            if not res.get("result"):
                self.log(f"❌ 错误: 未找到域名 {self.config['record_name']} 的记录")
                return False
            
            record = res["result"][0]
            if record["content"] == ip:
                self.log(f"✅ CF 已经是最佳 IP ({ip})，无需操作")
                return True

            # 2. 执行更新
            self.log(f"🛠️ 准备更新 IP: {record['content']} -> {ip}")
            update_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records/{record['id']}"
            payload = {"type": "A", "name": self.config['record_name'], "content": ip, "ttl": 60, "proxied": False}
            put_res = requests.put(update_url, headers=self.headers, json=payload, timeout=10).json()
            
            if put_res.get("success"):
                self.log("🚀 同步成功！Cloudflare 已更新。")
                return True
            else:
                self.log(f"❌ 更新指令失败: {put_res['errors'][0]['message']}")
                return False
        except Exception as e:
            self.log(f"⚠️ 网络通信故障: {str(e)}")
            return False

    def run_forever(self):
        while True:
            self.log("🔄 开启新一轮巡检...")
            ips = []
            for link in self.links:
                try:
                    p = urllib.parse.urlparse(link)
                    ips.append(p.netloc.split('@')[-1].split(':')[0])
                except: continue
            
            results = []
            for ip in set(ips):
                try:
                    start = time.time()
                    # 测速
                    requests.get(f"https://{ip}", timeout=1.5, verify=False)
                    results.append((ip, int((time.time() - start) * 1000)))
                except: continue
            
            if results:
                results.sort(key=lambda x: x[1])
                top_ip = results[0][0]
                self.log(f"🏆 锁定最优: {top_ip} ({results[0]
