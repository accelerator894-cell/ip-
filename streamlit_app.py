import streamlit as st
import requests
import json
import time

# ==========================================
# 1. 配置中心 (建议实际使用时通过 st.secrets 或环境变量读取)
# ==========================================
CF_CONFIG = {
    "email": "your_email@example.com",
    "api_token": "你的_Cloudflare_API_Token",
    "zone_id": "你的_Zone_ID",
    "record_name": "nodes.yourdomain.com" # 你要优选到的域名
}

# ==========================================
# 2. API 逻辑抽离 (Cloudflare 管理类)
# ==========================================
class CFManager:
    def __init__(self, config):
        self.config = config
        self.headers = {
            "Authorization": f"Bearer {config['api_token']}",
            "Content-Type": "application/json"
        }
        self.base_url = "https://api.cloudflare.com/client/v4"

    def get_record_info(self):
        """获取 DNS 记录的 ID 和当前内容"""
        url = f"{self.base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}"
        try:
            resp = requests.get(url, headers=self.headers).json()
            if resp.get("success") and len(resp["result"]) > 0:
                return resp["result"][0] # 返回第一个匹配的记录
            return None
        except Exception as e:
            st.error(f"获取 DNS 信息失败: {e}")
            return None

    def update_dns(self, record_id, new_ip):
        """执行 DNS 更新"""
        url = f"{self.base_url}/zones/{self.config['zone_id']}/dns_records/{record_id}"
        data = {
            "type": "A",
            "name": self.config['record_name'],
            "content": new_ip,
            "ttl": 60,
            "proxied": False # 优选通常不开启小云朵
        }
        try:
            resp = requests.put(url, headers=self.headers, json=data).json()
            return resp.get("success")
        except Exception as e:
            st.error(f"更新失败: {e}")
            return False

# ==========================================
# 3. Streamlit UI 界面
# ==========================================
def main():
    st.set_page_config(page_title="CF 节点自动优选器", page_icon="⚡")
    st.title("🚀 CF 节点自动优选系统")
    
    # 初始化 API 经理
    cf = CFManager(CF_CONFIG)

    # 侧边栏：状态显示
    st.sidebar.header("配置状态")
    st.sidebar.info(f"目标域名: \n`{CF_CONFIG['record_name']}`")

    # 主界面布局
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔍 扫描当前最优 IP"):
            with st.status("正在测速优选...", expanded=True) as status:
                st.write("正在连接测试服务器...")
                time.sleep(1) # 模拟测速耗时
                
                # 这里假设你已经有了优选逻辑，我们先模拟一个结果
                best_ip = "104.16.123.45" 
                
                st.write(f"找到最优 IP: {best_ip}")
                status.update(label="扫描完成!", state="complete")
                st.session_state['best_ip'] = best_ip

    if 'best_ip' in st.session_state:
        st.success(f"当前推荐 IP: **{st.session_state['best_ip']}**")
        
        with col2:
            if st.button("🛠️ 自动同步到 Cloudflare"):
                record = cf.get_record_info()
                if record:
                    old_ip = record['content']
                    if old_ip == st.session_state['best_ip']:
                        st.warning("CF 记录已是最优，无需更新。")
                    else:
                        success = cf.update_dns(record['id'], st.session_state['best_ip'])
                        if success:
                            st.balloons()
                            st.success(f"同步成功！已从 {old_ip} 更新至 {st.session_state['best_ip']}")
                        else:
                            st.error("同步失败，请检查 API Token 权限。")
                else:
                    st.error("未找到对应的 DNS 记录，请先在 CF 后台手动创建该 A 记录。")

    # 底部展示
    st.divider()
    st.caption("编码助手提供支持 | 保持高效，保持简洁")

if __name__ == "__main__":
    main()