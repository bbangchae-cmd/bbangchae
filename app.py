import cloudscraper
import requests
from bs4 import BeautifulSoup
import re
import os

# 1. 설정값
WORKER_URL = "https://musinsa-tracker.bbangchae.workers.dev"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

def scrape_musinsa(goods_id):
    # 봇 차단 우회
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    url = f"https://www.musinsa.com/app/goods/{goods_id}"
    
    try:
        response = scraper.get(url)
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        
        # 이미지와 상품명, 브랜드 추출
        og_img = soup.find('meta', property='og:image')
        image = og_img['content'] if og_img else "https://image.msscdn.net/images/no_image.png"
        if image.startswith('//'): image = "https:" + image
            
        og_title = soup.find('meta', property='og:title')
        title = og_title['content'].split('|')[0].strip() if og_title else f"무신사 상품 ({goods_id})"
        brand = title.split(')')[0] + ')' if ')' in title else "무신사"
        
        # 가격 추출
        norm_match = re.search(r'"normalPrice"\s*:\s*(\d+)', html)
        sale_match = re.search(r'"salePrice"\s*:\s*(\d+)', html)
        
        origin_price = int(norm_match.group(1)) if norm_match else 0
        current_price = int(sale_match.group(1)) if sale_match else 0
        
        if origin_price == 0 and current_price == 0:
            return None
            
        return {
            "title": title,
            "brand": brand,
            "image": image,
            "origin_price": origin_price,
            "current_price": current_price
        }
    except Exception as e:
        print(f"[오류] {goods_id} 스크래핑 실패: {e}")
        return None

def main():
    print("🔍 클라우드플레어 워커에서 추적 목록을 가져옵니다...")
    try:
        res = requests.get(f"{WORKER_URL}/api/items")
        data = res.json()
    except Exception as e:
        print("목록을 불러올 수 없습니다.", e)
        return

    items = data.get("items", [])
    is_tracking_global = data.get("is_tracking_global", True)
    updated = False
    
    if is_tracking_global:
        for item in items:
            if not item.get("is_tracking", True):
                continue
                
            print(f"[{item['id']}] 상세 정보 및 가격 확인 중...")
            info = scrape_musinsa(item["id"])
            
            if info and info["current_price"] > 0:
                print(f" - 갱신 성공: {info['title']} / {info['current_price']:,}원")
                
                # 워커에 저장할 데이터 덮어쓰기
                item["title"] = info["title"]
                item["brand"] = info["brand"]
                item["image"] = info["image"]
                item["origin_price"] = info["origin_price"]
                item["final_price"] = info["current_price"]
                
                if info["origin_price"] > info["current_price"]:
                    item["grade_discount"] = info["origin_price"] - info["current_price"]
                
                # 디스코드 알림 로직
                if item["final_price"] <= item["target_price"]:
                    item["reached"] = True
                    if not item.get("discord_notified"):
                        if DISCORD_WEBHOOK:
                            msg = f"🎯 **[무신사 목표가 달성!]**\n• 상품명: {item['title']}\n• 현재가: **{item['final_price']:,}원** (희망가: {item['target_price']:,}원)\n{item['url']}"
                            requests.post(DISCORD_WEBHOOK, json={"content": msg})
                        item["discord_notified"] = True
                else:
                    item["reached"] = False
                    item["discord_notified"] = False
                
                updated = True

    # 🚀 파이썬이 찾은 진짜 데이터를 클라우드플레어 대시보드로 다시 쏴주기
    if updated:
        print("🚀 워커 대시보드로 최신 데이터 동기화 중...")
        data["items"] = items
        sync_res = requests.post(f"{WORKER_URL}/api/sync", json=data)
        if sync_res.status_code == 200:
            print("✅ 대시보드 화면 업데이트 완벽하게 성공!")

if __name__ == "__main__":
    main()
