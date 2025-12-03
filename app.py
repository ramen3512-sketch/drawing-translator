import streamlit as st
import anthropic
import base64
import json
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4, landscape
from PIL import Image
import io
import hmac

# --- APIキー設定 ---
# クラウドの金庫(Secrets)からキーを取得
client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

st.set_page_config(layout="wide", page_title="Trans-Pacific Drawing System")

# --- 🔐 パスワード認証 (門番) ---
if "APP_PASSWORD" in st.secrets:
    password = st.sidebar.text_input("パスワードを入力してください", type="password")
    if not password:
        st.warning("🔒 ログインしてください")
        st.stop()
    elif not hmac.compare_digest(password, st.secrets["APP_PASSWORD"]):
        st.error("❌ パスワードが違います")
        st.stop()

# セッション状態の初期化
if 'final_edits' not in st.session_state:
    st.session_state['final_edits'] = {}

# --- PDF生成関数 ---
def create_pdf(image_file, annotations):
    buffer = io.BytesIO()
    img = Image.open(image_file)
    img_width, img_height = img.size
    
    c = canvas.Canvas(buffer, pagesize=(img_width, img_height))
    
    # フォント登録
    try:
        pdfmetrics.registerFont(TTFont('IPAexGothic', 'ipaexg.ttf'))
        font_name = 'IPAexGothic'
    except:
        font_name = 'Helvetica'

    img_byte_arr = io.BytesIO(image_file.getvalue())
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(img_byte_arr), 0, 0, width=img_width, height=img_height)

    c.setFont(font_name, 12)
    c.setFillColorRGB(1, 0, 0) # 赤色
    
    for item in annotations:
        ymin, xmin, ymax, xmax = item.get('bbox', [0,0,0,0])
        translated_text = item.get('Approved_JP', '')
        
        x = (xmin / 1000) * img_width
        y = img_height - ((ymax / 1000) * img_height) - 15
        
        c.drawString(x, y, translated_text)
        
        # 枠線
        w = ((xmax - xmin) / 1000) * img_width
        h = ((ymax - ymin) / 1000) * img_height
        c.rect(x, y - 5, w, h, stroke=1, fill=0)

    c.save()
    buffer.seek(0)
    return buffer

def encode_image(uploaded_file):
    return base64.b64encode(uploaded_file.getvalue()).decode('utf-8')

def analyze_drawing(uploaded_file):
    image_data = encode_image(uploaded_file)
    
    # --- 策2: 専門用語辞書 (ここに追加！) ---
    # これを増やせば増やすほど、特定の単語に強くなります
    glossary = """
    - "A36" -> "SS400 (A36相当)"
    - "1018" -> "S20C (1018相当)"
    - "1045" -> "S45C (1045相当)"
    - "4140" -> "SCM440 (4140相当)"
    - "304 SS" -> "SUS304"
    - "316 SS" -> "SUS316"
    - "6061-T6" -> "A6061-T6"
    - "7075-T6" -> "A7075-T6 (超々ジュラルミン)"
    - "Delrin" -> "POM (ジュラコン/デルリン)"
    - "Anodize" -> "アルマイト処理"
    - "Black Oxide" -> "黒染め"
    - "Chem Film" -> "アロジン処理 (Chem Film)"
    - "Passivate" -> "不動態化処理 (パシべ)"
    - "CRS" -> "冷間圧延鋼 (ミガキ材)"
    - "HRS" -> "熱間圧延鋼 (黒皮材)"
    """

    system_prompt = f"""
    You are an expert translator bridging US design and Japanese manufacturing (Machikoba).
    Analyze the drawing text and provide 3 translation options with English rationale.

    【Translation Rules】
    1. Ignore pure numbers (e.g., "50.5").
    2. Use "Machikoba" jargon (Japanese Shop Terms) for the 'Shop Term' category.
    3. **STRICTLY FOLLOW the Glossary mapping below for materials and finishes.**
    4. Output pure JSON format.
    
    【Mandatory Glossary】
    {glossary}
    
    【Few-Shot Examples】
    Input: "DRILL & TAP 1/4-20 UNC THRU"
    Output Candidates:
      - Standard: "ドリル及びタップ 1/4-20 UNC 通し" (Desc: Formal engineering term)
      - Shop Term: "1/4-20 UNC キリ・タップ 通し" (Desc: 'Kiri' is preferred by craftsmen)
      - Functional: "下穴あけ後にねじ切り" (Desc: Describes the process)

    Input: "MAT'L: A36 STEEL"
    Output Candidates:
      - Standard: "材質: A36 スチール"
      - Shop Term: "材質: SS400 (A36相当)" (Desc: Converted to nearest JIS standard)
      - Functional: "一般構造用圧延鋼材"

    Now, analyze the user's image following these examples and glossary.
    """
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514", 
        max_tokens=4096,
        temperature=0,
        system=system_prompt,
        messages=[
            {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_data}}, {"type": "text", "text": "Extract and translate."}]}
        ],
    )
    return response.content[0].text

# --- UI ---
st.title("🇺🇸🇯🇵 図面翻訳・検証システム (Pro)")
st.caption("Enhanced with 'Few-Shot' learning for Machikoba terminology.")

uploaded_file = st.file_uploader("Upload Drawing", type=['png', 'jpg'])

if uploaded_file:
    if 'current_file' not in st.session_state or st.session_state['current_file'] != uploaded_file.name:
        st.session_state['data'] = None
        st.session_state['current_file'] = uploaded_file.name

    col1, col2 = st.columns([1, 1])
    with col1:
        st.image(uploaded_file, caption="Original", use_column_width=True)
        
        if st.button("Analyze & Translate"):
            with st.spinner("AI is analyzing context and nuances..."):
                try:
                    res = analyze_drawing(uploaded_file)
                    start = res.find('{')
                    end = res.rfind('}') + 1
                    data = json.loads(res[start:end])
                    st.session_state['data'] = data
                except Exception as e:
                    st.error(f"Error: {e}")

    with col2:
        if st.session_state.get('data'):
            st.subheader("🧐 Verify & Edit")
            
            approved_data = []
            
            with st.form("approval_form"):
                annotations = st.session_state['data'].get('annotations', [])
                
                for i, item in enumerate(annotations):
                    st.markdown(f"**#{i+1} Original: `{item['original']}`**")
                    
                    options = {c['ja']: f"{c['ja']}  [:blue[{c.get('category', 'Option')}]] {c.get('en_desc', '')}" for c in item['candidates']}
                    
                    default_opt = list(options.keys())[0] if options else ""
                    
                    selected_key = st.radio(
                        f"Suggestion #{i+1}",
                        options=options.keys(),
                        format_func=lambda x: options[x],
                        key=f"radio_{i}"
                    )
                    
                    final_text = st.text_input("Final Japanese:", value=selected_key, key=f"text_{i}")
                    st.divider()
                    
                    approved_data.append({
                        "Original": item['original'], 
                        "Approved_JP": final_text,
                        "bbox": item.get('bbox')
                    })
                
                if st.form_submit_button("✅ Approve All"):
                    st.session_state['approved_data'] = approved_data
                    st.success("Approved! Ready to download.")

            if 'approved_data' in st.session_state:
                st.write("### 📤 Output")
                pdf_data = create_pdf(uploaded_file, st.session_state['approved_data'])
                
                st.download_button(
                    label="Download Translated PDF",
                    data=pdf_data,
                    file_name="translated_drawing_verified.pdf",
                    mime="application/pdf"
                )