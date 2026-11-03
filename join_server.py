import os
import re
import sys
import time
from curl_cffi import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

TOKEN_FILE = "tokens.txt"


def extract_invite_code(invite_input: str) -> str:
    """Tách mã invite code từ link hoặc chuỗi nhập vào."""
    invite_input = invite_input.strip()
    match = re.search(r"(?:discord\.gg/|discord\.com/invite/)?([a-zA-Z0-9-]+)$", invite_input)
    if match:
        return match.group(1)
    return invite_input


def load_tokens() -> list[str]:
    """Đọc danh sách token từ file tokens.txt."""
    if not os.path.exists(TOKEN_FILE):
        print(f"❌ Không tìm thấy file {TOKEN_FILE}!")
        return []

    tokens = []
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                tokens.append(line)
    return tokens


def join_guild(token: str, invite_code: str, index: int, total: int) -> bool:
    """Sử dụng API Discord để join server với impersonation trình duyệt Chrome."""
    url = f"https://discord.com/api/v9/invites/{invite_code}"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    try:
        session = requests.Session(impersonate="chrome120")
        response = session.post(url, headers=headers, json={})
        
        if response.status_code == 200:
            data = response.json()
            guild_name = data.get("guild", {}).get("name", "Unknown Server")
            print(f"✅ [{index}/{total}] Token ...{token[-8:]} -> Đã vào server: '{guild_name}'")
            return True
        elif response.status_code == 401:
            print(f"❌ [{index}/{total}] Token ...{token[-8:]} -> Token không hợp lệ / Hết hạn!")
            return False
        elif response.status_code == 403:
            print(f"⚠️ [{index}/{total}] Token ...{token[-8:]} -> Bị chặn (Yêu cầu Captcha hoặc IP bị cờ đỏ)!")
            return False
        elif response.status_code == 429:
            retry_after = response.json().get("retry_after", 5)
            print(f"⏳ [{index}/{total}] Đang bị Rate Limit, chờ {retry_after}s...")
            time.sleep(retry_after)
            return join_guild(token, invite_code, index, total)
        else:
            print(f"❌ [{index}/{total}] Token ...{token[-8:]} -> Lỗi {response.status_code}: {response.text[:100]}")
            return False
    except Exception as e:
        print(f"❌ [{index}/{total}] Lỗi kết nối: {e}")
        return False


def main():
    tokens = load_tokens()
    if not tokens:
        print(f"⚠️ File '{TOKEN_FILE}' đang trống! Hãy dán các token vào file tokens.txt trước.")
        return

    print("=" * 60)
    print(f"🚀 CÔNG CỤ TỰ ĐỘNG THAM GIA SERVER CHO {len(tokens)} TÀI KHOẢN")
    print("=" * 60)

    if len(sys.argv) > 1:
        invite_input = sys.argv[1].strip()
    else:
        invite_input = input("Nhập link mời Discord (ví dụ: https://discord.gg/abcxyz): ").strip()
    if not invite_input:
        print("❌ Chưa nhập link mời!")
        return

    invite_code = extract_invite_code(invite_input)
    print(f"👉 Đang xử lý mã mời: '{invite_code}'...")
    print("⏳ Bắt đầu tham gia (delay 3s giữa các acc để bảo đảm an toàn)...")
    print("-" * 60)

    success_count = 0
    for idx, token in enumerate(tokens, start=1):
        if join_guild(token, invite_code, idx, len(tokens)):
            success_count += 1
        if idx < len(tokens):
            time.sleep(3)

    print("=" * 60)
    print(f"🎉 Hoàn thành: {success_count}/{len(tokens)} tài khoản đã tham gia server thành công!")


if __name__ == "__main__":
    main()

