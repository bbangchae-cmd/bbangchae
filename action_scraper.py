Python
import time
import random
import requests
import json
import os
from datetime import datetime

# GitHub Secrets에서 안전하게 가져오는 디스코드 주소
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
DATA_FILE = "tracking_items.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

def send_discord_message(text):
    if not DISCORD_WEBHOOK_URL: return
    try: requests.post(DISCORD_WEBHOOK_URL, json={"content": text})
    except: pass

def get_musinsa_price(goods_no):
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://www.musinsa.com/"
    })
    try:
        url = f"https://goods-detail.musinsa.com/goods/{goods_no}"
        res = session.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get("data", {})
            benefit = data.get("maxBenefitPrice") or data.get("benefitPrice") or {}
            price_info = data.get("price", {})
            return benefit.get("price", price_info.get("salePrice", 0))
    except Exception as e:
        print(f"[{goods_no}] 조회 실패: {e}")
    return None

def main():
    if not os.path.exists(DATA_FILE): return
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if not data.get("is_tracking", False):
        print("추적이 꺼져있습니다.")
        return

    items = data.get("items", [])
    target_items = [i for i in items if i.get("is_tracking")]
    updated = False

    for idx, item in enumerate(target_items):
        cur_price = get_musinsa_price(str(item["id"]))
        if cur_price:
            item["final_price"] = cur_price
            tgt_price = item["target_price"]
            
            if cur_price <= tgt_price:
                item["reached"] = True
                if not item.get("notified", False):
                    item["notified"] = True
                    msg = f"🎯 **[무신사 추적 완료]**\n• 상품명: {item['title']}\n• 현재가: **{cur_price:,}원** (희망가: {tgt_price:,}원)\n{item['url']}"
                    send_discord_message(msg)
            else:
                item["reached"] = False
                item["notified"] = False
            updated = True
            
        # 스크래퍼 운영 팁: 봇 차단 방지를 위한 랜덤 딜레이 (3~6초)
        if idx < len(target_items) - 1:
            time.sleep(random.uniform(3.1, 6.2))

    # 변경 내용 저장
    if updated:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()