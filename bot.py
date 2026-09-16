import os
import json
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Koyeb के Environment Variables से टोकन लोड होगा
TOKEN = os.environ.get("BOT_TOKEN")

def generate_mock_test_html(file_name="CET_Mock_Test.html"):
    # टेस्ट के प्रश्न और विकल्प
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
        },
        {
            "q": "विटामिन C का रासायनिक नाम क्या है?",
            "options": ["रेटिनॉल", "थायमिन", "एस्कॉर्बिक एसिड", "कैल्सीफेरोल"],
            "answer": 2
        }
    ]

    html_template = f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CET Online Mock Test</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #eef2f5; margin: 0; padding: 15px; }}
        .container {{ max-width: 650px; margin: auto; background: #ffffff; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
        .header {{ text-align: center; border-bottom: 2px solid #007bff; padding-bottom: 12px; margin-bottom: 20px; }}
        .header h2 {{ margin: 0 0 5px 0; color: #1e293b; }}
        .header p {{ margin: 0; color: #64748b; font-size: 14px; }}
        .q-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px; }}
        .q-title {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; color: #0f172a; }}
        .opt-label {{ display: flex; align-items: center; background: #ffffff; border: 1px solid #cbd5e1; padding: 10px 14px; margin-bottom: 8px; border-radius: 6px; cursor: pointer; transition: background 0.2s; }}
        .opt-label:hover {{ background: #f1f5f9; }}
        input[type="radio"] {{ margin-right: 12px; transform: scale(1.15); }}
        .btn-submit {{ width: 100%; background: #2563eb; color: #ffffff; padding: 14px; font-size: 16px; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; transition: background 0.2s; }}
        .btn-submit:hover {{ background: #1d4ed8; }}
        .correct {{ background: #dcfce7 !important; border-color: #22c55e !important; color: #15803d; font-weight: 600; }}
        .wrong {{ background: #fee2e2 !important; border-color: #ef4444 !important; color: #b91c1c; }}
        #res {{ display: none; margin-top: 20px; padding: 15px; background: #ecfdf5; border: 1px solid #6ee7b7; border-radius: 8px; text-align: center; font-size: 18px; font-weight: bold; color: #065f46; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h2>CET Mock Test 2026</h2>
        <p>कुल प्रश्न: {len(questions)} | समय: असीमित (Self-Paced)</p>
    </div>
    <form id="quiz">
"""
    for i, item in enumerate(questions):
        html_template += f"""
        <div class="q-box">
            <div class="q-title">Q{i+1}. {item['q']}</div>
        """
        for opt_idx, opt in enumerate(item['options']):
            html_template += f"""
            <label class="opt-label" id="l-{i}-{opt_idx}">
                <input type="radio" name="q{i}" value="{opt_idx}"> {opt}
            </label>
            """
        html_template += "</div>"

    html_template += f"""
        <button type="button" class="btn-submit" onclick="checkScore()">Submit Test</button>
    </form>
    <div id="res"></div>
</div>

<script>
    const keys = {json.dumps([q['answer'] for q in questions])};
    function checkScore() {{
        let score = 0;
        for(let i = 0; i < keys.length; i++) {{
            let sel = document.querySelector('input[name="q' + i + '"]:checked');
            let correctEl = document.getElementById('l-' + i + '-' + keys[i]);
            if (correctEl) correctEl.classList.add('correct');
            
            if (sel) {{
                let val = parseInt(sel.value);
                if (val === keys[i]) {{
                    score++;
                }} else {{
                    let wrongEl = document.getElementById('l-' + i + '-' + val);
                    if (wrongEl) wrongEl.classList.add('wrong');
                }}
            }}
        }}
        let resDiv = document.getElementById('res');
        resDiv.style.display = 'block';
        resDiv.innerHTML = "आपका स्कोर: " + score + " / " + keys.length + "<br>" + 
                           (score === keys.length ? "शानदार तैयारी! 🎯" : "रिवीजन जारी रखें! 💪");
        window.scrollTo({{ top: document.body.scrollHeight, behavior: 'smooth' }});
    }}
</script>
</body>
</html>"""

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(html_template)
    return file_name

# /start कमांड
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "👋 स्वागत है! CET Mock Test HTML पाने के लिए ग्रुप या चैट में /test टाइप करें।"
    )

# /test कमांड (ग्रुप और पर्सनल चैट दोनों के लिए)
async def send_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg_id = update.effective_message.message_id
    
    # 1. प्रोसेस मैसेज
    status_msg = await update.effective_message.reply_text("⏳ HTML टेस्ट तैयार हो रहा है...")
    
    try:
        # 2. फ़ाइल जनरेट करें
        file_path = generate_mock_test_html("CET_Mock_Test_07.html")
        
        # 3. फ़ाइल भेजें (ग्रुप में उसी मैसेज पर रिप्लाई होगा)
        with open(file_path, "rb") as doc:
            await context.bot.send_document(
                chat_id=chat_id,
                document=doc,
                reply_to_message_id=msg_id,
                caption="📝 **CET Mock Test**\n\nइसे डाउनलोड करें और किसी भी ब्राउज़र (Chrome) में खोलकर टेस्ट दें।"
            )
        
        # 4. प्रोसेस मैसेज डिलीट करें
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit_text(f"❌ टेस्ट भेजने में त्रुटि हुई: {e}")

def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN सेट नहीं है! Koyeb के Environment Variables में इसे जोड़ें।")
        
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", send_test))
    
    print("Bot चालू है...")
    app.run_polling()

if __name__ == "__main__":
    main()
      
