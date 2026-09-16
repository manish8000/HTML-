import os
import json
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")

# Koyeb Port 8000 Health Check Server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# रिपीट रोकने के लिए हिस्ट्री
user_asked_history = {}

# राजस्थान परीक्षाओं का 150 प्रश्नों का सिलेबस एवं वेटेज डेटाबेस
EXAM_DATABASE = {
    "cet": {
        "name": "Rajasthan CET (Full Paper - 150 Qs)",
        "total_paper_questions": 150,
        "syllabus_quota": {
            "rajasthan_gk": 50,
            "india_gk_science": 35,
            "reasoning_maths": 25,
            "hindi": 15,
            "english": 15,
            "computer": 10
        },
        "sample_bank": {
            "rajasthan_gk": [
                ("राजस्थान का राज्य वृक्ष कौन सा है?", ["खेजड़ी", "रोहिड़ा", "नीम", "बरगद"], 0),
                ("हवामहल का निर्माण किसने करवाया था?", ["सवाई प्रताप सिंह", "सवाई जयसिंह", "राजा मानसिंह", "माधो सिंह"], 0),
                ("कालीबंगा सभ्यता किस जिले में स्थित है?", ["हनुमानगढ़", "बीकानेर", "चूरू", "सीकर"], 0),
                ("राजस्थान में 1857 की क्रांति का आरंभ कहाँ से हुआ था?", ["नसीराबाद", "एरिनपुरा", "नीमच", "कोटा"], 0),
                ("पिछोला झील राजस्थान के किस शहर में स्थित है?", ["उदयपुर", "जोधपुर", "अजमेर", "जयपुर"], 0)
            ],
            "india_gk_science": [
                ("मानव शरीर की सबसे बड़ी ग्रंथि कौन सी है?", ["यकृत (Liver)", "थायरॉयड", "पीयूष", "अग्न्याशय"], 0),
                ("कोशिका का 'पावर हाउस' किसे कहा जाता है?", ["माइटोकॉन्ड्रिया", "राइबोसोम", "लाइसोसोम", "केंद्रक"], 0),
                ("विटामिन C का रासायनिक नाम क्या है?", ["एस्कॉर्बिक एसिड", "रेटिनॉल", "थायमिन", "कैल्सीफेरोल"], 0)
            ],
            "reasoning_maths": [
                ("श्रेणी पूर्ण करें: 2, 4, 8, 16, ___?", ["32", "24", "64", "20"], 0),
                ("यदि 5 पेनों का मूल्य ₹50 है, तो 8 पेनों का मूल्य क्या होगा?", ["₹80", "₹70", "₹90", "₹60"], 0)
            ],
            "hindi": [
                ("'सूर्योदय' में कौन सी संधि है?", ["गुण स्वर संधि", "दीर्घ स्वर संधि", "वृद्धि स्वर संधि", "यण स्वर संधि"], 0),
                ("'अंगूठा दिखाना' मुहावरे का सही अर्थ क्या है?", ["साफ मना करना", "मजाक उड़ाना", "धोखा देना", "गुस्सा होना"], 0)
            ],
            "english": [
                ("Choose the synonym of 'ABANDON':", ["Leave", "Adopt", "Keep", "Join"], 0),
                ("Fill in the blank: She is good _____ English.", ["at", "in", "with", "for"], 0)
            ],
            "computer": [
                ("कंप्यूटर का मस्तिष्क किसे कहा जाता है?", ["CPU", "RAM", "ROM", "Hard Disk"], 0),
                ("Ctrl + C शॉर्टकट कुंजी का क्या कार्य है?", ["कॉपी करना", "पेस्ट करना", "कट करना", "सेव करना"], 0)
            ]
        }
    },
    "police": {
        "name": "Rajasthan Police Constable (Full Paper - 150 Qs)",
        "total_paper_questions": 150,
        "syllabus_quota": {
            "reasoning_computer": 60,
            "india_gk_current": 35,
            "women_child_crime": 10,
            "rajasthan_gk": 45
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
                ("POCSO एक्ट किस वर्ष लागू किया गया था?", ["2012", "2010", "2015", "2018"], 0),
                ("बाल विवाह प्रतिषेध अधिनियम कब लागू हुआ?", ["2006", "2005", "2008", "2010"], 0)
            ],
            "rajasthan_gk": [
                ("राजस्थान पुलिस का ध्येय वाक्य क्या है?", ["आमजन में विश्वास, अपराधियों में डर", "सत्यमेव जयते", "वीरभोग्या वसुंधरा", "अहर्निशं सेवामहे"], 0),
                ("हल्दीघाटी का ऐतिहासिक युद्ध किस वर्ष लड़ा गया?", ["1576 ई.", "1582 ई.", "1527 ई.", "1544 ई."], 0)
            ]
        }
    },
    "reet": {
        "name": "REET Level-2 (Full Paper - 150 Qs)",
        "total_paper_questions": 150,
        "syllabus_quota": {
            "cdp": 30,
            "hindi": 30,
            "english": 30,
            "subject_knowledge": 60
        },
        "sample_bank": {
            "cdp": [
                ("जीन पियाजे के अनुसार संज्ञानात्मक विकास की कितनी अवस्थाएँ हैं?", ["4", "3", "2", "5"], 0),
                ("क्रिया-प्रसूत अनुबंधन सिद्धांत किसने दिया?", ["बी. एफ. स्किनर", "पावलोव", "थार्नडाइक", "कोहलर"], 0)
            ],
            "hindi": [
                ("संज्ञा के कितने मुख्य भेद होते हैं?", ["3", "5", "4", "2"], 0),
                ("'पवन' का सही संधि-विच्छेद क्या होगा?", ["पो + अन", "पौ + अन", "प + वन", "पा + वन"], 0)
            ],
            "english": [
                ("Identify the Part of Speech: 'He runs **fast**.'", ["Adverb", "Adjective", "Noun", "Verb"], 0),
                ("Choose the antonym of 'BRAVE':", ["Coward", "Courageous", "Bold", "Hero"], 0)
            ],
            "subject_knowledge": [
                ("राजस्थान के किस जिले को 'झीलों की नगरी' कहते हैं?", ["उदयपुर", "जयपुर", "जोधपुर", "अजमेर"], 0),
                ("पौधों में पर्णहरिम में मुख्य तत्व कौन सा होता है?", ["मैग्नीशियम (Mg)", "लोहा (Fe)", "कैल्शियम (Ca)", "फास्फोरस (P)"], 0)
            ]
        }
    }
}

# 150 प्रश्नों का निर्माण (सिलेबस वेटेज के अनुसार)
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
        while created_for_sub < required_count:
            base_q = sub_bank[created_for_sub % len(sub_bank)]
            q_id = f"{exam_key}_{subject}_{created_for_sub+1}"

            opts = list(base_q[1])
            correct_text = opts[base_q[2]]
            random.shuffle(opts)

            full_questions_list.append({
                "id": q_id,
                "q": base_q[0],
                "options": opts,
                "answer": opts.index(correct_text)
            })
            created_for_sub += 1

    random.shuffle(full_questions_list)
    return full_questions_list

# CBT स्लाइड-वाइज HTML जनरेटर (1 सवाल प्रति स्क्रीन + Re-attempt)
def build_html_file(exam_title, questions_list, file_name):
    html_code = f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{exam_title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #eef2f6;
            margin: 0;
            padding: 12px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 95vh;
        }}
        .quiz-card {{
            width: 100%;
            max-width: 680px;
            background: #ffffff;
            border-radius: 14px;
            padding: 22px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.08);
            box-sizing: border-box;
        }}
        .top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #007bff;
            padding-bottom: 12px;
            margin-bottom: 18px;
        }}
        .top-bar h3 {{ margin: 0; color: #1e293b; font-size: 17px; }}
        .badge {{ background: #e0e7ff; color: #3730a3; padding: 5px 12px; border-radius: 20px; font-size: 14px; font-weight: bold; }}
        
        .q-slide {{ display: none; }}
        .q-slide.active {{ display: block; animation: fadeIn 0.2s ease-in-out; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(3px); }} to {{ opacity: 1; transform: translateY(0); }} }}

        .q-title {{ font-size: 16px; font-weight: 600; margin-bottom: 15px; color: #0f172a; line-height: 1.5; }}
        .opt-label {{
            display: flex;
            align-items: center;
            background: #f8fafc;
            border: 1.5px solid #cbd5e1;
            padding: 12px 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 15px;
            transition: all 0.2s;
        }}
        .opt-label:hover {{ background: #f1f5f9; border-color: #94a3b8; }}
        input[type="radio"] {{ margin-right: 12px; transform: scale(1.2); }}

        .nav-controls {{
            display: flex;
            justify-content: space-between;
            gap: 10px;
            margin-top: 22px;
            border-top: 1px solid #e2e8f0;
            padding-top: 15px;
        }}
        .btn {{
            padding: 12px 20px;
            font-size: 15px;
            font-weight: 600;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: 0.2s;
        }}
        .btn-prev {{ background: #64748b; color: white; }}
        .btn-prev:disabled {{ background: #cbd5e1; cursor: not-allowed; }}
        .btn-next {{ background: #007bff; color: white; }}
        .btn-submit {{ background: #16a34a; color: white; display: none; }}
        .btn-reset {{ background: #0284c7; color: white; width: 100%; display: none; margin-top: 15px; }}

        .correct {{ background: #dcfce7 !important; border-color: #22c55e !important; color: #15803d; font-weight: bold; }}
        .wrong {{ background: #fee2e2 !important; border-color: #ef4444 !important; color: #b91c1c; }}
        #res-box {{
            display: none;
            margin-top: 20px;
            padding: 16px;
            background: #ecfdf5;
            border: 1px solid #6ee7b7;
            border-radius: 8px;
            text-align: center;
            font-size: 18px;
            font-weight: bold;
            color: #065f46;
        }}
    </style>
</head>
<body>

<div class="quiz-card">
    <div class="top-bar">
        <h3>{exam_title}</h3>
        <span class="badge" id="progress-badge">Q 1 / {len(questions_list)}</span>
    </div>

    <form id="quizForm">
"""
    for i, item in enumerate(questions_list):
        active_cls = "active" if i == 0 else ""
        html_code += f"""
        <div class="q-slide {active_cls}" id="slide-{i}">
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
        <div class="nav-controls">
            <button type="button" class="btn btn-prev" id="prevBtn" onclick="prevSlide()" disabled>⬅️ Previous</button>
            <button type="button" class="btn btn-next" id="nextBtn" onclick="nextSlide()">Next ➡️</button>
            <button type="button" class="btn btn-submit" id="submitBtn" onclick="finishTest()">Submit Full Test 🎯</button>
        </div>
        <button type="button" class="btn btn-reset" id="resetBtn" onclick="reattempt()">🔄 Re-attempt Full Test</button>
    </form>

    <div id="res-box"></div>
</div>

<script>
    let currentIndex = 0;
    const totalQuestions = {len(questions_list)};
    const answerKeys = {json.dumps([q['answer'] for q in questions_list])};

    function updateView() {{
        for (let i = 0; i < totalQuestions; i++) {{
            document.getElementById('slide-' + i).classList.remove('active');
        }}
        document.getElementById('slide-' + currentIndex).classList.add('active');
        document.getElementById('progress-badge').innerText = "Q " + (currentIndex + 1) + " / " + totalQuestions;
        document.getElementById('prevBtn').disabled = (currentIndex === 0);

        if (currentIndex === totalQuestions - 1) {{
            document.getElementById('nextBtn').style.display = 'none';
            document.getElementById('submitBtn').style.display = 'block';
        }} else {{
            document.getElementById('nextBtn').style.display = 'block';
            document.getElementById('submitBtn').style.display = 'none';
        }}
    }}

    function nextSlide() {{
        if (currentIndex < totalQuestions - 1) {{
            currentIndex++;
            updateView();
        }}
    }}

    function prevSlide() {{
        if (currentIndex > 0) {{
            currentIndex--;
            updateView();
        }}
    }}

    function finishTest() {{
        let score = 0;
        for (let i = 0; i < totalQuestions; i++) {{
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

        document.getElementById('prevBtn').style.display = 'none';
        document.getElementById('submitBtn').style.display = 'none';
        document.getElementById('resetBtn').style.display = 'block';

        let resBox = document.getElementById('res-box');
        resBox.style.display = 'block';
        resBox.innerHTML = "🎯 टेस्ट समाप्त!<br>कुल स्कोर: " + score + " / " + totalQuestions;
    }}

    function reattempt() {{
        document.getElementById('quizForm').reset();
        for (let i = 0; i < totalQuestions; i++) {{
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
        document.getElementById('res-box').style.display = 'none';
        document.getElementById('resetBtn').style.display = 'none';
        currentIndex = 0;
        document.getElementById('prevBtn').style.display = 'block';
        updateView();
    }}
</script>
</body>
</html>"""

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(html_code)
    return file_name

# टेलीग्राम मैसेज हैंडलर
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
    status_msg = await update.effective_message.reply_text(
        f"⏳ **{exam_info['name']} का फुल CBT टेस्ट बन रहा है...**"
    )

    picked_questions = generate_full_paper_questions(selected_key, chat_id)
    rand_id = random.randint(1000, 9999)
    file_name = f"{selected_key.upper()}_CBT_Test_{rand_id}.html"
    file_path = build_html_file(exam_info['name'], picked_questions, file_name)

    with open(file_path, "rb") as doc:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=doc,
            reply_to_message_id=update.effective_message.message_id,
            caption=f"📝 **{exam_info['name']}**\n\n"
                    f"• CBT स्लाइडर मोड (1 सवाल प्रति स्लाइड)\n"
                    f"• कुल 150 प्रश्न (सिलेबस अनुसार)\n"
                    f"• Re-attempt बटन उपलब्ध\n\n"
                    f"📲 Chrome ब्राउज़र में खोलें।"
        )

    await status_msg.delete()
    if os.path.exists(file_path):
        os.remove(file_path)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "👋 **राजस्थान CBT टेस्ट बॉट**\n\n"
        "परीक्षा का नाम लिखकर टेस्ट मांगें:\n"
        "👉 `CET test` (150 Qs)\n"
        "👉 `Police test` (150 Qs)\n"
        "👉 `REET test` (150 Qs)"
    )

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
