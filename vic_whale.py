import os
import asyncio
import aiohttp
import base64
from dotenv import load_dotenv

load_dotenv()

TON_API_KEY = os.getenv("TON_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
NOTIFIER_CHAT_ID = os.getenv("NOTIFIER_CHAT_ID")

TARGET_WALLET = "UQD-Jv-fsvCZgyUan28CA1kMe9WBRE3-nl_y9u0B71R0-Xsh"
TARGET_JETTON_MASTER = "EQClb4h8Wnqx-X_sKMFExqxcQusCktlMHxYZ2M80A_WnnFUe"

HEADERS = {}
if TON_API_KEY and len(TON_API_KEY.strip()) > 20:
    clean_key = TON_API_KEY.strip().replace('"', '').replace("'", "")
    HEADERS["Authorization"] = f"Bearer {clean_key}"

def to_raw_address(address: str) -> str:
    if not address:
        return ""
    addr = address.strip()
    if addr.startswith("0:") or addr.startswith("-1:"):
        return addr.lower()
    try:
        b64 = addr.replace("-", "+").replace("_", "/")
        b64 += "=" * ((4 - len(b64) % 4) % 4)
        raw_bytes = base64.b64decode(b64)
        workchain = int.from_bytes(raw_bytes[1:2], byteorder="big", signed=True)
        account_id = raw_bytes[2:34].hex()
        return f"{workchain}:{account_id}".lower()
    except Exception:
        return addr.lower()

TARGET_WALLET_RAW = to_raw_address(TARGET_WALLET)
TARGET_JETTON_MASTER_RAW = to_raw_address(TARGET_JETTON_MASTER)

async def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": NOTIFIER_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                print(f"[TG Error] Status: {resp.status}, Body: {await resp.text()}")

async def monitor_wallet():
    # ثبت تمام تراکنش‌های دیده‌شده برای جلوگیری قطعی از تکرار
    seen_event_ids = set()
    is_first_run = True
    url = f"https://tonapi.io/v2/accounts/{TARGET_WALLET_RAW}/events?limit=20"
    
    print("🚀 Monitoring started for wallet:", TARGET_WALLET)
    print("🎯 Target Jetton Master:", TARGET_JETTON_MASTER)
    
    while True:
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        events = data.get("events", [])
                        
                        # در اجرای اول تمام تراکنش‌های گذشته ثبت و رد می‌شوند تا اسپم نشود
                        if is_first_run:
                            for ev in events:
                                seen_event_ids.add(ev.get("event_id"))
                            is_first_run = False
                            print(f"✅ Baseline established. Ignored {len(seen_event_ids)} past transactions.")
                            await asyncio.sleep(4)
                            continue
                        
                        # بررسی رویدادهای جدید (از قدیمی به جدید)
                        for event in reversed(events):
                            eid = event.get("event_id")
                            if not eid or eid in seen_event_ids:
                                continue
                            
                            # بلافاصله به لیست رویدادهای دیده شده اضافه می‌شود
                            seen_event_ids.add(eid)
                            
                            # کنترل حجم حافظه set
                            if len(seen_event_ids) > 1000:
                                seen_event_ids.pop()

                            for action in event.get("actions", []):
                                if action.get("type") == "JettonTransfer":
                                    jetton_data = action.get("JettonTransfer", {})
                                    
                                    recipient = jetton_data.get("recipient", {}).get("address", "")
                                    master = jetton_data.get("jetton", {}).get("address", "")
                                    
                                    is_match_token = to_raw_address(master) == TARGET_JETTON_MASTER_RAW
                                    is_match_wallet = to_raw_address(recipient) == TARGET_WALLET_RAW
                                    
                                    if is_match_token and is_match_wallet:
                                        decimals = jetton_data.get("jetton", {}).get("decimals", 9)
                                        raw_amount = int(jetton_data.get("amount", 0))
                                        amount = raw_amount / (10 ** decimals)
                                        
                                        symbol = jetton_data.get("jetton", {}).get("symbol", "Jetton")
                                        sender = jetton_data.get("sender", {}).get("address", "Unknown")
                                        
                                        msg = (
                                            f"🚨 <b>New Jetton Deposit Detected!</b>\n\n"
                                            f"🪙 <b>Token:</b> {symbol}\n"
                                            f"💰 <b>Amount:</b> <code>{amount:,.4f}</code>\n"
                                            f"📥 <b>Recipient:</b> <code>{recipient}</code>\n"
                                            f"📤 <b>Sender:</b> <code>{sender}</code>\n\n"
                                            f"🔗 <a href='https://tonviewer.com/transaction/{eid}'>View on Tonviewer</a>"
                                        )
                                        await send_telegram(msg)
                    else:
                        error_body = await response.text()
                        print(f"[TonAPI Error] Status: {response.status}, Detail: {error_body}")
                        
        except Exception as e:
            print(f"[Exception] {e}")
            
        await asyncio.sleep(4)

if __name__ == "__main__":
    asyncio.run(monitor_wallet())
