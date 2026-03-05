"""
Google Places API (New) を使用した写真取得
APIキーが必要。Places API が有効なプロジェクトでキーを取得してください。
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request


def _extract_from_maps_url(url: str) -> tuple[str | None, float | None, float | None]:
    """URLから店舗名と座標を抽出"""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    place_name = None
    lat, lng = None, None

    # /place/店舗名/ から名前を抽出
    match = re.search(r"/place/([^/@]+)/", url)
    if match:
        place_name = urllib.parse.unquote(match.group(1)).strip()
        if place_name and len(place_name) < 2:
            place_name = None

    # @lat,lng, から座標を抽出
    match = re.search(r"@(-?\d+\.?\d*),(-?\d+\.?\d*)", url)
    if match:
        try:
            lat = float(match.group(1))
            lng = float(match.group(2))
        except ValueError:
            pass

    return place_name, lat, lng


def fetch_via_places_api(maps_url: str, api_key: str, max_images: int = 30) -> list[str]:
    """
    Places API (New) で写真URLを取得
    Text Search → Place Details (photos) → Place Photos の流れ
    """
    place_name, lat, lng = _extract_from_maps_url(maps_url)
    if not place_name:
        raise ValueError("URLから店舗名を抽出できませんでした")

    # 1. Text Search で Place ID を取得
    text_search_url = "https://places.googleapis.com/v1/places:searchText"
    body = {"textQuery": place_name}
    if lat is not None and lng is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": 500.0,
            }
        }

    req = urllib.request.Request(
        text_search_url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.name",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        try:
            err_json = json.loads(err_body)
            msg = err_json.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body or str(e)
        if e.code == 403:
            raise ValueError(
                f"APIキーが無効か、Places API が有効化されていません。\n"
                f"詳細: {msg}\n\n"
                f"→ Google Cloud Console で「Places API (New)」を有効にしてください。"
            ) from e
        if e.code == 400:
            raise ValueError(f"API リクエストエラー: {msg}") from e
        raise ValueError(f"Places API エラー ({e.code}): {msg}") from e

    places = data.get("places", [])
    if not places:
        raise ValueError(f"「{place_name}」が見つかりませんでした")

    place_id = places[0].get("id")
    if not place_id:
        place_name_field = places[0].get("name", "")
        if "/" in place_name_field:
            place_id = place_name_field.split("/")[-1]
    if not place_id:
        raise ValueError("Place IDを取得できませんでした")

    # 2. Place Details で photos を取得
    details_url = f"https://places.googleapis.com/v1/places/{place_id}"
    req = urllib.request.Request(
        details_url,
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "photos",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            details = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        try:
            err_json = json.loads(err_body)
            msg = err_json.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body or str(e)
        raise ValueError(f"Place Details エラー: {msg}") from e

    photos = details.get("photos", [])
    if not photos:
        raise ValueError("この店舗には写真が登録されていません")

    # 3. 各写真のURLを取得（Place Photos APIはリダイレクトで画像を返す）
    image_urls = []
    for i, photo in enumerate(photos[:max_images]):
        photo_name = photo.get("name")
        if not photo_name:
            continue
        # Place Photos API: GET /v1/{name}/media で画像を取得
        # name は "places/ChIJ.../photos/PHOTO_RESOURCE" 形式
        if not photo_name.startswith("places/"):
            photo_name = "places/" + photo_name
        if not photo_name.endswith("/media"):
            photo_name = photo_name + "/media"
        photo_url = (
            f"https://places.googleapis.com/v1/{photo_name}"
            f"?maxWidthPx=1600&key={api_key}"
        )
        image_urls.append(photo_url)

    return image_urls
