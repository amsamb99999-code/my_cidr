import os
import ipaddress
import asyncio
import threading
import sys
import io
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# دالة للطباعة الفورية
def log(message):
    print(message, flush=True)

# --- خادم الصحة لـ Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Advanced Bot with File Export is alive!")
    def log_message(self, format, *args): return

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- إعدادات البوت ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
MAX_CONCURRENT_SCANS = 150 # زيادة طفيفة في السرعة

async def check_port(ip, port):
    try:
        conn = asyncio.open_connection(str(ip), port)
        _, writer = await asyncio.wait_for(conn, timeout=1.0)
        writer.close()
        await writer.wait_closed()
        return str(ip)
    except:
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("8080", callback_data='8080'),
         InlineKeyboardButton("80", callback_data='80'),
         InlineKeyboardButton("443", callback_data='443')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("مرحباً بك! اختر المنفذ الذي تريد فحصه:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['selected_port'] = int(query.data)
    await query.edit_message_text(text=f"✅ تم اختيار المنفذ: {query.data}\nالآن أرسل قائمة نطاقات CIDR (كل نطاق في سطر).")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    port = context.user_data.get('selected_port')
    if not port:
        await update.message.reply_text("⚠️ يرجى اختيار المنفذ أولاً باستخدام أمر /start")
        return

    input_text = update.message.text.strip()
    cidr_list = [line.strip() for line in input_text.split('\n') if line.strip()]
    
    await update.message.reply_text(f"🚀 جاري فحص {len(cidr_list)} نطاق على المنفذ {port}...")
    
    all_found_ips = [] # قائمة لجمع كل النتائج من كل النطاقات

    for cidr in cidr_list:
        try:
            status_msg = await update.message.reply_text(f"🔍 فحص النطاق: {cidr}...")
            network = ipaddress.ip_network(cidr, strict=False)
            all_ips = list(network)
            
            for i in range(0, len(all_ips), MAX_CONCURRENT_SCANS):
                batch = all_ips[i:i+MAX_CONCURRENT_SCANS]
                tasks = [check_port(ip, port) for ip in batch]
                results = await asyncio.gather(*tasks)
                
                successful = [ip for ip in results if ip]
                all_found_ips.extend(successful)
                
                # تحديث المستخدم بالتقدم كل 50 نتيجة
                if len(successful) > 0 and len(all_found_ips) % 50 == 0:
                    log(f"Found so far: {len(all_found_ips)}")

            await status_msg.edit_text(f"🏁 اكتمل فحص {cidr}")
                
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في النطاق {cidr}: {e}")

    # بعد الانتهاء من كل النطاقات، إرسال النتائج
    if all_found_ips:
        # إنشاء ملف نصي في الذاكرة دون الحاجة لحفظه على القرص
        result_text = "\n".join(all_found_ips)
        file_content = io.BytesIO(result_text.encode('utf-8'))
        file_content.name = f"results_port_{port}.txt"
        
        await update.message.reply_text(f"✅ تم العثور على إجمالي {len(all_found_ips)} عنوان.")
        await update.message.reply_document(document=file_content, caption="إليك ملف النتائج الكاملة.")
    else:
        await update.message.reply_text("🏁 انتهى الفحص ولم يتم العثور على أي نتائج.")

if __name__ == '__main__':
    if not TOKEN:
        log("FATAL ERROR: TELEGRAM_TOKEN is missing!")
        sys.exit(1)
    
    threading.Thread(target=run_health_check_server, daemon=True).start()
    
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    log("Advanced Bot with File Export is running...")
    application.run_polling()
