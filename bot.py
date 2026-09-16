import os
import json
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")

# Koyeb Health Check के लिए छोटा सा Fake Web Server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# HTML जनरेट करने का फंक्शन
def generate_mock_test_html(file_name="CET_Mock_Test.html"):
    questions = [
        {
            "q": "राजस्थान का राज्य पशु कौन सा है?",
            "options": ["बाघ", "चिंकारा", "गाय", "हाथी"],
            "answer": 1
        },
        {
            "q": "हवामहल किस शहर में स्थित है?",
            "options": ["उदयपुर", "जोधपुर", "जयपुर", "अजमेर"],
            "answer": 2
        },
        {
            "q": "मानव शरीर की सबसे बड़ी ग्रंथि कौन सी है?",
            "options": ["थायरॉयड", "यकृत (Liver)", "अग्न्याशय", "पीयूष"],
            "answer": 1
        }
    ]

    html_template = f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CET Mock Test</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #f3f4f6; margin: 0; padding: 15px; }}
        .container {{ max-width: 600px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
        .q-box {{ background: #fafafa; border: 1px solid #ddd; border-radius: 8px; padding: 12px; margin-bottom: 12px; }}
        .opt-label {{ display: block; background: #fff; border: 1px solid #ccc; padding: 8px 12px; margin: 6px 0; border-radius: 5px; cursor: pointer; }}
        .btn {{ width: 100%; padding: 12px; background: #007bff; color: white; border: none; border-radius: 6px; font-size: 16px; cursor: pointer; font-weight: bold; }}
        .correct {{ background: #d4edda !important; border-color: #28a745 !important; font-weight: bold; }}
        .wrong {{ background: #f8d7da !important; border-color: #dc3545 !important; }}
        #res {{ display: none; margin-top: 15px; padding: 12px; background: #e2f0d9; text-align: center; border-radius: 6px; font-weight: bold; }}
    </style>
</head>
<body>
<div class="container">
    <h2 style="text-align:center;">CET Mock Test 2026</h2>
    <form id="quiz">
"""
    for i, item in enumerate(questions):
        html_template += f"""
        <div class="q-box">
            <p><b>Q{i+1}. {item['q']}</b></p>
        """
        for opt_idx, opt in enumerate(item['options']):
            html_template += f"""
            <label class="opt-label" id="l-{i}-{opt_idx}">
                <input type="radio" name="q{i}" value="{opt_idx}"> {opt}
            </label>
            """
        html_template += "</div>"

    html_template += f"""
        <button type="button" class="btn" onclick="checkTest()">Submit Test</button>
    </form>
    <div id="res"></div>
</div>
<script>
    const keys = {json.dumps([q['answer'] for q in questions])};
    function checkTest() {{
        let score = 0;
        for(let i=0; i<keys.length; i++) {{
            let sel = document.querySelector('input[name="q'+i+'"]:checked');
            let correctEl = document.getElementById('l-' + i + '-' + keys[i]);
            if(correctEl) correctEl.classList.add('correct');
            if(sel) {{
                let val = parseInt(sel.value);
                if(val === keys[i]) {{ score++; }}
                else {{
                    let wrongEl = document.getElementById('l-' + i + '-' + val);
                    if(wrongEl) wrongEl.classList.add('wrong');
                }}
            }}
        }}
        let resDiv = document.getElementById('res');
        resDiv.style.display = 'block';
        resDiv.innerHTML = "स्कोर: " + score + " / " + keys.length;
    }}
</script>
</body>
</html>"""

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(html_template)
    return file_name

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("नमस्ते! CET Mock Test HTML पाने के लिए /test भेजें।")

async def send_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg_id = update.effective_message.message_id
    status_msg = await update.effective_message.reply_text("⏳ HTML टेस्ट तैयार हो रहा है...")
    
    try:
        file_path = generate_mock_test_html("CET_Mock_Test_07.html")
        with open(file_path, "rb") as doc:
            await context.bot.send_document(
                chat_id=chat_id,
                document=doc,
                reply_to_message_id=msg_id,
                caption="📝 CET Mock Test तैयार है! इसे Chrome में खोलें।"
            )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"त्रुटि: {e}")

def main():
    # बैकग्राउंड में वेब सर्वर चालू करें ताकि Koyeb को 200 OK मिल जाए
    server_thread = threading.Thread(target=run_health_server, daemon=True)
    server_thread.start()

    # टेलीग्राम बॉट चलाएं
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", send_test))
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
        
