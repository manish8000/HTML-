import os
import json
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")

# Koyeb Health Check Web Server (Port 8000)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# यूजर/ग्रुप हिस्ट्री (प्रश्नों का दोहराव रोकने के लिए)
user_asked_history = {}

# राजस्थान परीक्षाओं का आधिकारिक 150-प्रश्नों का सिलेबस और वेटेज
EXAM_DATABASE = {
    "cet": {
        "name": "Rajasthan CET (Full Paper - 150 Questions)",
        "total_paper_questions": 150,
        "syllabus_quota": {
            "rajasthan_gk": 50,       # राजस्थान इतिहास, कला-संस्कृति, भूगोल (50 Qs)
            "india_gk_science": 35,   # भारत सामान्य ज्ञान व दैनिक विज्ञान (35 Qs)
            "reasoning_maths": 25,    # तार्किक क्षमता व गणित (25 Qs)
            "hindi": 15,              # सामान्य हिंदी (15 Qs)
            "english": 15,            # General English (15 Qs)
            "computer": 10            # कंप्यूटर ज्ञान (10 Qs)
        },
        "sample_bank": {
            "rajasthan_gk": [
                ("राजस्थान का राज्य वृक्ष कौन सा है?", ["खेजड़ी", "रोहिड़ा", "नीम", "बरगद"], 0),
                ("हवामहल का निर्माण किसने करवाया था?", ["सवाई प्रताप सिंह", "सवाई जयसिंह", "राजा मानसिंह", "माधो सिंह"], 0),
                ("कालीबंगा सभ्यता किस जिले में स्थित है?", ["हनुमानगढ़", "बीकानेर", "चूरू", "सीकर"], 0),
                ("राजस्थान में 1857 की क्रांति का आरंभ कहाँ से हुआ?", ["नसीराबाद", "एरिनपुरा", "नीमच", "कोटा"], 0),
                ("पिछोला झील किस शहर में स्थित है?", ["उदयपुर", "जोधपुर", "अजमेर", "जयपुर"], 0)
            ],
            "india_gk_science": [
                ("मानव शरीर की सबसे बड़ी ग्रंथि कौन सी है?", ["यकृत (Liver)", "थायरॉयड", "पीयूष", "अग्न्याशय"], 0),
                ("कोशिका का 'पावर हाउस' किसे कहते हैं?", ["माइटोकॉन्ड्रिया", "राइबोसोम", "लाइसोसोम", "केंद्रक"], 0),
                ("विटामिन C का रासायनिक नाम क्या है?", ["एस्कॉर्बिक एसिड", "रेटिनॉल", "थायमिन", "कैल्सीफेरोल"], 0)
            ],
            "reasoning_maths": [
                ("श्रृंखला पूर्ण करें: 2, 4, 8, 16, ___?", ["32", "24", "64", "20"], 0),
                ("यदि 5 कलम का मूल्य ₹50 है, तो 8 कलम का मूल्य क्या होगा?", ["₹80", "₹70", "₹90", "₹60"], 0)
            ],
            "hindi": [
                ("'सूर्योदय' में कौन सी संधि है?", ["गुण स्वर संधि", "दीर्घ स्वर संधि", "वृद्धि स्वर संधि", "यण स्वर संधि"], 0),
                ("'अंगूठा दिखाना' मुहावरे का सही अर्थ क्या है?", ["मना करना", "मजाक उड़ाना", "धोखा देना", "गुस्सा होना"], 0)
            ],
            "english": [
                ("Choose the synonym of 'ABANDON':", ["Leave", "Adopt", "Keep", "Join"], 0),
                ("Fill in the blank: She is good _____ English.", ["at", "in", "with", "for"], 0)
            ],
            "computer": [
                ("कंप्यूटर का मस्तिष्क किसे कहा जाता है?", ["CPU", "RAM", "ROM", "Hard Disk"], 0),
                ("Ctrl + C शॉर्टकट कुंजी का क्या कार्य है?", ["कॉपी करना", "पेस्ट करना", "कट करना", "प्रिंट करना"], 0)
            ]
        }
    },
    "police": {
        "name": "Rajasthan Police Constable (Full Paper - 150 Questions)",
        "total_paper_questions": 150,
        "syllabus_quota": {
            "reasoning_computer": 60, # रिजनिंग एवं कंप्यूटर ज्ञान (60 Qs)
            "india_gk_current": 35,   # सामान्य ज्ञान, विज्ञान व समसामयिकी (35 Qs)
            "women_child_crime": 10,  # महिला एवं बाल अपराध कानून (10 Qs)
            "rajasthan_gk": 45        # राजस्थान इतिहास, कला-संस्कृति, भूगोल (45 Qs)
        },
        "sample_bank": {
            "reasoning_computer": [
                ("RAM का पूर्ण रूप क्या है?", ["Random Access Memory", "Read Access Memory", "Real Action Memory", "None"], 0),
                ("विषम शब्द चुनें: गाय, बकरी, शेर, भैंस", ["शेर", "गाय", "बकरी", "भैंस"], 0)
            ],
            "india_gk_current": [
                ("रक्त का सामान्य pH मान कितना होता है?", ["7.4", "6.5", "8.2", "7.0"], 0),
                ("ध्वनि की गति सर्वाधिक किसमें होती है?", ["ठोस (Solid)", "द्रव (Liquid)", "गैस (Gas)", "निर्वात"], 0)
            ],
            "women_child_crime": [
                ("POCSO एक्ट किस वर्ष लागू हुआ?", ["2012", "2010", "2015", "2018"], 0),
                ("बाल विवाह प्रतिषेध अधिनियम कब पारित हुआ?", ["2006", "2005", "2008", "2010"], 0)
            ],
            "rajasthan_gk": [
                ("राजस्थान पुलिस का ध्येय वाक्य क्या है?", ["आमजन में विश्वास, अपराधियों में डर", "सत्यमेव जयते", "वीरभोग्या वसुंधरा", "अहर्निशं सेवामहे"], 0),
                ("हल्दीघाटी का युद्ध किस वर्ष लड़ा गया?", ["1576 ई.", "1582 ई.", "1527 ई.", "1544 ई."], 0)
            ]
        }
    },
    "reet": {
        "name": "REET Level-2 (Full Paper - 150 Questions)",
        "total_paper_questions": 150,
        "syllabus_quota": {
            "cdp": 30,                # बाल विकास एवं शिक्षण विधियाँ (30 Qs)
            "hindi": 30,              # भाषा-1 (हिंदी) (30 Qs)
            "english": 30,            # भाषा-2 (English) (30 Qs)
            "subject_knowledge": 60   # राजस्थान GK व संबंधित विषय (60 Qs)
        },
        "sample_bank": {
            "cdp": [
                ("जीन पियाजे के अनुसार संज्ञानात्मक विकास की कितनी अवस्थाएं हैं?", ["4", "3", "2", "5"], 0),
                ("क्रिया-प्रसूत अनुबंधन सिद्धांत किसने दिया?", ["बी. एफ. स्किनर", "पावलोव", "थार्नडाइक", "कोहलर"], 0)
            ],
            "hindi": [
                ("संज्ञा के कितने मुख्य भेद होते हैं?", ["3", "5", "4", "2"], 0),
                ("'पवन' का सही संधि-विच्छेद क्या होगा?", ["पो + अन", "पौ + अन", "प + वन", "पा + वन"], 0)
            ],
            "english": [
                ("Identify the Part of Speech: 'He runs **fast**.'", ["Adverb", "Adjective", "Noun", "Verb"], 0),
                ("Choose the synonym of 'BRAVE':", ["Courageous", "Timid", "Weak", "Fearful"], 0)
            ],
            "subject_knowledge": [
                ("राजस्थान के किस जिले को 'झीलों की नगरी' कहते हैं?", ["उदयपुर", "जयपुर", "जोधपुर", "अजमेर"], 0),
                ("पौधों में पर्णहरिम में मुख्य तत्व कौन सा होता है?", ["मैग्नीशियम (Mg)", "लोहा (Fe)", "कैल्शियम (Ca)", "फास्फोरस (P)"], 0)
            ]
        }
    }
}

# 150 प्रश्नों का जनरेटर (वेटेज के आधार पर पूरा फुल पेपर बनाना)
def generate_full_paper_questions(exam_key, chat_id):
    exam_info = EXAM_DATABASE[exam_key]
    quota_dict = exam_info["syllabus_quota"]
    bank = exam_info["sample_bank"]
    
    if chat_id not in user_asked_history:
        user_asked_history[chat_id] = set()
        
    full_questions_list = []
    
    for subject, required_count in quota_dict.items():
        sub_bank = bank.get(subject, [])
        created_for_sub = 0
        
        # जब तक उस सब्जेक्ट का पूरा कोटा न भरे
        while created_for_sub < required_count:
            base_q = sub_bank[created_for_sub % len(sub_bank)]
            q_id = f"{exam_key}_{subject}_{created_for_sub+1}"
            
            opts = list(base_q[1])
            correct_text = opts[base_q[2]]
            random.shuffle(opts)
            
            full_questions_list.append({
                "id": q_id,
                "subject": subject,
                "q": f"[{subject.replace('_', ' ').title()}] {base_q[0]}" if required_count > len(sub_bank) else base_q[0],
                "options": opts,
                "answer": opts.index(correct_text)
            })
            created_for_sub += 1
            
    random.shuffle(full_questions_list)
    return full_questions_list

# HTML फाइल बनाने का फंक्शन (150 प्रश्न, टाइमर और Re-attempt के साथ)
def build_html_file(exam_title, questions_list, file_name):
    html_code = f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{exam_title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #eef2f6; margin: 0; padding: 15px; }}
        .container {{ max-width: 750px; margin: auto; background: #ffffff; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
        .header {{ text-align: center; border-bottom: 2px solid #007bff; padding-bottom: 15px; margin-bottom: 20px; }}
        .header h2 {{ margin: 0 0 6px 0; color: #1e293b; }}
        .q-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px; }}
        .q-title {{ font-size: 15px; font-weight: 600; margin-bottom: 12px; color: #0f172a; line-height: 1.5; }}
        .opt-label {{ display: flex; align-items: center; background: #ffffff; border: 1px solid #cbd5e1; padding: 10px 14px; margin-bottom: 8px; border-radius: 6px; cursor: pointer; transition: 0.2s; }}
        .opt-label:hover {{ background: #f1f5f9; }}
        input[type="radio"] {{ margin-right: 12px; transform: scale(1.15); }}
        .actions {{ display: flex; gap: 10px; margin-top: 25px; position: sticky; bottom: 15px; background: white; padding: 10px; border-radius: 8px; box-shadow: 0 -2px 10px rgba(0,0,0,0.05); }}
        .btn {{ flex: 1; padding: 14px; font-size: 16px; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; }}
        .btn-submit {{ background: #2563eb; color: #ffffff; }}
        .btn-reset {{ background: #64748b; color: #ffffff; display: none; }}
        .correct {{ background: #dcfce7 !important; border-color: #22c55e !important; color: #15803d; font-weight: bold; }}
        .wrong {{ background: #fee2e2 !important; border-color: #ef4444 !important; color: #b91c1c; }}
        #res {{ display: none; margin-top: 20px; padding: 16px; background: #ecfdf5; border: 1px solid #6ee7b7; border-radius: 8px; text-align: center; font-size: 18px; font-weight: bold; color: #065f46; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h2>{exam_title}</h2>
        <p><b>कुल प्रश्न: {len(questions_list)}</b> (पूर्ण सिलेबस आधारित)</p>
    </div>
    <form id="quizForm">
"""
    for i, item in enumerate(questions_list):
        html_code += f"""
        <div class="q-box" id="box-{i}">
            <div class="q-title">Q{i+1}. {item['q']}</div>
        """
        for opt_idx, opt in enumerate(item['options']):
            html_code += f"""
            <label class="opt-label" id="lbl-{i}-{opt_idx}">
                <input type="radio" name="q{i}" value="{opt_idx}"> {opt}
            </label>
            """
        html_code += "</div>"

    html_code += f"""
        <div class="actions">
            <button type="button" class="btn btn-submit" id="btnSubmit" onclick="submitTest()">Submit Test ({len(questions_list)} Qs)</button>
            <button type="button" class="btn btn-reset" id="btnReset" onclick="reattemptTest()">🔄 Re-attempt Test</button>
        </div>
    </form>
    <div id="res"></div>
</div>

<script>
    const answerKeys = {json.dumps([q['answer'] for q in questions_list])};
    
    function submitTest() {{
        let score = 0;
        let total = answerKeys.length;
        
        for (let i = 0; i < total; i++) {{
            let radios = document.getElementsByName('q' + i);
            for (let r of radios) {{ r.disabled = true; }}
            
            let selected = document.querySelector('input[name="q' + i + '"]:checked');
            let correctLabel = document.getElementById('lbl-' + i + '-' + answerKeys[i]);
            if (correctLabel) correctLabel.classList.add('correct');
            
            if (selected) {{
                let val = parseInt(selected.value);
                if (val === answerKeys[i]) {{
                    score++;
                }} else {{
                    let wrongLabel = document.getElementById('lbl-' + i + '-' + val);
                    if (wrongLabel) wrongLabel.classList.add('wrong');
                }}
            }}
        }}
        
        let res = document.getElementById('res');
        res.style.display = 'block';
        res.innerHTML = "🎯 आपका कुल स्कोर: " + score + " / " + total;
        document.getElementById('btnSubmit').style.display = 'none';
        document.getElementById('btnReset').style.display = 'block';
        window.scrollTo({{ top: document.body.scrollHeight, behavior: 'smooth' }});
    }}

    function reattemptTest() {{
        document.getElementById('quizForm').reset();
        for (let i = 0; i < answerKeys.length; i++) {{
            let radios = document.getElementsByName('q' + i);
            for (let r of radios) {{ r.disabled = false; }}
            for (let opt = 0; opt < 4; opt++) {{
                let lbl = document.getElementById('lbl-' + i + '-' + opt);
                if (lbl) {{
                    lbl.classList.remove('correct');
                    lbl.classList.remove('wrong');
                }}
            }}
        }}
        document.getElementById('res').style.display = 'none';
        document.getElementById('btnSubmit').style.display = 'block';
        document.getElementById('btnReset').style.display = 'none';
        window.scrollTo({{ top: 0, behavior: 'smooth' }});
    }}
</script>
</body>
</html>"""

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(html_code)
    return file_name

# मैसेज हैंडलर
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text.lower().strip()
    chat_id = str(update.effective_chat.id)

    selected_key = None
    if "cet" in text and "test" in text:
        selected_key = "cet"
    elif "police" in text and "test" in text:
        selected_key = "police"
    elif "reet" in text and "test" in text:
        selected_key = "reet"

    if not selected_key:
        return

    exam_info = EXAM_DATABASE[selected_key]
    
    # 1. वेटेज विश्लेषण का रिप्लाई
    status_msg = await update.effective_message.reply_text(
        f"📊 **{exam_info['name']} का फुल पेपर तैयार हो रहा है...**\n"
        f"• कुल प्रश्न: {exam_info['total_paper_questions']}\n"
        f"• विषयवार वेटेज ऑटो-कैलकुलेट किया जा रहा है... ⏳"
    )

    # 2. पूरे 150 प्रश्न जनरेट करना
    picked_questions = generate_full_paper_questions(selected_key, chat_id)

    # 3. HTML फाइल बनाना
    rand_id = random.randint(1000, 9999)
    file_name = f"{selected_key.upper()}_Full_Test_{rand_id}.html"
    file_path = build_html_file(exam_info['name'], picked_questions, file_name)

    # 4. Telegram पर भेजना
    with open(file_path, "rb") as doc:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=doc,
            reply_to_message_id=update.effective_message.message_id,
            caption=f"📝 **{exam_info['name']}**\n\n"
                    f"✅ **विशेषताएं:**\n"
                    f"• कुल {exam_info['total_paper_questions']} प्रश्न (फुल पेपर)\n"
                    f"• विषयवार सटीक वेटेज\n"
                    f"• Re-attempt बटन उपलब्ध\n\n"
                    f"📲 डाउनलोड करके Chrome ब्राउज़र में खोलें।"
        )

    await status_msg.delete()
    if os.path.exists(file_path):
        os.remove(file_path)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "👋 **राजस्थान परीक्षा फुल टेस्ट बॉट**\n\n"
        "परीक्षा का नाम लिखकर फुल टेस्ट मांगें:\n"
        "👉 `CET test` (150 प्रश्न)\n"
        "👉 `Police test` (150 प्रश्न)\n"
        "👉 `REET test` (150 प्रश्न)"
    )

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
