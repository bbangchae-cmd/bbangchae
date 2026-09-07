Python
from flask import Flask, render_template, request, jsonify
import json
import os
import re
import requests
from bs4 import BeautifulSoup
import threading

app = Flask(__name__)

# 무신사 쿠키 설정
RAW_COOKIE_STRING = """여기에_무신사_로그인_쿠키를_붙여넣으세요"""
def parse_cookie_string(raw_cookie: str) -> dict:
    cookies = {}
    if not raw_cookie or "여기에_" in raw_cookie: return cookies
    for item in raw_cookie.strip().split(';'):
        if '=' in item:
            k, v = item.strip().split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies
MY_MUSINSA_COOKIES = parse_cookie_string(RAW_COOKIE_STRING)

# 데이터베이스
DATA_FILE = "tracking_items.json"
db_lock = threading.Lock()
TRACKING_ITEMS = []
TRACKING_RUNNING = False # GitHub Actions가 추적하므로 여기선 상태만 표시

def load_items_from_file():
    global TRACKING_ITEMS, TRACKING_RUNNING
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                TRACKING_ITEMS = data.get("items", [])
                TRACKING_RUNNING = data.get("is_tracking", False)
        except: pass

def save_items_to_file():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"is_tracking": TRACKING_RUNNING, "items": TRACKING_ITEMS}, f, ensure_ascii=False, indent=2)
    except Exception as e: print(f"저장 오류: {e}")

load_items_from_file()

# 무신사 크롤러 (아이템 추가할 때 한 번 정보 가져오는 용도)
class MusinsaCrawler:
    def __init__(self, cookies_dict=None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.musinsa.com/"
        })
        if cookies_dict: self.session.cookies.update(cookies_dict)

    def extract_goods_no(self, query: str) -> str:
        match = re.findall(r'\d+', str(query))
        return match[0] if match else ""

    def get_goods_info(self, goods_no: str):
        # (기존 get_goods_info 및 _scrape_html_page 등 크롤링 로직을 그대로 유지합니다)
        # 내용이 길어 생략하지만, 기존 코드의 해당 함수 내용을 그대로 쓰시면 됩니다.
        pass

crawler = MusinsaCrawler(cookies_dict=MY_MUSINSA_COOKIES)

# API 라우트
@app.route("/")
def dashboard():
    return render_template("index.html")

@app.route("/api/items", methods=["GET"])
def get_items():
    load_items_from_file() # 화면 새로고침 시 최신 JSON 읽어오기
    with db_lock:
        return jsonify({"items": TRACKING_ITEMS, "is_tracking_global": TRACKING_RUNNING, "has_cookie": bool(MY_MUSINSA_COOKIES)})

@app.route("/api/items/add", methods=["POST"])
def add_item():
    query = request.json.get("query", "").strip()
    goods_no = crawler.extract_goods_no(query)
    # (기존 add_item 로직 그대로 유지)
    return jsonify({"success": True})

# (기존 update_target, mark_notified, delete_items, toggle_tracking API 모두 유지)

if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)