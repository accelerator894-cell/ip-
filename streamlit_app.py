import streamlit as st
import requests

# 填入你从 CF 获取的信息
CF_API_TOKEN = "R4LIwzWqfuJ8JSN4vTRYEPKLPJxruc-wPwf2EWlD"
ZONE_ID = "cb8ef9355c4081b04c3fbc0d65370f95"  # 在域名概述页右下角找到
RECORD_ID = "efc4c37be906c8a19a67808e51762c1f" # 需要通过 API 查询或查看网页源代码获取

def update_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records/{RECORD_ID}"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    # 构建更新数据包
    data = {
        "type": "A",
        "name": "speed", # 对应你图片 13 中的名称
        "content": new_ip,
        "ttl": 120,      # 设置为 2 分钟，让加速生效更快
        "proxied": False # 必须是灰色云，否则优选无效
    }
    
    response = requests.put(url, headers=headers, json=data)
    if response.status_code == 200:
        st.success(f"✅ 自动优选成功！已将解析更新为: {new_ip}")
    else:
        st.error(f"❌ 更新失败: {response.text}")

# 在网页上增加一个按钮
if st.button("发现最快 IP，立即同步到云端"):
    update_dns(best_ip_found_by_script)