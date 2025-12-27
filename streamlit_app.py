import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime

# ==========================================
# 1. 核心类逻辑 (增加下载测速功能)
# ==========================================
class VideoOptimizer:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        self.token = str(config.get("api_token", "")).strip()
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        self.best_ip = "188.114.97.1"
        self.current_speed = "0 MB/s"
        self.last_update = "尚未运行"
        self.status_log = []

    def log(self, message, type="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append({"time": timestamp, "msg": message, "type": type})
        if len(self.status_log) > 12: self.status_log.pop(0)

    def test_download_speed(self, ip):
        """
        核心优化：测试实际下载速度
        通过下载 Cloudflare 官方的小文件来评估带宽
        """
        test_url = f"https://{ip}/cdn-cgi/trace" # 也可以换成更大的测速文件，如 __down?bytes=5000000
        try:
            start_time = time.time()
            # 模拟下载 1MB 的数据块进行评估
            response = requests.get(f"https://{ip}/__down?bytes=1048576", timeout=3, verify=False)
            duration = time.time() - start_time
            if response.status_code == 200:
                speed_mbps = (1 / duration) * 8  # 换算成 Mbps
                return round(speed_mbps, 2)
        except:
            return 0
        return 0

    def run_forever(self):
        while True:
            self.log("🔄 开启‘视频专项’优选巡检...", "info")
            ips = list(set([urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in self.links if l.startswith("vless")]))
            
            # 1. 快速初筛延迟
            candidates = []
            for ip in ips:
                try:
                    start = time.time()
                    requests.get(f"https://{ip}", timeout=1.0, verify=False)
                    latency = int((time.time() - start) * 1000)
                    candidates.append({"ip": ip, "latency": latency})
                except: continue
            
            # 2. 对延迟表现前 5 的 IP 进行下载测速
            candidates.sort(key=lambda x: x["latency"])
            top_5 = candidates[:5]
            
            best_speed = 0
            winner_ip = self.best_ip

            for item in top_5:
                self.log(f"📥 正在测速: {item['ip']} (延迟 {item['latency']}ms)...", "info")
                speed = self.test_download_speed(item['ip'])
                if speed > best_speed:
                    best_speed = speed
                    winner_ip = item['ip']
            
            self.log(f"🏆 筛选结果: {winner_ip} | 测速: {best_speed} Mbps", "success")

            # 3. 同步到 Cloudflare (逻辑保持不变)
            # ... update_cf_dns 代码 ...
            
            self.best_ip = winner_ip
            self.current_speed = f"{best_speed} Mbps"
            self.last_update = datetime.now().strftime("%H:%M:%S")
            time.sleep(600)
