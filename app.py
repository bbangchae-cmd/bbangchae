import cloudscraper
import requests
import json
import re
import os

# 1. 설정값 (본인의 워커 주소와 디스코드 웹훅 입력)
WORKER_URL = "https://musinsa-tracker.bbangchae.workers.dev"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "여기에_디스코드_웹훅_주소_입력")

def scrape_musinsa(goods_id):
    # 🚀 핵심: 일반 requests가 아닌 cloudscraper를 사용하여 봇 차단 완벽 우회
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    url = f"https://www.musinsa.com/app/goods/{goods_id}"
    
    try:
        response = scraper.get(url)
        html = response.text
        
        # 정규식으로 가격 데이터 추출
        norm_match = re.search(r'"normalPrice"\s*:\s*(\d+)', html)
        sale_match = re.search(r'"salePrice"\s*:\s*(\d+)', html)
        
        origin_price = int(norm_match.group(1)) if norm_match else 0
        current_price = int(sale_match.group(1)) if sale_match else 0
        
        if origin_price == 0 and current_price == 0:
            return None # 긁어오기 실패 시 5만원이 아닌 None 반환 (기존 가격 보호)
            
        return current_price
    except Exception as e:
        print(f"[오류] 상품 {goods_id} 스크래핑 실패: {e}")
        return None

def main():
    print("🔍 클라우드플레어 워커에서 추적 목록을 가져옵니다...")
    try:
        # 기존에 만든 클라우드플레어 API에서 데이터 읽어오기
        res = requests.get(f"{WORKER_URL}/api/items")
        data = res.json()
        items = data.get("items", [])
    except Exception as e:
        print("목록을 불러올 수 없습니다.", e)
        return

    for item in items:
        if not item.get("is_tracking"):
            continue

        print(f"[{item['brand']}] {item['title']} 가격 확인 중...")
        current_price = scrape_musinsa(item["id"])
        
        if current_price and current_price > 0:
            print(f" - 현재 정확한 가격: {current_price:,}원 (희망가: {item['target_price']:,}원)")
            
            # 목표가 도달 시 디스코드 알림 발송
            if current_price <= item["target_price"]:
                if not item.get("discord_notified"):
                    msg = f"🎯 **[무신사 목표가 달성!]**\n• 상품명: {item['title']}\n• 현재가: **{current_price:,}원** (희망가: {item['target_price']:,}원)\n{item['url']}"
                    requests.post(DISCORD_WEBHOOK, json={"content": msg})
                    print(" 🚀 디스코드 알림 발송 완료!")

if __name__ == "__main__":
    main()
