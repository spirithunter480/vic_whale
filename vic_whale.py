import os
import asyncio
import aiohttp
import base64
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

TON_API_KEY = os.getenv("TON_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
NOTIFIER_CHAT_ID = os.getenv("NOTIFIER_CHAT_ID")

# Target wallet address and jetton master contract address
TARGET_WALLET = "UQD-Jv-fsvCZgyUan28CA1kMe9WBRE3-nl_y9u0B71R0-Xsh"
TARGET_JETTON_MASTER = "EQClb4h8Wnqx-X_sKMFExqxcQusCktlMHxYZ2M80A_WnnFUe"

HEADERS = {}
if TON_API_KEY and len(TON_API_KEY.strip()) > 10:
    HEADERS["Authorization"] = f"Bearer {TON_API_KEY.strip()}"

def to_raw_address(address: str) -> str:
    """Convert EQ/UQ address to unified raw format (0:...) for accurate matching."""
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

# Standardize addresses for reliable comparison
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
    last_event_id = None
    url = f"https://tonapi.io/v2/accounts/{TARGET_WALLET_RAW}/events?limit=10"
    
    print("🚀 Monitoring started for wallet:", TARGET_WALLET)
    print("🎯 Target Jetton Master:", TARGET_JETTON_MASTER)
    
    while True:
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        events = data.get("events", [])
                        
                        # Set initial baseline on startup to avoid spamming past transactions
                        if last_event_id is None:
                            if events:
                                last_event_id = events[0]["event_id"]
                            await asyncio.sleep(3)
                            continue
                        
                        # Process events from oldest to newest
                        for event in reversed(events):
                            if event["event_id"] == last_event_id:
                                continue
                            
                            for action in event.get("actions", []):
                                if action.get("type") == "JettonTransfer":
                                    jetton_data = action.get("JettonTransfer", {})
                                    
                                    recipient = jetton_data.get("recipient", {}).get("address", "")
                                    master = jetton_data.get("jetton", {}).get("address", "")
                                    
                                    # Compare normalized addresses
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
                                            f"🔗 <a href='https://tonviewer.com/transaction/{event['event_id']}'>View on Tonviewer</a>"
                                        )
                                        await send_telegram(msg)
                            
                            last_event_id = event["event_id"]
                    else:
                        print(f"[TonAPI Error] Status: {response.status}")
                        
        except Exception as e:
            print(f"[Exception] {e}")
            
        await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(monitor_wallet())
