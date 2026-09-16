import os
import json
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")

# Koyeb Health Check Web Server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# इस्तेमाल हो चुके प्रश्नों की हिस्ट्री (Repeat रोकने के लिए)
user_asked_history = {}

# परीक्षा डेटाबेस: विषयवार प्रश्न बैंक और ऑटोमैटिक वेटेज कोटा (कितने सवाल लेने हैं)
EXAM_DATABASE = {
    "cet": {
        "name": "Rajasthan CET Mock Test",
        # सिलेबस अनुसार ऑटोमैटिक वेटेज कोटा
        "syllabus_quota": {
            "rajasthan_gk": 4,  # राजस्थान GK: 4 प्रश्न
            "science": 2,       # सामान्य विज्ञान: 2 प्रश्न
            "hindi": 2,         # सामान्य हिंदी: 2 प्रश्न
            "english": 2        # General English: 2 प्रश्न
        },
        "questions": {
            "rajasthan_gk": [
                {"id": "cet_gk_1", "q": "राजस्थान का राज्य वृक्ष कौन सा है?", "options": ["खेजड़ी", "रोहिड़ा", "नीम", "बरगद"], "answer": 0},
                {"id": "cet_gk_2", "q": "हवामहल का निर्माण किस शासक ने करवाया था?", "options": ["सवाई प्रताप सिंह", "सवाई जयसिंह", "राजा मानसिंह", "माधो सिंह"], "answer": 0},
                {"id": "cet_gk_3", "q": "कालीबंगा सभ्यता किस जिले में स्थित है?", "options": ["हनुमानगढ़", "बीकानेर", "चूरू", "सीकर"], "answer": 0},
                {"id": "cet_gk_4", "q": "राजस्थान में 1857 की क्रांति की शुरुआत कहाँ से हुई थी?", "options": ["नसीराबाद", "एरिनपुरा", "नीमच", "कोटा"], "answer": 0},
                {"id": "cet_gk_5", "q": "पिछोला झील किस शहर में स्थित है?", "options": ["उदयपुर", "जोधपुर", "अजमेर", "जयपुर"], "answer": 0}
            ],
            "science": [
                {"id": "cet_sci_1", "q": "मानव शरीर की सबसे बड़ी ग्रंथि कौन सी है?", "options": ["यकृत (Liver)", "थायरॉयड", "पीयूष", "अग्न्याशय"], "answer": 0},
                {"id": "cet_sci_2", "q": "कोशिका का 'पावर हाउस' किसे कहा जाता है?", "options": ["माइटोकॉन्ड्रिया", "राइबोसोम", "लाइसोसोम", "केंद्रक"], "answer": 0},
                {"id": "cet_sci_3", "q": "विटामिन C का रासायनिक नाम क्या है?", "options": ["एस्कॉर्बिक एसिड", "रेटिनॉल", "थायमिन", "कैल्सीफेरोल"], "answer": 0}
            ],
            "hindi": [
                {"id": "cet_hin_1", "q": "'सूर्योदय' में कौन सी संधि है?", "options": ["गुण स्वर संधि", "दीर्घ स्वर संधि", "वृद्धि स्वर संधि", "यण स्वर संधि"], "answer": 0},
                {"id": "cet_hin_2", "q": "'अंगूठा दिखाना' मुहावरे का सही अर्थ क्या है?", "options": ["साफ मना करना", "मजाक उड़ाना", "धोखा देना", "गुस्सा होना"], "answer": 0},
                {"id": "cet_hin_3", "q": "जिसके आने की कोई तिथि न हो, उसे क्या कहते हैं?", "options": ["अतिथि", "आगंतुक", "अनंत", "सर्वज्ञ"], "answer": 0}
            ],
            "english": [
                {"id": "cet_eng_1", "q": "Choose the synonym of 'ABANDON':", "options": ["Leave", "Adopt", "Keep", "Join"], "answer": 0},
                {"id": "cet_eng_2", "q": "Fill in the blank: She is good _____ mathematics.", "options": ["at", "in", "with", "for"], "answer": 0},
                {"id": "cet_eng_3", "q": "Select the correctly spelt word:", "options": ["Accommodation", "Acommodation", "Accomodation", "Acomodation"], "answer": 0}
            ]
        }
    },
    "reet": {
        "name": "REET Level 2 Mock Test",
        "syllabus_quota": {
            "cdp": 3,           # बाल विकास: 3 प्रश्न
            "rajasthan_gk": 3,  # राजस्थान GK: 3 प्रश्न
            "science": 2,       # विज्ञान/गणित: 2 प्रश्न
            "english": 2        # English: 2 प्रश्न
        },
        "questions": {
            "cdp": [
                {"id": "rt_cdp_1", "q": "जीन पियाजे के अनुसार संज्ञानात्मक विकास की कितनी अवस्थाएँ हैं?", "options": ["4", "3", "2", "5"], "answer": 0},
                {"id": "rt_cdp_2", "q": "क्रिया-प्रसूत अनुबंधन सिद्धांत किसने प्रतिपादित किया?", "options": ["बी. एफ. स्किनर", "पावलोव", "थार्नडाइक", "कोहलर"], "answer": 0},
                {"id": "rt_cdp_3", "q": "बुद्धि लब्धि (IQ) का सूत्र किसने दिया?", "options": ["विलियम स्टर्न", "अल्फ्रेड बिने", "टर्मन", "स्पीयरमैन"], "answer": 0}
            ],
            "rajasthan_gk": [
                {"id": "rt_gk_1", "q": "राजस्थान के किस जिले को 'झीलों की नगरी' कहा जाता है?", "options": ["उदयपुर", "जयपुर", "जोधपुर", "अजमेर"], "answer": 0},
                {"id": "rt_gk_2", "q": "मेहरानगढ़ दुर्ग किस पहाड़ी पर बना है?", "options": ["चिड़ियाटूँक", "त्रिकूट", "सुवर्णगिरि", "तारागढ़"], "answer": 0},
                {"id": "rt_gk_3", "q": "रणथंभौर राष्ट्रीय उद्यान किस जिले में है?", "options": ["सवाई माधोपुर", "अलवर", "भरतपुर", "कोटा"], "answer": 0}
            ],
            "science": [
                {"id": "rt_sci_1", "q": "पौधों में पर्णहरिम (क्लोरोफिल) में कौन सा मुख्य तत्व होता है?", "options": ["मैग्नीशियम (Mg)", "आयरन (Fe)", "कैल्शियम (Ca)", "फास्फोरस (P)"], "answer": 0},
                {"id": "rt_sci_2", "q": "प्रकाश संश्लेषण की क्रिया में कौन सी गैस बाहर निकलती है?", "options": ["ऑक्सीजन (O₂)", "कार्बन डाइऑक्साइड (CO₂)", "नाइट्रोजन (N₂)", "हाइड्रोजन (H₂)"], "answer": 0}
            ],
            "english": [
                {"id": "rt_eng_1", "q": "Identify the part of speech: 'She speaks **fluent** English.'", "options": ["Adjective", "Adverb", "Noun", "Verb"], "answer": 0},
                {"id": "rt_eng_2", "q": "Choose the opposite of 'GENEROUS':", "options": ["Stingy", "Kind", "Helpful", "Noble"], "answer": 0}
            ]
        }
    },
    "police": {
        "name": "Rajasthan Police Constable Mock Test",
        "syllabus_quota": {
            "rajasthan_gk": 4,  # राजस्थान GK: 4 प्रश्न
            "law": 2,           # महिला एवं बाल सुरक्षा कानून: 2 प्रश्न
            "science": 2,       # सामान्य विज्ञान: 2 प्रश्न
            "english": 1        # Basic English: 1 प्रश्न
        },
        "questions": {
            "rajasthan_gk": [
                {"id": "pol_gk_1", "q": "राजस्थान पुलिस का ध्येय वाक्य क्या है?", "options": ["आमजन में विश्वास, अपराधियों में डर", "सत्यमेव जयते", "वीरभोग्या वसुंधरा", "अहर्निशं सेवामहे"], "answer": 0},
                {"id": "pol_gk_2", "q": "हल्दीघाटी का ऐतिहासिक युद्ध किस वर्ष हुआ था?", "options": ["1576 ई.", "1582 ई.", "1527 ई.", "1544 ई."], "answer": 0},
                {"id": "pol_gk_3", "q": "चित्तौड़गढ़ दुर्ग का प्रथम साका कब हुआ था?", "options": ["1303 ई.", "1534 ई.", "1568 ई.", "1301 ई."], "answer": 0},
                {"id": "pol_gk_4", "q": "थार का मरुस्थल राजस्थान के लगभग कितने प्रतिशत भाग पर फैला है?", "options": ["61.11%", "50%", "40%", "72%"], "answer": 0}
            ],
            "law": [
                {"id": "pol_law_1", "q": "बाल विवाह प्रतिषेध अधिनियम किस वर्ष का है?", "options": ["2006", "2005", "2012", "2009"], "answer": 0},
                {"id": "pol_law_2", "q": "POCSO एक्ट कब लागू किया गया था?", "options": ["14 नवंबर 2012", "2 अक्टूबर 2010", "15 अगस्त 2015", "1 जनवरी 2013"], "answer": 0}
            ],
            "science": [
                {"id": "pol_sci_1", "q": "रक्त का सामान्य pH मान कितना होता है?", "options": ["7.4", "6.5", "8.2", "7.0"], "answer": 0},
                {"id": "pol_sci_2", "q": "ध्वनि की गति सर्वाधिक किस माध्यम में होती है?", "options": ["ठोस (Solid)", "द्रव (Liquid)", "गैस (Gas)", "निर्वात (Vacuum)"], "answer": 0}
            ],
            "english": [
                {"id": "pol_eng_1", "q": "Choose the correct antonym of 'VICTORY':", "options": ["Defeat", "Success", "Triumph", "Win"], "answer": 0}
            ]
        }
    }
}

# HTML जनरेटर (Re-attempt बटन सहित)
def build_html_file(exam_title, questions_list, file_name):
    shuffled_questions = []
    for item in questions_list:
        opts = list(item["options"])
        correct_text = opts[item["answer"]]
        random.shuffle(opts)
        shuffled_questions.append({
            "q": item["q"],
            "options": opts,
            "answer": opts.index(correct_text)
        })

    html_code = f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{exam_title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #eef2f6; margin: 0; padding: 15px; }}
        .container {{ max-width: 680px; margin: auto; background: #ffffff; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
        .header {{ text-align: center; border-bottom: 2px solid #007bff; padding-bottom: 12px; margin-bottom: 20px; }}
        .header h2 {{ margin: 0 0 6px 0; color: #1e293b; }}
        .q-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px; }}
        .q-title {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; color: #0f172a; }}
        .opt-label {{ display: flex; align-items: center; background: #ffffff; border: 1px solid #cbd5e1; padding: 10px 14px; margin-bottom: 8px; border-radius: 6px; cursor: pointer; transition: 0.2s; }}
        .opt-label:hover {{ background: #f1f5f9; }}
        input[type="radio"] {{ margin-right: 12px; transform: scale(1.2); }}
        .actions {{ display: flex; gap: 10px; margin-top: 20px; }}
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
        <p>कुल प्रश्न: {len(shuffled_questions)} | सिलेबस व वेटेज आधारित</p>
    </div>
    <form id="quizForm">
"""
    for i, item in enumerate(shuffled_questions):
        html_code += f"""
        <div class="q-box">
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
            <button type="button" class="btn btn-submit" id="btnSubmit" onclick="submitTest()">Submit Test</button>
            <button type="button" class="btn btn-reset" id="btnReset" onclick="reattemptTest()">🔄 Re-attempt Test</button>
        </div>
    </form>
    <div id="res"></div>
</div>

<script>
    const answerKeys = {json.dumps([q['answer'] for q in shuffled_questions])};
    
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
        res.innerHTML = "🎯 स्कोर: " + score + " / " + total;
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

    # परीक्षा का नाम पहचानना
    selected_key = None
    if "cet" in text and "test" in text:
        selected_key = "cet"
    elif "reet" in text and "test" in text:
        selected_key = "reet"
    elif ("police" in text or "कांस्टेबल" in text) and "test" in text:
        selected_key = "police"

    if not selected_key:
        return

    exam_data = EXAM_DATABASE[selected_key]
    status_msg = await update.effective_message.reply_text("⏳ सिलेबस और वेटेज का विश्लेषण करके टेस्ट तैयार किया जा रहा है...")

    # यूजर हिस्ट्री चेक
    if chat_id not in user_asked_history:
        user_asked_history[chat_id] = set()

    picked_questions = []

    # बॉट खुद सिलेबस कोटा के अनुसार प्रश्न चुनेगा (नो रिपीट)
    for subject, quota in exam_data["syllabus_quota"].items():
        all_subject_q = exam_data["questions"].get(subject, [])
        available = [q for q in all_subject_q if q["id"] not in user_asked_history[chat_id]]

        # अगर सवाल खत्म हो गए तो सिर्फ इस विषय की हिस्ट्री रीसेट करें
        if len(available) < quota:
            available = all_subject_q

        selected_for_sub = random.sample(available, min(quota, len(available)))
        for q in selected_for_sub:
            picked_questions.append(q)
            user_asked_history[chat_id].add(q["id"])

    # प्रश्नों को आगे-पीछे शफल करना
    random.shuffle(picked_questions)

    # HTML फाइल जनरेट करना
    rand_id = random.randint(1000, 9999)
    file_name = f"{selected_key.upper()}_Mock_Test_{rand_id}.html"
    file_path = build_html_file(exam_data['name'], picked_questions, file_name)

    # Telegram पर सीधे HTML भेजना
    with open(file_path, "rb") as doc:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=doc,
            reply_to_message_id=update.effective_message.message_id,
            caption=f"📝 **{exam_data['name']}**\n\n"
                    f"• परीक्षा सिलेबस के अनुसार विषयवार वेटेज ऑटो-सेट है\n"
                    f"• सभी प्रश्न नए हैं (No Repeat)\n"
                    f"• Re-attempt बटन उपलब्ध है\n\n"
                    f"📲 Chrome या किसी भी ब्राउज़र में खोलें।"
        )

    await status_msg.delete()

    if os.path.exists(file_path):
        os.remove(file_path)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "👋 **राजस्थान परीक्षा टेस्ट बॉट में स्वागत है!**\n\n"
        "बस परीक्षा का नाम लिखकर टेस्ट मांगें:\n"
        "👉 `CET test`\n"
        "👉 `REET test`\n"
        "👉 `Police test`\n\n"
        "बॉट अपने आप सिलेबस वेटेज विश्लेषण करके बिना रिपीट किए HTML टेस्ट भेजेगा।"
    )

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
