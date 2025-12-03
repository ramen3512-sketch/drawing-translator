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

# --- APIキー設定 ---
# キーはクラウドの金庫から借りる、という書き方に変えます
client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

st.set_page_config(layout="wide", page_title="Trans-Pacific Drawing System")
# --- ⬇︎ ここから追加 ⬇︎ ---
# パスワード認証機能
import hmac
if "APP_PASSWORD" in st.secrets:
    password = st.sidebar.text_input("パスワードを入力してください", type="password")
    if not password:
        st.warning("🔒 ログインしてください")
        st.stop()  # パスワード未入力ならここで処理を止める
    elif not hmac.compare_digest(password, st.secrets["APP_PASSWORD"]):
        st.error("❌ パスワードが違います")
        st.stop()  # パスワード間違いならここで処理を止める
# --- ⬆︎ ここまで追加 ⬆︎ ---

# セッション状態の初期化
if 'final_edits' not in st.session_state:
    st.session_state['final_edits'] = {}

# --- PDF生成関数 ---
def create_pdf(image_file, annotations):
    buffer = io.BytesIO()
    
    # 画像を開いてサイズを取得
    img = Image.open(image_file)
    img_width, img_height = img.size
    
    # PDFキャンバス作成（画像のサイズに合わせる）
    c = canvas.Canvas(buffer, pagesize=(img_width, img_height))
    
    # 1. フォント登録（ipaexg.ttfが同じフォルダにある前提）
    try:
        pdfmetrics.registerFont(TTFont('IPAexGothic', 'ipaexg.ttf'))
        font_name = 'IPAexGothic'
    except:
        font_name = 'Helvetica' # フォントがない場合の予備（日本語は豆腐になります）

    # 2. 画像を描画
    # StreamlitのUploadFileは一度読むとポインタが進むので、再度読み直すかBytesIO化が必要
    img_byte_arr = io.BytesIO(image_file.getvalue())
    c.drawImage(from_image(img_byte_arr), 0, 0, width=img_width, height=img_height)

    # 3. 翻訳テキストを書き込む
    c.setFont(font_name, 12) # 文字サイズ12
    c.setFillColorRGB(1, 0, 0) # 赤色
    
    for item in annotations:
        # 座標計算 (bboxは [ymin, xmin, ymax, xmax] の1000分率)
        ymin, xmin, ymax, xmax = item.get('bbox', [0,0,0,0])
        translated_text = item.get('Approved_JP', '')
        
        # PDFの座標系は「左下が(0,0)」なので、Y座標を反転させる必要がある
        # x座標: xmin / 1000 * 幅
        # y座標: 高さ - (ymin / 1000 * 高さ)
        
        x = (xmin / 1000) * img_width
        y = img_height - ((ymax / 1000) * img_height) - 15 # 少し下にずらす
        
        # テキスト描画
        c.drawString(x, y, translated_text)
        
        # 枠線を描画（オプション）
        w = ((xmax - xmin) / 1000) * img_width
        h = ((ymax - ymin) / 1000) * img_height
        c.rect(x, y - 5, w, h, stroke=1, fill=0)

    c.save()
    buffer.seek(0)
    return buffer

def from_image(img_buffer):
    from reportlab.lib.utils import ImageReader
    return ImageReader(img_buffer)

def encode_image(uploaded_file):
    return base64.b64encode(uploaded_file.getvalue()).decode('utf-8')

def analyze_drawing(uploaded_file):
    image_data = encode_image(uploaded_file)
    system_prompt = """
    You are an expert translator bridging US design and Japanese manufacturing.
    Analyze the drawing text and provide 3 translation options with English rationale.
    Output JSON format:
    {
      "annotations": [
        {
          "original": "Drill 1/4",
          "candidates": [
            {"ja": "ドリル 1/4", "category": "Standard", "en_desc": "Standard term"},
            {"ja": "キリ 1/4", "category": "Shop Term", "en_desc": "Preferred by craftsmen"}
          ],
          "bbox": [ymin, xmin, ymax, xmax]
        }
      ]
    }
    Rules: 
    - Ignore pure numbers.
    - bbox must be [ymin, xmin, ymax, xmax] (0-1000 scale).
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
st.title("🇺🇸🇯🇵 図面翻訳・検証システム (Workflow Alpha)")
st.caption("Step 1: Upload -> Step 2: AI Translate -> Step 3: Approve -> Step 4: Download PDF")

uploaded_file = st.file_uploader("Upload Drawing", type=['png', 'jpg'])

if uploaded_file:
    # データ保持用
    if 'current_file' not in st.session_state or st.session_state['current_file'] != uploaded_file.name:
        st.session_state['data'] = None
        st.session_state['current_file'] = uploaded_file.name

    col1, col2 = st.columns([1, 1])
    with col1:
        st.image(uploaded_file, caption="Original", use_column_width=True)
        
        # 翻訳ボタン
        if st.button("Analyze & Translate"):
            with st.spinner("AI is analyzing..."):
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
                    
                    options = {c['ja']: f"{c['ja']}  [:blue[{c['category']}]] {c['en_desc']}" for c in item['candidates']}
                    
                    # デフォルト値の安全な取得
                    default_opt = list(options.keys())[0] if options else ""
                    
                    selected_key = st.radio(
                        f"Suggestion #{i+1}",
                        options=options.keys(),
                        format_func=lambda x: options[x],
                        key=f"radio_{i}"
                    )
                    
                    final_text = st.text_input("Final Japanese:", value=selected_key, key=f"text_{i}")
                    st.divider()
                    
                    # 承認データに座標も含める
                    approved_data.append({
                        "Original": item['original'], 
                        "Approved_JP": final_text,
                        "bbox": item.get('bbox')
                    })
                
                # 承認ボタン
                if st.form_submit_button("✅ Approve All"):
                    st.session_state['approved_data'] = approved_data
                    st.success("Approved! Ready to download.")

            # PDFダウンロードボタン（承認後に表示）
            if 'approved_data' in st.session_state:
                st.write("### 📤 Output")
                pdf_data = create_pdf(uploaded_file, st.session_state['approved_data'])
                
                st.download_button(
                    label="Download Translated PDF (JAPAN Factory Ready)",
                    data=pdf_data,
                    file_name="translated_drawing_verified.pdf",
                    mime="application/pdf"
                )