"""
画像一括加工Webアプリ
- Google Mapsから画像取得（Playwright）
- 一括加工（Pillow）：サイズプリセット、スマートクロップ、ロゴ合成
"""

import io
import json
import subprocess
import sys
import traceback
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter

# ============== 定数 ==============
SIZE_PRESETS = {
    "縦型 (1080x1350px)": (1080, 1350),
    "横型 (1024x682px)": (1024, 682),
}
LOGO_POSITIONS = {
    "左上": "top-left",
    "右上": "top-right",
    "左下": "bottom-left",
    "右下": "bottom-right",
}
DEFAULT_MAX_IMAGES = 30


# ============== 画像取得エンジン ==============
def _is_valid_maps_url(url: str) -> bool:
    """Google Maps URLかどうかを検証"""
    url = url.strip().replace("\n", "").replace("\r", "")
    if not url or len(url) < 15:
        return False
    normalized = url if url.startswith("http") else "https://" + url
    maps_indicators = [
        "google.com/maps",
        "maps.google.com",
        "google.co.jp/maps",
        "goo.gl/maps",
        "maps.app.goo.gl",
    ]
    return any(ind in normalized for ind in maps_indicators)


def fetch_images_via_places_api(maps_url: str, api_key: str, max_images: int) -> list[str]:
    """Google Places API で写真URLを取得（確実に取得できる）"""
    from places_api_fetcher import fetch_via_places_api
    return fetch_via_places_api(maps_url, api_key, max_images)


def fetch_images_from_gbp_url(
    maps_url: str,
    max_images: int = DEFAULT_MAX_IMAGES,
    api_key: str | None = None,
) -> list[str]:
    """
    GBPの写真URLを収集
    - APIキーあり: Places API を使用（推奨・確実）
    - APIキーなし: Playwright でスクレイピング
    """
    if not _is_valid_maps_url(maps_url):
        raise ValueError(
            "有効なGoogle Maps URLを入力してください。"
            "例: https://www.google.com/maps/place/店舗名/..."
        )

    if not maps_url.strip().startswith("http"):
        maps_url = "https://" + maps_url.strip()

    # Places API を優先（APIキーがある場合）
    if api_key and api_key.strip():
        return fetch_images_via_places_api(maps_url, api_key.strip(), max_images)

    # Playwright（別プロセス）- ローカル環境のみ
    fetcher_path = Path(__file__).parent / "gbp_fetcher.py"
    if not fetcher_path.exists():
        raise RuntimeError(
            "Web上ではGBP取得にPlaces APIキーが必要です。"
            "サイドバーでAPIキーを入力するか、ローカルアップロードをご利用ください。"
        )
    result = subprocess.run(
        [sys.executable, str(fetcher_path), maps_url.strip(), str(max_images)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(Path(__file__).parent),
    )

    if result.returncode != 0 and result.stderr:
        err_msg = result.stderr
        if "playwright" in err_msg.lower() or "ModuleNotFoundError" in err_msg:
            raise RuntimeError(
                "Web上ではGBP取得にPlaces APIキーが必要です。"
                "サイドバーでAPIキーを入力してください。"
            )
        try:
            err_data = json.loads(result.stderr.strip())
            if "error" in err_data:
                raise RuntimeError(err_data["error"])
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"取得に失敗しました: {result.stderr}")

    output = result.stdout or ""
    marker = "<<<GBP_FETCH_RESULT>>>"
    if marker in output:
        json_str = output.split(marker, 1)[1].strip()
        return json.loads(json_str)
    raise RuntimeError("画像URLの取得に失敗しました")


# ============== 一括加工ロジック (Pillow) ==============
def center_crop(img: Image.Image, target_width: int, target_height: int) -> Image.Image:
    """アスペクト比を維持したまま中心でクロップ"""
    orig_w, orig_h = img.size
    target_ratio = target_width / target_height
    orig_ratio = orig_w / orig_h

    if orig_ratio > target_ratio:
        # 幅が広い → 幅を基準にクロップ
        new_h = orig_h
        new_w = int(orig_h * target_ratio)
    else:
        # 高さが高い → 高さを基準にクロップ
        new_w = orig_w
        new_h = int(orig_w / target_ratio)

    left = (orig_w - new_w) // 2
    top = (orig_h - new_h) // 2
    right = left + new_w
    bottom = top + new_h

    return img.crop((left, top, right, bottom)).resize(
        (target_width, target_height), Image.Resampling.LANCZOS
    )


def add_logo_overlay(
    base_img: Image.Image,
    logo_img: Image.Image,
    position: str,
    x_offset: int,
    y_offset: int,
    opacity: float,
    logo_size_ratio: float,
    outline_width: int,
) -> Image.Image:
    """
    透過ロゴを指定位置に合成（影・縁取りで視認性向上）
    """
    base_img = base_img.convert("RGBA")
    logo_img = logo_img.convert("RGBA")

    logo_width = int(base_img.width * logo_size_ratio)
    ratio = logo_width / logo_img.width
    logo_height = int(logo_img.height * ratio)
    logo_resized = logo_img.resize(
        (logo_width, logo_height), Image.Resampling.LANCZOS
    )

    if opacity < 1.0:
        alpha = logo_resized.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        logo_resized.putalpha(alpha)

    # 影を追加（背景と見分けやすく）
    shadow_offset = 4
    alpha_ch = logo_resized.split()[3]
    shadow_img = Image.new("RGBA", (logo_resized.width + 20, logo_resized.height + 20), (0, 0, 0, 0))
    shadow_img.paste(
        Image.new("RGBA", logo_resized.size, (0, 0, 0, 100)),
        (10, 10),
        alpha_ch.point(lambda p: int(p * 0.5)),
    )
    shadow_blur = shadow_img.filter(ImageFilter.GaussianBlur(radius=4))

    # 白い縁取りを追加（背景と見分けやすく）
    if outline_width > 0:
        lw, lh = logo_resized.size
        pad = outline_width * 2
        outline_canvas = Image.new("RGBA", (lw + pad, lh + pad), (0, 0, 0, 0))
        alpha_channel = logo_resized.split()[3]
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx != 0 or dy != 0:
                    outline_canvas.paste(
                        Image.new("RGBA", (lw, lh), (255, 255, 255, 220)),
                        (outline_width + dx, outline_width + dy),
                        alpha_channel,
                    )
        outline_canvas.paste(logo_resized, (outline_width, outline_width), logo_resized)
        logo_final = outline_canvas
    else:
        logo_final = logo_resized

    lw, lh = logo_final.size
    bw, bh = base_img.size
    margin = int(base_img.width * 0.02)

    positions_map = {
        "top-left": (margin + x_offset, margin + y_offset),
        "top-right": (bw - lw - margin + x_offset, margin + y_offset),
        "bottom-left": (margin + x_offset, bh - lh - margin + y_offset),
        "bottom-right": (bw - lw - margin + x_offset, bh - lh - margin + y_offset),
    }
    paste_x, paste_y = positions_map.get(position, positions_map["top-left"])

    # 影を先に描画（オフセット考慮）
    sh_x = paste_x + shadow_offset - 10
    sh_y = paste_y + shadow_offset - 10
    base_img.paste(shadow_blur, (sh_x, sh_y), shadow_blur.split()[3])

    paste_x = max(0, min(paste_x, bw - lw))
    paste_y = max(0, min(paste_y, bh - lh))
    base_img.paste(logo_final, (paste_x, paste_y), logo_final.split()[3])
    return base_img.convert("RGB")


def reduce_highlights(img: Image.Image, amount: float = 0.05) -> Image.Image:
    """ハイライト（明るい部分）を指定割合で落とす"""
    img = img.convert("RGB")
    r, g, b = img.split()

    def _reduce(x: int) -> int:
        return int(x * (1 - amount)) if x > 180 else x

    r = r.point(_reduce)
    g = g.point(_reduce)
    b = b.point(_reduce)
    return Image.merge("RGB", (r, g, b))


def enhance_for_smartphone(img: Image.Image) -> Image.Image:
    """縦型（スマホ用）: 明るさ10%・コントラスト10%・ハイライト5%落とし"""
    enhancer_b = ImageEnhance.Brightness(img)
    enhancer_c = ImageEnhance.Contrast(img)
    img = enhancer_b.enhance(1.10)  # 10%明るく
    img = enhancer_c.enhance(1.10)  # 10%コントラスト強め
    img = reduce_highlights(img, 0.05)  # ハイライト5%落とし
    return img


def process_image(
    img: Image.Image,
    size_preset: tuple[int, int],
    logo_img: Image.Image | None,
    logo_position: str,
    x_offset: int,
    y_offset: int,
    opacity: float,
    logo_size_ratio: float,
    outline_width: int,
    is_portrait: bool,
) -> Image.Image:
    """画像を加工（クロップ + 縦型時は補正 + ロゴ合成）"""
    target_w, target_h = size_preset
    result = center_crop(img, target_w, target_h)

    # 縦型（スマホ用）の場合は明るさ・コントラスト補正
    if is_portrait:
        result = enhance_for_smartphone(result)

    if logo_img:
        result = add_logo_overlay(
            result, logo_img, logo_position, x_offset, y_offset, opacity,
            logo_size_ratio, outline_width,
        )

    return result


# ============== メインアプリ ==============
def main():
    st.set_page_config(
        page_title="画像一括加工アプリ",
        page_icon="🖼️",
        layout="wide",
    )
    st.title("🖼️ 画像一括加工Webアプリ")

    # セッション状態の初期化
    if "processed_images" not in st.session_state:
        st.session_state.processed_images = []
    if "source_images" not in st.session_state:
        st.session_state.source_images = []
    if "selected_indices" not in st.session_state:
        st.session_state.selected_indices = []

    # ===== Sidebar =====
    with st.sidebar:
        st.header("⚙️ 設定")

        # ロゴアップロード
        logo_file = st.file_uploader(
            "ロゴ画像 (PNG推奨)",
            type=["png", "jpg", "jpeg"],
            help="透過PNGを推奨します",
        )
        logo_img = None
        if logo_file:
            try:
                logo_img = Image.open(logo_file).convert("RGBA")
                st.success("ロゴを読み込みました")
            except Exception as e:
                st.error(f"ロゴの読み込みに失敗: {e}")

        st.divider()

        # 加工サイズ
        size_choice = st.selectbox(
            "加工サイズ",
            options=list(SIZE_PRESETS.keys()),
            index=0,
        )
        size_preset = SIZE_PRESETS[size_choice]
        if size_preset == (1080, 1350):
            st.caption("📱 縦型: スマホ用に明るさ・コントラストを自動補正")

        st.divider()

        # ロゴ配置・サイズ・透過度
        if logo_img:
            st.subheader("ロゴ設定")
            logo_position_key = st.selectbox(
                "配置位置",
                options=list(LOGO_POSITIONS.keys()),
                index=0,
            )
            logo_position = LOGO_POSITIONS[logo_position_key]
            logo_size_ratio = st.slider(
                "ロゴサイズ（背景幅に対する割合）",
                0.05, 0.35, 0.15, 0.01,
                help="0.15 = 15%",
            )
            x_offset = st.slider("Xオフセット (px)", -150, 150, 0)
            y_offset = st.slider("Yオフセット (px)", -150, 150, 0)
            opacity = st.slider("不透明度", 0.0, 1.0, 1.0, 0.05)
            outline_width = st.slider(
                "縁取りの太さ (px)",
                0, 4, 2,
                help="背景と見分けやすくする白い縁取り。0でオフ",
            )
        else:
            logo_position = "top-left"
            logo_size_ratio = 0.15
            x_offset = y_offset = 0
            opacity = 1.0
            outline_width = 2

        st.divider()

        # 取得枚数
        max_images = st.number_input(
            "取得枚数 (GBP)",
            min_value=5,
            max_value=50,
            value=DEFAULT_MAX_IMAGES,
            step=5,
        )

        st.divider()

        # Google Places API キー（オプション・推奨）
        st.subheader("📷 写真取得方法")
        api_key = st.text_input(
            "Google Places API キー（任意）",
            type="password",
            placeholder="AIza...",
            help="入力すると確実に写真を取得できます。未入力の場合はPlaywrightを使用（取得が不安定な場合あり）",
        )
        if api_key:
            st.caption("✅ Places API で取得（推奨）")
        else:
            st.caption("⚠️ Playwright で取得（枚数が少ない場合あり）")
        with st.expander("🔑 APIキーの取得方法"):
            st.markdown("""
            1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
            2. プロジェクトを作成
            3. **「Places API (New)」** を有効化（ライブラリで検索）
            4. 認証情報 → API キーを作成
            5. 上記にキーを貼り付け

            詳しくは `PLACES_API_SETUP.md` を参照してください。
            """)

    # ===== Main =====
    tab1, tab2 = st.tabs(["📍 GBP（店舗）取得", "📁 ローカル一括アップロード"])

    with tab1:
        st.subheader("GBP（Google Business Profile）から画像を取得")
        st.caption("店舗のGoogle MapsページのURLを貼り付けてください。")
        st.info(
            "💡 **APIキーが取得できない場合**: 「ローカル一括アップロード」タブで、"
            "Google Mapsの写真を手動で保存してアップロードすることもできます。"
        )
        maps_url_input = st.text_input(
            "Google Maps URL（店舗のGBPページ）",
            placeholder="https://www.google.com/maps/place/店舗名/@35.6595,139.7004,17z/...",
        )
        if st.button("🔍 取得開始", type="primary"):
            if not maps_url_input.strip():
                st.error("Google Maps URLを入力してください")
            else:
                with st.spinner("画像を取得中..."):
                    try:
                        urls = fetch_images_from_gbp_url(
                            maps_url_input.strip(), max_images, api_key
                        )
                        if not urls:
                            st.warning("画像が見つかりませんでした。URLが正しいか確認してください。")
                        else:
                            st.session_state.source_images = []
                            for i, url in enumerate(urls):
                                try:
                                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                                    with urllib.request.urlopen(req, timeout=15) as resp:
                                        img_data = resp.read()
                                    img = Image.open(io.BytesIO(img_data)).convert("RGB")
                                    st.session_state.source_images.append(img)
                                except Exception as e:
                                    st.warning(f"画像 {i+1} の読み込みに失敗: {e}")
                            st.success(f"{len(st.session_state.source_images)} 枚の画像を取得しました")
                    except Exception as e:
                        st.error("取得に失敗しました")
                        with st.expander("🔧 エラー詳細と対処法", expanded=True):
                            st.code(traceback.format_exc(), language="text")
                            st.markdown("""
                            **よくある原因と対処法：**
                            1. **Chromiumが未インストール** → ターミナルで以下を実行してください：
                               ```
                               playwright install chromium
                               ```
                            2. **実行後はStreamlitを再起動**してください
                            3. 上記で解決しない場合は、エラー内容を確認して環境を整えてください
                            """)

    with tab2:
        st.subheader("ローカルから画像をアップロード")
        uploaded_files = st.file_uploader(
            "画像をドラッグ＆ドロップ",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
        )
        if st.button("📤 アップロード画像を読み込み"):
            if not uploaded_files:
                st.error("画像を選択してください")
            else:
                st.session_state.source_images = []
                for f in uploaded_files:
                    try:
                        img = Image.open(f).convert("RGB")
                        st.session_state.source_images.append(img)
                    except Exception as e:
                        st.warning(f"{f.name} の読み込みに失敗: {e}")
                st.success(f"{len(st.session_state.source_images)} 枚の画像を読み込みました")

    # ===== 取得画像の選択 =====
    st.divider()
    if st.session_state.source_images:
        st.subheader("📋 加工する画像を選択")
        st.caption("加工したい画像にチェックを入れてください（取得直後は全選択）")

        # ソース変更時に全選択にリセット
        if "source_images_hash" not in st.session_state:
            st.session_state.source_images_hash = 0
        current_hash = id(st.session_state.source_images)
        if st.session_state.source_images_hash != current_hash:
            st.session_state.selected_indices = list(range(len(st.session_state.source_images)))
            st.session_state.source_images_hash = current_hash

        # 全選択/全解除
        n_src = len(st.session_state.source_images)
        col_btn1, col_btn2, _ = st.columns([1, 1, 4])
        with col_btn1:
            if st.button("全選択"):
                st.session_state.selected_indices = list(range(n_src))
                for i in range(n_src):
                    st.session_state[f"sel_{n_src}_{i}"] = True
                st.rerun()
        with col_btn2:
            if st.button("全解除"):
                st.session_state.selected_indices = []
                for i in range(n_src):
                    st.session_state[f"sel_{n_src}_{i}"] = False
                st.rerun()

        # 画像グリッド（5列）で選択
        cols_per_row = 5
        for row_start in range(0, len(st.session_state.source_images), cols_per_row):
            cols = st.columns(cols_per_row)
            for col_idx, col in enumerate(cols):
                img_idx = row_start + col_idx
                if img_idx >= len(st.session_state.source_images):
                    break
                with col:
                    img = st.session_state.source_images[img_idx]
                    st.image(img, use_container_width=True, caption=f"#{img_idx + 1}")
                    n_src = len(st.session_state.source_images)
                    default_val = img_idx in st.session_state.selected_indices
                    st.checkbox(
                        "加工する",
                        value=default_val,
                        key=f"sel_{n_src}_{img_idx}",
                    )

        # チェックボックスの状態から選択リストを構築
        n_src = len(st.session_state.source_images)
        st.session_state.selected_indices = [
            i for i in range(n_src)
            if st.session_state.get(f"sel_{n_src}_{i}", i in st.session_state.selected_indices)
        ]

        st.caption(f"選択中: {len(st.session_state.selected_indices)} 枚 / {len(st.session_state.source_images)} 枚")

    # ===== 加工実行 =====
    st.divider()
    if st.session_state.source_images and st.session_state.selected_indices:
        if st.button("🔄 一括加工を実行", type="primary"):
            images_to_process = [
                st.session_state.source_images[i] for i in st.session_state.selected_indices
            ]
            is_portrait = size_preset == (1080, 1350)
            processed = []
            progress = st.progress(0)
            for i, img in enumerate(images_to_process):
                try:
                    result = process_image(
                        img,
                        size_preset,
                        logo_img,
                        logo_position,
                        x_offset,
                        y_offset,
                        opacity,
                        logo_size_ratio,
                        outline_width,
                        is_portrait,
                    )
                    processed.append(result)
                except Exception as e:
                    st.warning(f"画像 {i+1} の加工に失敗: {e}")
                progress.progress((i + 1) / len(images_to_process))
            progress.empty()
            st.session_state.processed_images = processed
            st.success(f"{len(processed)} 枚の加工が完了しました")

    # ===== プレビュー =====
    if st.session_state.processed_images:
        st.subheader("📷 プレビュー（最初の3枚）")
        cols = st.columns(3)
        for i, img in enumerate(st.session_state.processed_images[:3]):
            with cols[i]:
                st.image(img, use_container_width=True, caption=f"画像 {i+1}")

        # ===== ダウンロード =====
        st.subheader("📥 ダウンロード")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, img in enumerate(st.session_state.processed_images):
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                zf.writestr(f"image_{i+1:04d}.jpg", buf.getvalue())
        zip_buffer.seek(0)

        st.download_button(
            label="📦 processed_images.zip をダウンロード",
            data=zip_buffer,
            file_name="processed_images.zip",
            mime="application/zip",
        )


if __name__ == "__main__":
    main()
