import os
import asyncio
import aiohttp
import base64
from dotenv import load_dotenv

load_dotenv()

TON_API_KEY = os.getenv("TON_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
NOTIFIER_CHAT_ID = os.getenv("NOTIFIER_CHAT_ID")

# لیست ولت‌های هدف برای مانیتورینگ
TARGET_WALLETS = [
    "UQD-Jv-fsvCZgyUan28CA1kMe9WBRE3-nl_y9u0B71R0-Xsh",
    "UQCdHd0HR51iRBFYDM2q25i-AhoHt5_Y-4rX2qQ1EJM1Fmi4",
    "UQDaYs2kud5EsXJNTnLUG3tMY8knpm3l5NxClO2jRRgKQBHL",
    "UQDxfJj18D3olhy4ZoqiAwouykxd3a7Bbe4g3SZOmZN9UyGt",
    "UQCyQQ6yOYXgK0MS4QR7lx5Jy84oH-lIR3NGvx_0sS4mwiLN",
    "UQCckRYi9BvNsRndPE8rZRpMZwXSlqY_TyRJNDTr_SlXN_EE",
    "UQD9ie8yg_NcrqRmrMV8jpSN8kXX2qCbyi8ybQx8ZX-SHAGf"
]

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

# نگاشت ولت‌های خام به آدرس‌های ورودی برای استفاده در تطابق و نوتیفیکیشن
TARGET_WALLETS_RAW = {to_raw_address(w): w for w in TARGET_WALLETS}
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
    seen_event_ids = set()
    is_first_run = True
    
    print(f"🚀 Monitoring started for {len(TARGET_WALLETS)} wallets:")
    for w in TARGET_WALLETS:
        print(f"   - {w}")
    print("🎯 Target Jetton Master:", TARGET_JETTON_MASTER)
    
    while True:
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                for wallet_raw, wallet_original in TARGET_WALLETS_RAW.items():
                    url = f"https://tonapi.io/v2/accounts/{wallet_raw}/events?limit=20"
                    
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            events = data.get("events", [])
                            
                            if is_first_run:
                                for ev in events:
                                    seen_event_ids.add(ev.get("event_id"))
                                continue
                            
                            for event in reversed(events):
                                eid = event.get("event_id")
                                if not eid or eid in seen_event_ids:
                                    continue
                                
                                seen_event_ids.add(eid)
                                
                                if len(seen_event_ids) > 2000:
                                    seen_event_ids.pop()

                                for action in event.get("actions", []):
                                    if action.get("type") == "JettonTransfer":
                                        jetton_data = action.get("JettonTransfer", {})
                                        
                                        recipient = jetton_data.get("recipient", {}).get("address", "")
                                        master = jetton_data.get("jetton", {}).get("address", "")
                                        
                                        is_match_token = to_raw_address(master) == TARGET_JETTON_MASTER_RAW
                                        is_match_wallet = to_raw_address(recipient) in TARGET_WALLETS_RAW
                                        
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
                            print(f"[TonAPI Error] Wallet: {wallet_original[:10]}... Status: {response.status}, Detail: {error_body}")
                    
                    # وقفه کوتاه بین بررسی هر ولت برای رعایت نرخ مجاز API
                    await asyncio.sleep(2)
                
                if is_first_run:
                    is_first_run = False
                    print(f"✅ Baseline established. Ignored {len(seen_event_ids)} past transactions across all wallets.")
                        
        except Exception as e:
            print(f"[Exception] {e}")
            
        await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(monitor_wallet())
