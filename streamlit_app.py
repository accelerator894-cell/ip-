import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# 1. 配置中心 (从 Secrets 读取)
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ 未找到 Secrets 配置")
    st.stop()

# 节点素材库
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@173.245.58.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG1",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.61.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG2",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@108.162.192.5:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#AP",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.46.10:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG3",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@172.64.36.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG4"
]

class FlashMaster:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        self.headers = {"Authorization": f"Bearer {config['api_token']}", "Content-Type": "application/json"}
        self.best_ip = "等待同步"
        self.latency = 0
        self.last_update = "初始化"
        self.status_log = []

    def log(self, message, type="info"):
        t = datetime.now().strftime("%H:%M:%S")
        self.status_log.append({"time": t, "msg": message, "type": type})
        if len(self.status_log) > 12: self.status_log.pop(0)

    def fast_ping(self, ip):
        """闪电版逻辑：只测高精度延迟，不拉取大文件"""
        try:
            # 连续测试 3 次取平均，确保结果真实
            latencies = []
            for _ in range(3):
                s = time.time()
                requests.get(f"https://{ip}/cdn-cgi/trace", timeout=1.0, verify=False)
                latencies.append(int((time.time() - s) * 1000))
            avg_lat = sum(latencies) // 3
            return {"ip": ip, "latency": avg_lat}
        except: return None

    def update_cf(self, new_ip):
        base_url = "https://api.cloudflare.com/client/v4"
        try:
            res = requests.get(f"{base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}", headers=self.headers).json()
            if res.get("success") and res.get("result"):
                record = res["result"][0]
                if record["content"] == new_ip: return "skip"
                requests.put(f"{base_url}/zones/{self.config['zone_id']}/dns_records/{record['id']}", headers=self.headers, json={"type": "A", "name": self.config['record_name'], "content": new_ip, "ttl": 60, "proxied": False})
                return "success"
        except: return "error"

    def run_loop(self):
        while True:
            self.log("⚡ 启动闪电版极速优选...", "info")
            ips = list(set([urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in self.links]))
            results = []
            # 并发测速，10秒内出结果
            with ThreadPoolExecutor(max_workers=5) as ex:
                for r in ex.map(self.fast_ping, ips):
                    if r: results.append(r)
            
            if results:
                results.sort(key=lambda x: x['latency'])
                top = results[0]
                status = self.update_cf(top['ip'])
                if status == "success": self.log(f"🚀 闪电同步成功: {top['ip']}", "success")
                else: self.log(f"✅ IP 稳定，当前延迟: {top['latency']}ms", "info")
                self.best_ip, self.latency, self.last_update = top['ip'], top['latency'], datetime.now().strftime("%H:%M:%S")
            
            time.sleep(600) # 每10分钟更新一次

st.title("⚡ 闪电版优选云端系统")
if 'master' not in st.session_state:
    st.session_state.master = FlashMaster(CF_CONFIG, VLESS_LINKS)
    threading.Thread(target=st.session_state.master.run_loop, daemon=True).start()

m = st.session_state.master
c1, c2, c3 = st.columns(3)
c1.metric("最优 IP", m.best_ip)
c2.metric("当前延迟", f"{m.latency} ms")
c3.metric("最后更新", m.last_update)
st.divider()
for e in reversed(m.status_log):
    st.success(f"[{e['time']}] {e['msg']}") if e['type']=="success" else st.code(f"[{e['time']}] {e['msg']}")
time.sleep(10)
st.rerun()
