import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# 1. 配置中心 - 从 Secrets 读取加密数据
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except:
    st.error("❌ 未检测到 Secrets 配置，请在 Streamlit 后台设置。")
    st.stop()

# 2. 节点素材库
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@173.245.58.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG1",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.61.1:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG2",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@108.162.192.5:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#AP",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.46.10:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG3",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@172.64.36.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#SG4"
]

class VideoMaster:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        self.headers = {"Authorization": f"Bearer {config['api_token']}", "Content-Type": "application/json"}
        self.best_ip = "188.114.97.1"
        self.current_speed = 0.0
        self.last_update = "初始化中"
        self.status_log = []

    def log(self, message, type="info"):
        t = datetime.now().strftime("%H:%M:%S")
        self.status_log.append({"time": t, "msg": message, "type": type})
        if len(self.status_log) > 15: self.status_log.pop(0)

    def test_single_ip(self, ip):
        try:
            start_l = time.time()
            requests.get(f"https://{ip}", timeout=1.5, verify=False)
            latency = int((time.time() - start_l) * 1000)
            start_d = time.time()
            r = requests.get(f"https://{ip}/__down?bytes=1500000", timeout=3.0, verify=False)
            speed = round((1.5 / (time.time() - start_d)) * 8, 2)
            return {"ip": ip, "latency": latency, "speed": speed}
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
            self.log("🎬 开启云端 4K 视频专项巡检...", "info")
            ips = list(set([urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in self.links]))
            results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                for res in executor.map(self.test_single_ip, ips):
                    if res: results.append(res)
            if results:
                results.sort(key=lambda x: (-x['speed'], x['latency']))
                top = results[0]
                status = self.update_cf(top['ip'])
                if status == "success": self.log(f"🚀 已同步最优IP: {top['ip']}", "success")
                else: self.log(f"✅ 当前已是最佳: {top['ip']}", "info")
                self.best_ip, self.current_speed, self.last_update = top['ip'], top['speed'], datetime.now().strftime("%H:%M:%S")
            time.sleep(600)

st.title("🎥 4K 视频优选云端版")
if 'master' not in st.session_state:
    st.session_state.master = VideoMaster(CF_CONFIG, VLESS_LINKS)
    threading.Thread(target=st.session_state.master.run_loop, daemon=True).start()

vm = st.session_state.master
c1, c2, c3 = st.columns(3)
c1.metric("最优 IP", vm.best_ip)
c2.metric("实测带宽", f"{vm.current_speed} Mbps")
c3.metric("最后同步", vm.last_update)
st.divider()
for e in reversed(vm.status_log):
    m = f"[{e['time']}] {e['msg']}"
    st.success(m) if e['type'] == "success" else st.code(m)
time.sleep(10)
st.rerun()