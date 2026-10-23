from dotenv import load_dotenv
load_dotenv()
import asyncio
from reminders import send_reminder

CASES = [
    ("Аренда офиса", "1 500,00", "RUB", "2026-11-01"),
    ("Subscription", "29.99", "USD", "2026-11-05"),
    ("Abo Strom", "84,50", "EUR", "2026-11-10"),
    ("Очень длинное название " * 30, "10", "EUR", "2026-11-15"),
    ("<b>bold</b> & _italic_ *star* [link](http://x) `code` #tag", "1", "USD", "2026-11-20"),
]

async def main():
    for case in CASES:
        print(await send_reminder(*case))

asyncio.run(main())