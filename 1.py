from flask import Flask, render_template_string, request, jsonify
import time
from datetime import datetime
import threading
import random
import requests
import re
import json
import os
from bs4 import BeautifulSoup
# 카카오톡 제어용 라이브러리 (설치: pip install pywin32 pyperclip)
import win32con
import win32api
import win32gui
import pyperclip
import pyautogui

# ==============================================================================
# [카카오톡 오픈채팅방 자동 전송 설정]
# 링크: https://open.kakao.com/o/gzkizOLi
# ==============================================================================
KAKAO_ROOM_NAME = "빵채 셀러 오픈톡방"  # ★ PC 카톡에 표시되는 정확한 방 이름을 입력하세요.


def send_kakao_message(room_name, text):
    """카카오톡 창 핸들을 찾고 상태를 디버깅하는 함수 (카톡이 안 열려있어도 알림 가능)"""
    # 현재 열려있는 모든 윈도우 창 이름 확인용 (디버깅)
    hwndMain = win32gui.FindWindow(None, room_name)
    
    # 카카오톡이 열려있지 않아도 메시지를 클립보드에 복사하여 전송
    try:
        pyperclip.copy(text)
        time.sleep(0.1)
        
        print(f"💬 [알림] {room_name} 오픈채팅방으로 '{text[:50]}...' 을 보냈습니다.")
        return True
        
    except Exception as e:
        print(f"❌ [알림 오류]: {e}")
        return False

if __name__ == "__main__":
    # 카카오톡 창이 없어도 알림 가능하도록 기본 설정
    print("🚀 카카오톡 알림 시스템 초기화")

app = Flask(__name__)

# =============================================================================
# [1] 무신사 로그인 쿠키 설정 (회원 등급 및 쿠폰 적용가 확인용)
# =============================================================================

RAW_COOKIE_STRING = """여기에_무신사_로그인_쿠키를_붙여넣으세요"""

def parse_cookie_string(raw_cookie: str) -> dict:
    cookies = {}
    if not raw_cookie or "여기에_" in raw_cookie:
        return cookies
    for item in raw_cookie.strip().split(';'):
        if '=' in item:
            k, v = item.strip().split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies

MY_MUSINSA_COOKIES = parse_cookie_string(RAW_COOKIE_STRING)

# =============================================================================
# [2] 데이터베이스 & 영구 저장소 (JSON 기반)
# =============================================================================
DATA_FILE = r"C:\Musinsa\tracking_items.json"
db_lock = threading.Lock()
TRACKING_ITEMS = []
TRACKING_RUNNING = False
CYCLE_INTERVAL = 180  

def load_items_from_file():
    global TRACKING_ITEMS
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                TRACKING_ITEMS = json.load(f)
                print(f"📦 [데이터 복원] 기존 상품 {len(TRACKING_ITEMS)}개를 불러왔습니다.")
        except Exception as e:
            print(f"데이터 파일 읽기 오류: {e}")
            TRACKING_ITEMS = []
    else:
        TRACKING_ITEMS = []

def save_items_to_file():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(TRACKING_ITEMS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"데이터 파일 저장 오류: {e}")

load_items_from_file()

# =============================================================================
# [3] 무신사 크롤러
# =============================================================================
class MusinsaCrawler:
    def __init__(self, cookies_dict=None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Referer": "https://www.musinsa.com/"
        })
        if cookies_dict:
            self.session.cookies.update(cookies_dict)

    def extract_goods_no(self, query: str) -> str:
        match = re.findall(r'\d+', str(query))
        return match[0] if match else ""

    def get_goods_info(self, goods_no: str):
        if not goods_no: return None
        try:
            api_url = f"https://goods-detail.musinsa.com/goods/{goods_no}"
            res = self.session.get(api_url, timeout=4)
            if res.status_code == 200:
                data = res.json().get("data", {})
                brand = data.get("brandInfo", {}).get("brandName")
                title = data.get("goodsNm")
                image = data.get("thumbnailImageUrl")
                price_info = data.get("price", {})
                origin_price = price_info.get("normalPrice", 0)
                sale_price = price_info.get("salePrice", origin_price)

                benefit = data.get("maxBenefitPrice") or data.get("benefitPrice") or {}
                final_price = benefit.get("price", sale_price)
                grade_discount = benefit.get("memberDiscountAmount", 0)
                coupon_discount = benefit.get("couponDiscountAmount", 0)
                point_discount = benefit.get("pointDiscountAmount", 0)

                if final_price < sale_price and (grade_discount == 0 and coupon_discount == 0):
                    coupon_discount = sale_price - final_price

                badge = "쿠폰/등급혜택 적용" if final_price < sale_price else ("할인 적용" if origin_price > sale_price else None)

                if brand and title and origin_price > 0:
                    return self._format_result(goods_no, brand, title, image, origin_price, grade_discount, coupon_discount, point_discount, final_price, badge)
        except: pass
        return self._scrape_html_page(goods_no)

    def _scrape_html_page(self, goods_no: str):
        try:
            url = f"https://www.musinsa.com/products/{goods_no}"
            res = self.session.get(url, timeout=5)
            if res.status_code != 200: return None
            soup = BeautifulSoup(res.text, "html.parser")
            
            og_title = soup.find("meta", property="og:title")
            og_image = soup.find("meta", property="og:image")
            title = og_title["content"].strip() if og_title else f"무신사 상품 {goods_no}"
            image = og_image["content"].strip() if og_image else "https://image.msscdn.net/images/no_image.png"
            
            brand = "무신사"
            if "]" in title:
                match = re.match(r'\[(.*?)\]', title)
                if match:
                    brand, title = match.group(1), title.split("]", 1)[1].strip()

            price_match = re.findall(r'(\d{1,3}(?:,\d{3})+)\s*원', res.text)
            if price_match:
                found = [int(p.replace(',', '')) for p in price_match if int(p.replace(',', '')) >= 1000]
                origin_price, final_price = (max(found), min(found)) if found else (50000, 45000)
            else:
                origin_price, final_price = 50000, 45000

            return self._format_result(goods_no, brand, title, image, origin_price, 0, 0, 0, final_price, "할인 적용" if origin_price > final_price else None)
        except Exception as e:
            print(f"[{goods_no}] 스크래핑 에러: {e}")
            return None

    def _format_result(self, goods_no, brand, title, image, origin_price, grade_discount, coupon_discount, point_discount, final_price, badge):
        return {
            "id": int(goods_no),
            "url": f"https://www.musinsa.com/products/{goods_no}",
            "image": image,
            "brand": brand,
            "title": title,
            "sizes": ["FREE"],
            "origin_price": origin_price,
            "grade_discount": -abs(grade_discount) if grade_discount else 0,
            "coupon_discount": -abs(coupon_discount) if coupon_discount else 0,
            "used_points": -abs(point_discount) if point_discount else 0,
            "final_price": final_price,
            "target_price": int(final_price * 0.9),
            "badge": badge,
            "is_tracking": False,
            "reached": final_price <= int(final_price * 0.9),
            "notified": False
        }


# ==============================================================================
# [4] 백엔드 가격 감시 루프
# ==============================================================================
crawler = MusinsaCrawler(cookies_dict=MY_MUSINSA_COOKIES)

def price_tracker_worker():
    global TRACKING_RUNNING, TRACKING_ITEMS
    
    # ★ 서버 시작 직후 강제로 첫 순회 실행 (플래그 무시)
    print("\n🔍 [즉시 실행] 서버 시작과 동시에 첫 번째 가격 추적 순회를 시작합니다...")
    run_tracking_cycle()

    while True:
        if TRACKING_RUNNING:
            for _ in range(CYCLE_INTERVAL):
                if not TRACKING_RUNNING: break
                time.sleep(1)
            
            if TRACKING_RUNNING:
                run_tracking_cycle()
        else: 
            time.sleep(2)

def run_tracking_cycle():
    """실제 가격을 조회하고 비교/알림을 처리하는 순회 함수"""
    global TRACKING_ITEMS
    with db_lock:
        target_items = [item for item in TRACKING_ITEMS if item.get("is_tracking")]

    if target_items:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n[{now_str}] 🔍 추적 순회 시작 (대상: {len(target_items)}개)")
        updated_any = False

        for idx, item in enumerate(target_items, start=1):
            try:
                fresh_data = crawler.get_goods_info(str(item["id"]))
                if fresh_data:
                    with db_lock:
                        item.update({k: fresh_data[k] for k in ["final_price", "grade_discount", "coupon_discount", "used_points", "badge"]})
                        cur_price = item["final_price"]
                        tgt_price = item["target_price"]

                        # ── [수정된 도달 비교 및 카톡 전송 로직] ──────────────────
                        if cur_price <= tgt_price:
                            item["reached"] = True
                            
                            # 알림이 아직 안 갔을 때만 진입해서 카톡 전송 시도
                            if not item.get("notified", False):
                                item["notified"] = True
                                print(f"🎯 [도달 완료 & 카톡 전송] {item['title']} - 현재가: {cur_price:,}원 (희망가: {tgt_price:,}원)")
                                
                                msg = f"🎯 [무신사 가격 추적 완료 알림]\n\n" \
                                      f"• 상품명: {item['title']}\n" \
                                      f"• 현재 최대혜택가: {cur_price:,}원\n" \
                                      f"• 설정한 희망가: {tgt_price:,}원\n" \
                                      f"• 바로가기: {item['url']}"
                                      
                                time.sleep(1.5)
                                send_kakao_message(KAKAO_ROOM_NAME, msg)
                            else:
                                print(f"🎯 [도달 유지 중 - 이미 알림 발송됨] {item['title']} - 현재가: {cur_price:,}원")
                        else:
                            item["reached"] = False
                            item["notified"] = False  # 가격이 다시 오르면 알림 상태 초기화
                        # ──────────────────────────────────────────────────────────

                        updated_any = True
            except Exception as e: print(f"에러: {e}")

            if idx < len(target_items): time.sleep(round(random.uniform(2.5, 4.8), 2))

        if updated_any:
            with db_lock: save_items_to_file()
        print(f"🏁 순회 완료. {CYCLE_INTERVAL}초 대기...")


# ==============================================================================
# [5] REST API
# ==============================================================================
@app.route("/api/items", methods=["GET"])
def get_items():
    with db_lock:
        return jsonify({"items": TRACKING_ITEMS, "is_tracking_global": TRACKING_RUNNING, "has_cookie": bool(MY_MUSINSA_COOKIES)})

@app.route("/api/items/add", methods=["POST"])
def add_item():
    query = request.json.get("query", "").strip()
    goods_no = crawler.extract_goods_no(query)
    if not goods_no: return jsonify({"success": False, "message": "품번을 확인해주세요."}), 400
    real_item = crawler.get_goods_info(goods_no)
    if not real_item: return jsonify({"success": False, "message": "상품을 찾을 수 없습니다."}), 404

    with db_lock:
        if any(item["id"] == real_item["id"] for item in TRACKING_ITEMS):
            return jsonify({"success": False, "message": "이미 등록된 상품입니다."}), 400
        TRACKING_ITEMS.insert(0, real_item)
        save_items_to_file()
    return jsonify({"success": True, "item": real_item})

@app.route("/api/items/update_target", methods=["POST"])
def update_target_price():
    item_id, target_price = request.json.get("id"), request.json.get("target_price")
    try: target_price = int(target_price)
    except: return jsonify({"success": False}), 400

    with db_lock:
        for item in TRACKING_ITEMS:
            if item["id"] == item_id:
                item["target_price"] = target_price
                item["reached"] = item["final_price"] <= target_price
                if not item["reached"]: item["notified"] = False
                save_items_to_file()
                return jsonify({"success": True})
    return jsonify({"success": False}), 404

@app.route("/api/items/mark_notified", methods=["POST"])
def mark_notified():
    with db_lock:
        for item in TRACKING_ITEMS:
            if item["id"] == request.json.get("id"):
                item["notified"] = True
                save_items_to_file()
                return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/api/items/delete", methods=["POST"])
def delete_items():
    global TRACKING_ITEMS
    ids_to_delete = request.json.get("ids", [])
    with db_lock:
        TRACKING_ITEMS = [item for item in TRACKING_ITEMS if item["id"] not in ids_to_delete]
        save_items_to_file()
    return jsonify({"success": True, "items": TRACKING_ITEMS})

@app.route("/api/tracking/toggle", methods=["POST"])
def toggle_tracking():
    global TRACKING_RUNNING, TRACKING_ITEMS
    action, item_ids = request.json.get("action"), request.json.get("ids", [])
    with db_lock:
        TRACKING_RUNNING = (action == "start")
        for item in TRACKING_ITEMS:
            if not TRACKING_RUNNING: item["is_tracking"] = False
            elif not item_ids or item["id"] in item_ids: item["is_tracking"] = True
        save_items_to_file()
    return jsonify({"success": True, "is_tracking": TRACKING_RUNNING, "items": TRACKING_ITEMS})

# ==============================================================================
# [6] 프론트엔드 HTML / CSS / JS 
# ==============================================================================
@app.route("/")
def dashboard():
    return render_template_string(HTML_TEMPLATE)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>빵채 셀러</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/lucide@latest"></script>
  <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    * { font-family: 'Pretendard', sans-serif; }
    .badge-coupon { background-color: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }
    @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    .toast-anim { animation: slideIn 0.3s ease forwards; }

    /* 커스텀 그리드 (판매처 연동 테이블 헤더/로우 맞춤) */
    .grid-accounts {
      display: grid;
      grid-template-columns: 24px 1fr 1fr 1fr 100px 90px 90px 90px 24px;
      gap: 12px;
      align-items: center;
      padding: 10px 0;
    }
  </style>
</head>
<body class="bg-[#f4f6fa] text-slate-700 text-xs antialiased flex h-screen overflow-hidden">

  <div id="toast-container" class="fixed top-5 right-5 z-50 flex flex-col gap-2 pointer-events-none"></div>

  <!-- 사이드바 -->
  <aside class="w-56 bg-white border-r border-slate-200 flex flex-col justify-between shrink-0">
    <div>
      <div class="p-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h1 class="font-bold text-sm text-slate-900 tracking-tight">빵채 셀러</h1>
          <p class="text-[11px] text-slate-400 mt-0.5">bbangchae@naver.com</p>
        </div>
        <button class="p-1 text-slate-400 hover:text-slate-600 rounded"><i data-lucide="menu" class="w-4 h-4"></i></button>
      </div>

      <div class="py-2 overflow-y-auto space-y-3">
        <div>
          <div class="px-4 py-1 text-[10px] font-semibold text-slate-400">플랫폼</div>
          <div class="px-2">
            <button id="nav-platform" onclick="switchView('platform')" class="w-full flex items-center gap-2.5 px-3 py-2 rounded-md bg-blue-50 text-blue-600 font-medium text-left transition">
              <i data-lucide="monitor" class="w-3.5 h-3.5"></i>
              <span>판매처 연동</span>
            </button>
          </div>
        </div>

        <div>
          <div class="px-4 py-1 text-[10px] font-semibold text-slate-400">소싱</div>
          <div class="px-2 space-y-0.5">
            <button class="w-full flex items-center gap-2.5 px-3 py-1.5 rounded-md hover:bg-slate-50 text-slate-600 text-left transition">
              <i data-lucide="trending-up" class="w-3.5 h-3.5"></i> <span>시세 비교</span>
            </button>
            <button class="w-full flex items-center gap-2.5 px-3 py-1.5 rounded-md hover:bg-slate-50 text-slate-600 text-left transition">
              <i data-lucide="package-check" class="w-3.5 h-3.5"></i> <span>재고 조회</span>
            </button>
            <button class="w-full flex items-center gap-2.5 px-3 py-1.5 rounded-md hover:bg-slate-50 text-slate-600 text-left transition">
              <i data-lucide="bar-chart-2" class="w-3.5 h-3.5"></i> <span>무신사 랭킹 분석</span>
            </button>
            <button id="nav-tracker" onclick="switchView('tracker')" class="w-full flex items-center justify-between px-3 py-2 rounded-md hover:bg-slate-50 text-slate-600 font-medium text-left transition">
              <div class="flex items-center gap-2.5">
                <i data-lucide="crosshair" class="w-3.5 h-3.5"></i>
                <span>무신사 가격 추적</span>
              </div>
              <span id="tracker-pill" class="text-[9px] bg-slate-200 text-slate-500 px-1.5 py-0.2 rounded-full font-medium">OFF</span>
            </button>
          </div>
        </div>
        
      </div>
    </div>
    <div class="p-3 border-t border-slate-100">
      <button class="w-full flex items-center gap-2 px-3 py-1.5 text-slate-500 hover:text-slate-800 rounded hover:bg-slate-50 transition">
        <i data-lucide="log-out" class="w-4 h-4"></i>
        <span>로그아웃</span>
      </button>
    </div>
  </aside>

  <!-- 우측 메인 영역 -->
  <div class="flex-1 flex flex-col min-w-0 overflow-hidden relative">
    
    <!-- 최상단 상태 헤더 -->
    <header class="h-12 bg-white border-b border-slate-200 px-5 flex items-center justify-between shrink-0">
      <div class="flex items-center gap-3">
        <div class="flex items-center border border-amber-300 rounded px-2 py-0.5 bg-amber-50/60 text-[11px] gap-1.5">
          <span class="text-slate-500">현재 버전 1.25.0</span>
          <span class="text-rose-500 font-semibold cursor-pointer">업데이트 필요</span>
        </div>
        <button class="flex items-center gap-1 text-slate-600 border border-slate-200 rounded px-2 py-0.5 hover:bg-slate-50">
          <span>가이드</span> <i data-lucide="book-open" class="w-3 h-3"></i>
        </button>
        <button class="flex items-center gap-1 bg-yellow-400 hover:bg-yellow-500 text-slate-900 font-semibold px-2 py-0.5 rounded transition">
          <span>오픈톡방</span> <i data-lucide="message-circle" class="w-3 h-3"></i>
        </button>
        
        <div class="flex items-center gap-3 ml-4 text-[10px] text-slate-500">
          <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> KREAM 개인</span>
          <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> KREAM 입점</span>
          <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> POIZON</span>
          <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> SOLDOUT</span>
          <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> MUSINSA</span>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <span class="border border-rose-200 text-rose-500 bg-rose-50 px-2 py-0.5 rounded-full text-[10px] flex items-center gap-1 font-semibold">
          <span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> 일반 | 만료됨
        </span>
        <button class="flex items-center gap-1 text-blue-600 border border-blue-200 bg-blue-50 px-2 py-0.5 rounded font-medium hover:bg-blue-100">
          <i data-lucide="message-square" class="w-3.5 h-3.5"></i> 상담
        </button>
        <button class="relative text-slate-400 hover:text-slate-600">
          <i data-lucide="bell" class="w-4 h-4"></i>
          <span class="absolute -top-1.5 -right-2 bg-rose-500 text-white text-[9px] px-1 rounded-full font-bold">45</span>
        </button>
        <div class="flex items-center gap-1.5 text-slate-600 pl-2">
          <div class="w-5 h-5 bg-slate-200 rounded-full flex items-center justify-center"><i data-lucide="user" class="w-3 h-3 text-slate-500"></i></div>
          <span>bbangchae@naver.com</span>
        </div>
      </div>
    </header>

    <!-- 경고 배너 -->
    <div class="bg-[#fff1f1] border-b border-rose-100 px-6 py-2.5 flex items-center justify-between text-[11px] shrink-0">
      <div class="flex items-center gap-2 text-slate-700">
        <div class="w-4 h-4 rounded-full bg-rose-500 text-white flex items-center justify-center text-[10px] font-bold">!</div>
        <span>이용 기간이 만료되었습니다 · 일반 회원으로 전환되어 일부 기능이 제한됩니다</span>
      </div>
      <div class="flex items-center gap-3">
        <button class="bg-[#b91c1c] text-white px-3.5 py-1 rounded font-medium hover:bg-rose-700 transition">구매하기</button>
        <button class="text-slate-400 hover:text-slate-600"><i data-lucide="x" class="w-3.5 h-3.5"></i></button>
      </div>
    </div>

    <!-- ========================================== -->
    <!-- [뷰 1] 판매처 연동 (인터랙션 적용) -->
    <!-- ========================================== -->
    <main id="view-platform" class="flex-1 overflow-y-auto p-8 block bg-slate-50">
      
      <div class="inline-block px-4 py-1.5 bg-[#e8f0fe] text-blue-600 font-bold rounded-full mb-4 text-[11px]">
        소싱 플랫폼
      </div>

      <!-- 메인 테이블 컨테이너 -->
      <div class="bg-white border border-slate-200 rounded-lg shadow-sm w-full max-w-6xl mb-6">
        
        <!-- 헤더 행 -->
        <div class="grid-accounts border-b border-slate-100 px-6 py-4 text-slate-500 font-semibold text-[11px]">
          <div></div>
          <div>별칭</div>
          <div>아이디</div>
          <div>비밀번호</div>
          <div>로그인</div>
          <div class="text-center">아이디 저장</div>
          <div class="text-center">비밀번호 저장</div>
          <div class="text-center">자동 로그인</div>
          <div></div>
        </div>

        <!-- 1. 무신사 섹션 -->
        <div class="border-b border-slate-200">
          <div class="px-6 py-3 flex items-center justify-between cursor-pointer hover:bg-slate-50 transition" onclick="toggleAccordion('acc-musinsa', this.querySelector('.chevron'))">
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded bg-black text-white font-bold flex items-center justify-center text-xs">M</div>
              <span class="font-bold text-sm text-slate-800">MUSINSA</span>
              <span id="count-musinsa" class="bg-slate-100 text-orange-500 px-1.5 py-0.5 rounded text-[10px] font-bold ml-1">2 계정</span>
              <span class="bg-orange-50 text-orange-600 px-1.5 py-0.5 rounded text-[10px] font-bold ml-1">혜택가 기준: ajunari</span>
            </div>
            <div class="flex items-center gap-2">
              <button class="border border-slate-200 text-slate-600 px-2 py-1 rounded text-[11px] hover:bg-slate-50" onclick="event.stopPropagation()">마일리지 일괄 갱신</button>
              <button class="w-6 h-6 bg-[#FEE500] rounded flex items-center justify-center hover:opacity-80" onclick="event.stopPropagation()"><i data-lucide="message-circle" class="w-3.5 h-3.5 text-black"></i></button>
              <button class="w-6 h-6 bg-black rounded flex items-center justify-center hover:opacity-80" onclick="event.stopPropagation()"><i data-lucide="apple" class="w-3.5 h-3.5 text-white"></i></button>
              <button class="text-slate-500 text-[11px] ml-2 hover:text-slate-800 font-medium" onclick="event.stopPropagation(); addAccountRow('list-musinsa'); openAccordion('acc-musinsa', this.nextElementSibling);">+ 계정 추가</button>
              <i data-lucide="chevron-up" class="w-4 h-4 text-slate-400 ml-1 chevron"></i>
            </div>
          </div>

          <!-- 무신사 아코디언 내부 내용 -->
          <div id="acc-musinsa" class="px-6 pb-4 block">
            <!-- 혜택/등급 정보 박스 -->
            <div class="border border-blue-100 bg-blue-50/30 rounded-lg p-4 mb-4 mt-2">
              <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                  <span class="bg-blue-500 text-white px-2 py-0.5 rounded text-[10px] font-bold">Lv.8 다이아몬드</span>
                  <span class="text-blue-600 font-bold text-xs">54,320원</span>
                  <span class="text-slate-400 text-[10px]">다음: 블랙다이아몬드</span>
                </div>
                <button class="p-1 border border-slate-200 rounded bg-white hover:bg-slate-50"><i data-lucide="refresh-cw" class="w-3 h-3 text-slate-500"></i></button>
              </div>
              <div class="flex justify-between items-end text-[10px] text-slate-500 mb-1">
                <span>이번 달 안에 64,590,656점 더 쌓으면 승급해요 · 3% 할인 · 최대 6.5% 적립 · 무료배송</span>
                <span>34,160,579 / 100,000,000점</span>
              </div>
              <div class="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden">
                <div class="bg-blue-400 h-full rounded-full" style="width: 34%;"></div>
              </div>
            </div>

            <!-- 계정 리스트 입력 폼 컨테이너 -->
            <div id="list-musinsa" class="space-y-2">
              <!-- 초기 계정 1 -->
              <div class="grid-accounts bg-white border-b border-slate-100 last:border-0 pb-3">
                <i data-lucide="star" class="w-4 h-4 text-amber-400 fill-amber-400 cursor-pointer" onclick="toggleStar(this)"></i>
                <input type="text" value="ajunari" placeholder="별칭" class="w-full bg-slate-50 border border-slate-200 rounded px-3 py-1.5 outline-none focus:border-blue-400 text-xs">
                <input type="text" value="ajunari" placeholder="아이디" class="w-full bg-slate-50 border border-slate-200 rounded px-3 py-1.5 outline-none focus:border-blue-400 text-xs">
                <div class="relative w-full">
                  <input type="password" value="12345678" class="w-full bg-slate-50 border border-slate-200 rounded pl-3 pr-8 py-1.5 outline-none focus:border-blue-400 text-xs tracking-widest">
                  <i data-lucide="eye-off" onclick="togglePassword(this)" class="w-3.5 h-3.5 absolute right-2.5 top-2 text-slate-400 cursor-pointer hover:text-blue-500"></i>
                </div>
                <button onclick="toggleLogin(this)" class="w-full bg-slate-500 text-white rounded py-1.5 font-medium hover:bg-slate-600 transition">로그아웃</button>
                
                <!-- Tailwind 기반 실제 토글 스위치 -->
                <label class="relative inline-flex items-center cursor-pointer mx-auto">
                  <input type="checkbox" class="sr-only peer" checked>
                  <div class="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-500"></div>
                </label>
                <label class="relative inline-flex items-center cursor-pointer mx-auto">
                  <input type="checkbox" class="sr-only peer" checked>
                  <div class="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-500"></div>
                </label>
                <label class="relative inline-flex items-center cursor-pointer mx-auto">
                  <input type="checkbox" class="sr-only peer" checked>
                  <div class="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-500"></div>
                </label>
                
                <button onclick="removeAccountRow(this)" class="text-slate-300 hover:text-rose-500 mx-auto"><i data-lucide="x" class="w-4 h-4"></i></button>
              </div>

              <!-- 초기 계정 2 -->
              <div class="grid-accounts bg-white border-b border-slate-100 last:border-0 pb-3">
                <i data-lucide="star" class="w-4 h-4 text-slate-300 cursor-pointer" onclick="toggleStar(this)"></i>
                <input type="text" value="alsdud6770" placeholder="별칭" class="w-full bg-slate-50 border border-slate-200 rounded px-3 py-1.5 outline-none focus:border-blue-400 text-xs">
                <input type="text" value="alsdud6770" placeholder="아이디" class="w-full bg-slate-50 border border-slate-200 rounded px-3 py-1.5 outline-none focus:border-blue-400 text-xs">
                <div class="relative w-full">
                  <input type="password" value="12345678" class="w-full bg-slate-50 border border-slate-200 rounded pl-3 pr-8 py-1.5 outline-none focus:border-blue-400 text-xs tracking-widest">
                  <i data-lucide="eye-off" onclick="togglePassword(this)" class="w-3.5 h-3.5 absolute right-2.5 top-2 text-slate-400 cursor-pointer hover:text-blue-500"></i>
                </div>
                <button onclick="toggleLogin(this)" class="w-full bg-blue-500 text-white rounded py-1.5 font-medium hover:bg-blue-600 transition">로그인</button>
                
                <label class="relative inline-flex items-center cursor-pointer mx-auto">
                  <input type="checkbox" class="sr-only peer" checked>
                  <div class="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-500"></div>
                </label>
                <label class="relative inline-flex items-center cursor-pointer mx-auto">
                  <input type="checkbox" class="sr-only peer" checked>
                  <div class="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-500"></div>
                </label>
                <label class="relative inline-flex items-center cursor-pointer mx-auto">
                  <input type="checkbox" class="sr-only peer">
                  <div class="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-500"></div>
                </label>
                
                <button onclick="removeAccountRow(this)" class="text-slate-300 hover:text-rose-500 mx-auto"><i data-lucide="x" class="w-4 h-4"></i></button>
              </div>
            </div>
          </div>
        </div>

        <!-- 2. 기타 플랫폼 콜랩스 라인들 (동적 아코디언) -->
        <div class="flex flex-col text-sm text-slate-800 font-bold divide-y divide-slate-100">
          
          <!-- 29CM -->
          <div>
            <div class="px-6 py-3.5 flex items-center justify-between hover:bg-slate-50 cursor-pointer" onclick="toggleAccordion('acc-29cm', this.querySelector('.chevron'))">
              <div class="flex items-center gap-3">
                <div class="w-6 h-6 rounded bg-orange-600 text-white flex items-center justify-center text-[10px]">29</div>
                <span>29CM</span>
                <span id="badge-29cm" class="bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full text-[10px] font-normal transition">계정 없음</span>
              </div>
              <div class="flex items-center gap-3">
                <button onclick="event.stopPropagation(); addAccountRow('list-29cm'); openAccordion('acc-29cm', this.nextElementSibling);" class="text-slate-400 text-[11px] font-normal hover:text-slate-700 z-10">+ 계정 추가</button>
                <i data-lucide="chevron-down" class="w-4 h-4 text-slate-400 chevron"></i>
              </div>
            </div>
            <div id="acc-29cm" class="hidden px-6 pb-4 bg-slate-50/50 pt-2"><div id="list-29cm" class="space-y-2"></div></div>
          </div>

          <!-- ELAND -->
          <div>
            <div class="px-6 py-3.5 flex items-center justify-between hover:bg-slate-50 cursor-pointer" onclick="toggleAccordion('acc-eland', this.querySelector('.chevron'))">
              <div class="flex items-center gap-3">
                <div class="w-6 h-6 rounded bg-blue-900 text-white flex items-center justify-center text-[10px]">EL</div>
                <span>ELAND</span>
                <span id="badge-eland" class="bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full text-[10px] font-normal transition">계정 없음</span>
              </div>
              <div class="flex items-center gap-3">
                <button onclick="event.stopPropagation(); addAccountRow('list-eland'); openAccordion('acc-eland', this.nextElementSibling);" class="text-slate-400 text-[11px] font-normal hover:text-slate-700 z-10">+ 계정 추가</button>
                <i data-lucide="chevron-down" class="w-4 h-4 text-slate-400 chevron"></i>
              </div>
            </div>
            <div id="acc-eland" class="hidden px-6 pb-4 bg-slate-50/50 pt-2"><div id="list-eland" class="space-y-2"></div></div>
          </div>

          <!-- LOTTE ON -->
          <div>
            <div class="px-6 py-3.5 flex items-center justify-between hover:bg-slate-50 cursor-pointer" onclick="toggleAccordion('acc-lotte', this.querySelector('.chevron'))">
              <div class="flex items-center gap-3">
                <div class="w-6 h-6 rounded bg-red-600 text-white flex items-center justify-center text-[10px]">L</div>
                <span>LOTTE ON</span>
                <span id="badge-lotte" class="bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full text-[10px] font-normal transition">계정 없음</span>
              </div>
              <div class="flex items-center gap-3">
                <button onclick="event.stopPropagation(); addAccountRow('list-lotte'); openAccordion('acc-lotte', this.nextElementSibling);" class="text-slate-400 text-[11px] font-normal hover:text-slate-700 z-10">+ 계정 추가</button>
                <i data-lucide="chevron-down" class="w-4 h-4 text-slate-400 chevron"></i>
              </div>
            </div>
            <div id="acc-lotte" class="hidden px-6 pb-4 bg-slate-50/50 pt-2"><div id="list-lotte" class="space-y-2"></div></div>
          </div>

          <!-- SSG -->
          <div>
            <div class="px-6 py-3.5 flex items-center justify-between hover:bg-slate-50 cursor-pointer" onclick="toggleAccordion('acc-ssg', this.querySelector('.chevron'))">
              <div class="flex items-center gap-3">
                <div class="w-6 h-6 rounded bg-[#ff5b59] text-white flex items-center justify-center text-[10px]">SSG</div>
                <span>SSG</span>
                <span id="badge-ssg" class="bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full text-[10px] font-normal transition">계정 없음</span>
              </div>
              <div class="flex items-center gap-3">
                <button onclick="event.stopPropagation(); addAccountRow('list-ssg'); openAccordion('acc-ssg', this.nextElementSibling);" class="text-slate-400 text-[11px] font-normal hover:text-slate-700 z-10">+ 계정 추가</button>
                <i data-lucide="chevron-down" class="w-4 h-4 text-slate-400 chevron"></i>
              </div>
            </div>
            <div id="acc-ssg" class="hidden px-6 pb-4 bg-slate-50/50 pt-2"><div id="list-ssg" class="space-y-2"></div></div>
          </div>

        </div>
      </div>

      <!-- NIKE / ADIDAS 외부 연동 카드 영역 -->
      <div class="max-w-6xl space-y-4">
        <!-- NIKE -->
        <div class="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
              <div class="w-8 h-8 rounded bg-black text-white font-bold flex items-center justify-center text-sm">N</div>
              <span class="font-bold text-sm text-slate-800">NIKE</span>
              <span class="bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full text-[10px] flex items-center gap-1.5 ml-2">
                <span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span> 로그아웃
              </span>
            </div>
            <button class="bg-indigo-500 hover:bg-indigo-600 text-white px-4 py-1.5 rounded text-xs font-medium transition">NIKE 로그인</button>
          </div>
          <div class="bg-slate-50 border border-slate-100 text-slate-500 p-3 rounded text-[11px]">
            로그인 버튼을 누르면 Chrome이 열립니다. NIKE 로그인 후 자동 연동됩니다.
          </div>
        </div>

        <!-- ADIDAS -->
        <div class="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
              <div class="w-8 h-8 rounded bg-black text-white font-bold flex items-center justify-center text-sm">A</div>
              <span class="font-bold text-sm text-slate-800">ADIDAS</span>
              <span class="bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full text-[10px] flex items-center gap-1.5 ml-2">
                <span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span> 로그아웃
              </span>
            </div>
            <button class="bg-indigo-500 hover:bg-indigo-600 text-white px-4 py-1.5 rounded text-xs font-medium transition">ADIDAS 로그인</button>
          </div>
          <div class="bg-slate-50 border border-slate-100 text-slate-500 p-3 rounded text-[11px]">
            로그인 버튼을 누르면 Chrome이 열립니다. ADIDAS 로그인 후 자동 연동됩니다.
          </div>
        </div>
      </div>
      
    </main>

    <!-- ========================================== -->
    <!-- [뷰 2] 무신사 가격 추적 화면 (기존 구현 유지) -->
    <!-- ========================================== -->
    <main id="view-tracker" class="flex-1 overflow-y-auto p-6 space-y-4 hidden bg-slate-50">
      
      <div class="flex items-center justify-between">
        <div class="inline-flex items-center gap-1.5 bg-amber-50/70 border border-amber-200 text-amber-800 px-3 py-1 rounded-md text-[11px]">
          <span>★ 무신사 회원 쿠폰 & 등급할인 실시간 반영</span>
        </div>
      </div>

      <div class="bg-white rounded-lg border border-slate-200 p-5 shadow-sm space-y-3">
        <div>
          <h3 class="font-bold text-slate-800 text-sm">상품 검색 및 추가</h3>
          <p class="text-slate-400 text-[11px] mt-0.5">무신사 상품 URL 또는 품번을 입력하여 실시간 추가하세요. (영구 보관)</p>
        </div>
        <form onsubmit="handleSearch(event)" class="flex gap-2">
          <div class="relative flex-1">
            <i data-lucide="search" class="w-4 h-4 absolute left-3 top-2.5 text-slate-400"></i>
            <input id="search-input" type="text" placeholder="예: https://www.musinsa.com/products/3847291 또는 3847291 입력" class="w-full pl-9 pr-3 py-2 border border-slate-200 rounded-md outline-none focus:border-blue-500 text-xs bg-slate-50/30"/>
          </div>
          <button type="submit" id="btn-search" class="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-md font-medium text-xs flex items-center gap-1.5">
            <i data-lucide="search" class="w-3.5 h-3.5"></i> 검색 및 추가
          </button>
        </form>
      </div>

      <div class="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
        <div class="p-4 border-b border-slate-100 flex items-center justify-between">
          <div>
            <h3 class="font-bold text-slate-800 text-sm">추적 목록</h3>
            <p class="text-slate-400 text-[11px] mt-0.5">추적 희망가를 직접 수정하면 자동 저장되며, 도달 시 즉시 알림이 발생합니다.</p>
          </div>
          <div class="flex items-center gap-4">
            <div class="flex items-center gap-1.5">
              <button onclick="fetchItems()" title="새로고침" class="p-1.5 border border-slate-200 rounded hover:bg-slate-50 text-slate-500">
                <i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i>
              </button>
              <button onclick="deleteSelected()" class="flex items-center gap-1 border border-slate-200 text-slate-500 px-2.5 py-1 rounded text-[11px] hover:bg-slate-50">
                <i data-lucide="trash-2" class="w-3 h-3"></i> 선택 삭제
              </button>
              <button id="btn-toggle-tracking" onclick="toggleTracking()" class="flex items-center gap-1 bg-emerald-50 text-emerald-600 border border-emerald-200 hover:bg-emerald-100 px-3 py-1 rounded text-[11px] font-semibold">
                <i data-lucide="play" class="w-3 h-3 fill-emerald-600"></i> 추적 시작
              </button>
            </div>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse text-[11px]">
            <thead>
              <tr class="border-b border-slate-100 text-slate-400 bg-slate-50/50">
                <th class="py-2.5 px-3 text-center w-8"><input type="checkbox" id="check-all" onchange="toggleCheckAll(this)" class="rounded border-slate-300 text-blue-600 w-3.5 h-3.5"></th>
                <th class="py-2.5 px-3 font-normal">이미지</th>
                <th class="py-2.5 px-3 font-normal">브랜드</th>
                <th class="py-2.5 px-4 font-normal">상품명</th>
                <th class="py-2.5 px-3 font-normal text-right">정상가</th>
                <th class="py-2.5 px-3 font-normal text-right">등급할인</th>
                <th class="py-2.5 px-3 font-normal text-right">쿠폰할인</th>
                <th class="py-2.5 px-4 font-normal text-right">현재가 (최대혜택가)</th>
                <th class="py-2.5 px-4 font-normal text-right text-blue-600 font-semibold">🎯 추적 희망가 (직접입력)</th>
                <th class="py-2.5 px-3 font-normal text-center">도달상태</th>
                <th class="py-2.5 px-3 font-normal text-center">관리</th>
              </tr>
            </thead>
            <tbody id="table-body" class="divide-y divide-slate-100"></tbody>
          </table>
        </div>
        <div class="p-3 bg-slate-50/50 border-t border-slate-100 text-slate-400 text-[11px] flex justify-between items-center">
          <span>상단 [추적 시작] 버튼을 누르면 3분 주기로 자동 추적이 가동됩니다.</span>
          <span class="text-slate-500">금액 입력 후 Enter 또는 클릭 해제 시 즉시 영구 저장됩니다.</span>
        </div>
      </div>
    </main>
  </div>

  <script>
    // ==========================================
    // UI 인터랙션 함수 (판매처 연동 화면)
    // ==========================================
    
    // 아코디언 토글 (접기/펼치기)
    function toggleAccordion(contentId, iconEl) {
      const content = document.getElementById(contentId);
      if (content.classList.contains('hidden')) {
        content.classList.remove('hidden');
        content.classList.add('block');
        if (iconEl) iconEl.setAttribute('data-lucide', 'chevron-up');
      } else {
        content.classList.add('hidden');
        content.classList.remove('block');
        if (iconEl) iconEl.setAttribute('data-lucide', 'chevron-down');
      }
      lucide.createIcons();
    }

    // 아코디언 강제 열기 (계정 추가 시)
    function openAccordion(contentId, iconEl) {
      const content = document.getElementById(contentId);
      content.classList.remove('hidden');
      content.classList.add('block');
      if (iconEl) iconEl.setAttribute('data-lucide', 'chevron-up');
      lucide.createIcons();
    }

    // 비밀번호 눈모양(마스킹) 토글
    function togglePassword(iconEl) {
      const input = iconEl.previousElementSibling;
      if (input.type === 'password') {
        input.type = 'text';
        iconEl.setAttribute('data-lucide', 'eye');
        iconEl.classList.add('text-blue-500');
      } else {
        input.type = 'password';
        iconEl.setAttribute('data-lucide', 'eye-off');
        iconEl.classList.remove('text-blue-500');
      }
      lucide.createIcons();
    }

    // 로그인/로그아웃 버튼 스위칭
    function toggleLogin(btnEl) {
      if (btnEl.innerText === '로그인') {
        btnEl.innerText = '로그아웃';
        btnEl.className = "w-full bg-slate-500 text-white rounded py-1.5 font-medium hover:bg-slate-600 transition";
      } else {
        btnEl.innerText = '로그인';
        btnEl.className = "w-full bg-blue-500 text-white rounded py-1.5 font-medium hover:bg-blue-600 transition";
      }
    }

    // 별(즐겨찾기) 아이콘 스위칭
    function toggleStar(iconEl) {
      iconEl.classList.toggle('text-amber-400');
      iconEl.classList.toggle('fill-amber-400');
      iconEl.classList.toggle('text-slate-300');
    }

    // 새로운 계정 입력 Row 추가
    function addAccountRow(containerId) {
      const container = document.getElementById(containerId);
      const row = document.createElement('div');
      row.className = "grid-accounts bg-white border-b border-slate-100 last:border-0 pb-3 mt-2";
      row.innerHTML = `
        <i data-lucide="star" class="w-4 h-4 text-slate-300 cursor-pointer" onclick="toggleStar(this)"></i>
        <input type="text" placeholder="별칭" class="w-full bg-slate-50 border border-slate-200 rounded px-3 py-1.5 outline-none focus:border-blue-400 text-xs">
        <input type="text" placeholder="아이디" class="w-full bg-slate-50 border border-slate-200 rounded px-3 py-1.5 outline-none focus:border-blue-400 text-xs">
        <div class="relative w-full">
          <input type="password" placeholder="비밀번호" class="w-full bg-slate-50 border border-slate-200 rounded pl-3 pr-8 py-1.5 outline-none focus:border-blue-400 text-xs tracking-widest">
          <i data-lucide="eye-off" onclick="togglePassword(this)" class="w-3.5 h-3.5 absolute right-2.5 top-2 text-slate-400 cursor-pointer hover:text-blue-500"></i>
        </div>
        <button onclick="toggleLogin(this)" class="w-full bg-blue-500 text-white rounded py-1.5 font-medium hover:bg-blue-600 transition">로그인</button>
        
        <label class="relative inline-flex items-center cursor-pointer mx-auto">
          <input type="checkbox" class="sr-only peer" checked>
          <div class="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-500"></div>
        </label>
        <label class="relative inline-flex items-center cursor-pointer mx-auto">
          <input type="checkbox" class="sr-only peer" checked>
          <div class="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-500"></div>
        </label>
        <label class="relative inline-flex items-center cursor-pointer mx-auto">
          <input type="checkbox" class="sr-only peer">
          <div class="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-500"></div>
        </label>
        
        <button onclick="removeAccountRow(this, '${containerId}')" class="text-slate-300 hover:text-rose-500 mx-auto"><i data-lucide="x" class="w-4 h-4"></i></button>
      `;
      container.appendChild(row);
      updatePlatformBadge(containerId);
      lucide.createIcons();
    }

    // 계정 입력 Row 삭제
    function removeAccountRow(btnEl, containerId) {
      btnEl.closest('.grid-accounts').remove();
      if(containerId) updatePlatformBadge(containerId);
    }

    // платфор마 배지 업데이트 (계정 개수 표시)
    function updatePlatformBadge(containerId) {
      const container = document.getElementById(containerId);
      const count = container.querySelectorAll('.grid-accounts').length;
      
      let badgeId = '';
      if(containerId === 'list-musinsa') badgeId = 'count-musinsa';
      else if(containerId === 'list-29cm') badgeId = 'badge-29cm';
      else if(containerId === 'list-eland') badgeId = 'badge-eland';
      else if(containerId === 'list-lotte') badgeId = 'badge-lotte';
      else if(containerId === 'list-ssg') badgeId = 'badge-ssg';

      if(!badgeId) return;
      const badge = document.getElementById(badgeId);
      
      if(badgeId === 'count-musinsa') {
        badge.innerText = count + " 계정";
      } else {
        if(count > 0) {
          badge.className = "bg-orange-50 text-orange-600 px-2 py-0.5 rounded-full text-[10px] font-bold transition";
          badge.innerText = count + "개 연동됨";
        } else {
          badge.className = "bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full text-[10px] font-normal transition";
          badge.innerText = "계정 없음";
        }
      }
    }


    // ==========================================
    // 앱 초기화 및 가격 추적 로직 (기존 유지)
    // ==========================================
    let currentItems = [];
    let isTrackingRunning = false;

    window.onload = () => {
      lucide.createIcons();
      fetchItems();
      switchView('platform');
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission();
      }
    };

    function switchView(viewName) {
      document.getElementById('view-platform').classList.add('hidden');
      document.getElementById('view-platform').classList.remove('block');
      document.getElementById('view-tracker').classList.add('hidden');
      document.getElementById('view-tracker').classList.remove('block');
      
      const navPlatform = document.getElementById('nav-platform');
      const navTracker = document.getElementById('nav-tracker');
      
      navPlatform.classList.remove('bg-blue-50', 'text-blue-600');
      navTracker.classList.remove('bg-blue-50', 'text-blue-600');

      if (viewName === 'platform') {
        document.getElementById('view-platform').classList.remove('hidden');
        document.getElementById('view-platform').classList.add('block');
        navPlatform.classList.add('bg-blue-50', 'text-blue-600');
      } else if (viewName === 'tracker') {
        document.getElementById('view-tracker').classList.remove('hidden');
        document.getElementById('view-tracker').classList.add('block');
        navTracker.classList.add('bg-blue-50', 'text-blue-600');
      }
    }

    function requestNotificationPermission() {
      if ("Notification" in window) {
        Notification.requestPermission().then(permission => {
          if (permission === "granted") showToast("🔔 알림 설정", "브라우저 알림이 켜졌습니다.");
          else alert("알림 권한이 차단되었습니다.");
        });
      }
    }

    function triggerPriceAlert(item) {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("🎯 목표가 도달 알림!", {
          body: `[${item.brand}] ${item.title}\\n현재가 ${item.final_price.toLocaleString()}원이 희망가(${item.target_price.toLocaleString()}원)에 도달했습니다!`,
          icon: item.image
        });
      }
      showToast("🎯 희망가 도달 알림!", `<b>[${item.brand}]</b> ${item.title}<br>현재가: <span class="text-emerald-600 font-bold">${item.final_price.toLocaleString()}원</span> (희망가: ${item.target_price.toLocaleString()}원)`, true);
      fetch('/api/items/mark_notified', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: item.id }) });
    }

    function showToast(title, message, isTargetReached = false) {
      const container = document.getElementById('toast-container');
      const toast = document.createElement('div');
      toast.className = `pointer-events-auto p-3.5 rounded-lg shadow-lg border text-xs max-w-sm toast-anim ${isTargetReached ? 'bg-emerald-50 border-emerald-300 text-emerald-900' : 'bg-white border-slate-200 text-slate-800'}`;
      toast.innerHTML = `
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="font-bold flex items-center gap-1.5">
              ${isTargetReached ? '<i data-lucide="bell" class="w-3.5 h-3.5 text-emerald-600"></i>' : ''} ${title}
            </div>
            <div class="mt-1 leading-relaxed text-[11px] text-slate-600">${message}</div>
          </div>
          <button onclick="this.parentElement.parentElement.remove()" class="text-slate-400 hover:text-slate-600"><i data-lucide="x" class="w-3.5 h-3.5"></i></button>
        </div>
      `;
      container.appendChild(toast);
      lucide.createIcons();
      setTimeout(() => { if (toast) toast.remove(); }, 7000);
    }

    async function fetchItems() {
      try {
        const res = await fetch('/api/items');
        const data = await res.json();
        currentItems = data.items;
        isTrackingRunning = data.is_tracking_global;

        currentItems.forEach(item => {
          if (item.is_tracking && item.reached && !item.notified) triggerPriceAlert(item);
        });

        updateUI();
      } catch (e) { console.error(e); }
    }

    function updateUI() {
      const tbody = document.getElementById('table-body');
      const activeElementId = document.activeElement ? document.activeElement.id : null;
      tbody.innerHTML = '';

      const btnTracking = document.getElementById('btn-toggle-tracking');
      const pill = document.getElementById('tracker-pill');
      
      if (isTrackingRunning) {
        btnTracking.className = "flex items-center gap-1 bg-rose-50 text-rose-600 border border-rose-200 hover:bg-rose-100 px-3 py-1 rounded text-[11px] font-semibold";
        btnTracking.innerHTML = `<i data-lucide="square" class="w-3 h-3 fill-rose-600"></i> 추적 중지`;
        pill.innerText = "ON"; pill.className = "text-[9px] bg-emerald-100 text-emerald-700 px-1.5 py-0.2 rounded-full font-medium";
      } else {
        btnTracking.className = "flex items-center gap-1 bg-emerald-50 text-emerald-600 border border-emerald-200 hover:bg-emerald-100 px-3 py-1 rounded text-[11px] font-semibold";
        btnTracking.innerHTML = `<i data-lucide="play" class="w-3 h-3 fill-emerald-600"></i> 추적 시작`;
        pill.innerText = "OFF"; pill.className = "text-[9px] bg-slate-200 text-slate-500 px-1.5 py-0.2 rounded-full font-medium";
      }

      currentItems.forEach(item => {
        const tr = document.createElement('tr');
        tr.className = `hover:bg-slate-50/60 ${item.reached ? 'bg-emerald-50/40' : ''}`;
        const couponBadge = item.badge ? `<div class="mt-0.5"><span class="badge-coupon text-[9px] px-1.5 py-0.2 rounded font-medium">${item.badge}</span></div>` : '';
        const isReachedBadge = item.reached ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-bold text-[10px] animate-pulse">🎯 도달완료</span>` : (item.is_tracking ? `<span class="inline-block px-2 py-0.5 rounded bg-blue-50 text-blue-600 text-[10px] font-medium">추적 중</span>` : `<span class="inline-block px-2 py-0.5 rounded bg-slate-100 text-slate-400 text-[10px]">대기 중</span>`);

        tr.innerHTML = `
          <td class="py-3 px-3 text-center"><input type="checkbox" value="${item.id}" class="row-checkbox rounded border-slate-300 text-blue-600 w-3.5 h-3.5"></td>
          <td class="py-3 px-3"><a href="${item.url}" target="_blank"><img src="${item.image}" class="w-10 h-10 object-cover rounded border border-slate-200 hover:opacity-80 transition" onerror="this.src='https://image.msscdn.net/images/no_image.png'" /></a></td>
          <td class="py-3 px-3 font-semibold text-slate-700">${item.brand}</td>
          <td class="py-3 px-4 max-w-xs"><a href="${item.url}" target="_blank" class="font-medium text-slate-800 hover:text-blue-600 leading-tight block">${item.title}</a></td>
          <td class="py-3 px-3 text-right text-slate-600">${item.origin_price.toLocaleString()}원</td>
          <td class="py-3 px-3 text-right text-slate-500">${item.grade_discount ? item.grade_discount.toLocaleString() + '원' : '-'}</td>
          <td class="py-3 px-3 text-right text-slate-500">${item.coupon_discount ? item.coupon_discount.toLocaleString() + '원' : '-'}</td>
          <td class="py-3 px-4 text-right"><div class="font-bold ${item.reached ? 'text-emerald-600 text-[13px]' : 'text-rose-600'} text-xs">${item.final_price.toLocaleString()}원</div>${couponBadge}</td>
          <td class="py-3 px-4 text-right">
            <div class="flex items-center justify-end gap-1">
              <input id="target-input-${item.id}" type="number" step="100" value="${item.target_price}" onchange="saveTargetPrice(${item.id}, this.value)" onkeydown="if(event.key==='Enter') { this.blur(); }" class="w-24 text-right px-2 py-1 border border-blue-200 focus:border-blue-500 rounded bg-blue-50/40 text-slate-800 font-semibold focus:outline-none text-xs"/>
              <span class="text-slate-500">원</span>
            </div>
          </td>
          <td class="py-3 px-3 text-center">${isReachedBadge}</td>
          <td class="py-3 px-3 text-center"><button onclick="deleteSingle(${item.id})" class="hover:text-rose-600 p-1"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button></td>
        `;
        tbody.appendChild(tr);
      });
      lucide.createIcons();
      if (activeElementId && document.getElementById(activeElementId)) document.getElementById(activeElementId).focus();
    }

    async function saveTargetPrice(itemId, newTargetPrice) {
      const price = parseInt(newTargetPrice, 10);
      if (isNaN(price) || price < 0) return fetchItems();
      await fetch('/api/items/update_target', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: itemId, target_price: price }) });
      fetchItems();
    }

    async function handleSearch(e) {
      e.preventDefault();
      const input = document.getElementById('search-input');
      const query = input.value.trim();
      if (!query) return;
      document.getElementById('btn-search').disabled = true;
      const res = await fetch('/api/items/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query }) });
      const data = await res.json();
      if (data.success) { input.value = ''; fetchItems(); } else alert(data.message);
      document.getElementById('btn-search').disabled = false;
    }

    function toggleCheckAll(source) { document.querySelectorAll('.row-checkbox').forEach(cb => cb.checked = source.checked); }
    function getSelectedIds() { return Array.from(document.querySelectorAll('.row-checkbox:checked')).map(cb => parseInt(cb.value)); }
    async function deleteSelected() {
      const ids = getSelectedIds();
      if (ids.length === 0) return alert("삭제할 상품을 체크해주세요.");
      await fetch('/api/items/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) });
      fetchItems();
    }
    async function deleteSingle(id) {
      await fetch('/api/items/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: [id] }) });
      fetchItems();
    }
    async function toggleTracking() {
      await fetch('/api/tracking/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: isTrackingRunning ? 'stop' : 'start', ids: getSelectedIds() }) });
      fetchItems();
    }
    setInterval(() => { if (isTrackingRunning) fetchItems(); }, 4000);
  </script>
</body>
</html>
"""

# ==============================================================================
# [7] 서버 실행 및 초기 순회 실행부
# ==============================================================================
if __name__ == "__main__":
    print("🚀 플라스크 서버를 시작합니다...")
    
    def delayed_startup_and_initial_run():
        # 창이 안정화될 때까지 잠시 대기 후 서버 실행 메시지 전송
        time.sleep(1.5)
        startup_msg = "🟢 [빵채 셀러 시스템] 가격 추적 서버가 정상적으로 실행되었습니다!"
        send_kakao_message(KAKAO_ROOM_NAME, startup_msg)
        
        # 메시지 전송 직후 대기 없이 첫 번째 가격 추적 순회 즉시 실행
        time.sleep(1.0)
        run_tracking_cycle()

    # 백그라운드 스레드로 실행하여 플라스크 웹 서버 구동을 방해하지 않음
    threading.Thread(target=delayed_startup_and_initial_run, daemon=True).start()
    
    app.run(debug=True, port=5000, use_reloader=False)