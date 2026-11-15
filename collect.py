"""
わんこガチャ：無名な犬動画を集めて videos.json に保存するスクリプト
GitHub Actions から1日1回実行されます。
必要な環境変数: YOUTUBE_API_KEY
"""
import datetime as dt
import json
import os
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
SEARCHES_PER_RUN = int(os.environ.get("SEARCHES_PER_RUN", "60"))  # 1回の検索=100ユニット(上限 1日10,000)
MAX_VIEWS = int(os.environ.get("MAX_VIEWS", "1000"))   # これ以下の再生回数だけ残す
MIN_SEC, MAX_SEC = 5, 15 * 60                         # 5秒〜15分の動画だけ
MAX_KEEP = 5000                                        # 保存する最大本数
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "videos.json")
API = "https://www.googleapis.com/youtube/v3/"

# 「犬じゃなかった」の集計(Googleスプレッドシートを「ウェブに公開」したCSVのURL)
REPORT_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRn_CHmsI4AWPCVUxjnE4JeP2rXBkKg_m9HeC0n3p1PBjTzQizo7rW3Ngfo_uVktfre4U5riYb8c6VJ/pub?gid=754659049&single=true&output=csv"       # 例: "https://docs.google.com/spreadsheets/d/e/xxxx/pub?gid=0&single=true&output=csv"
REPORT_THRESHOLD = 2      # この回数以上「犬じゃなかった」が押された動画を除外する

# 検索に使う言葉: (言語コード, 表示名, [検索語])
SEARCH_WORDS = [
    ("ja", "日本語", ["犬", "子犬", "わんこ", "柴犬", "うちの犬", "愛犬"]),
    ("en", "英語", ["dog", "puppy", "my dog", "doggo"]),
    ("es", "スペイン語", ["perro", "perrito", "mi perro"]),
    ("pt", "ポルトガル語", ["cachorro", "cachorrinho"]),
    ("fr", "フランス語", ["chien", "chiot", "mon chien"]),
    ("de", "ドイツ語", ["Hund", "Welpe", "mein Hund"]),
    ("it", "イタリア語", ["cagnolino", "cucciolo", "il mio cane"]),
    ("nl", "オランダ語", ["hond", "mijn hond"]),
    ("pl", "ポーランド語", ["piesek", "szczeniak"]),
    ("sv", "スウェーデン語", ["hund", "valp"]),
    ("ru", "ロシア語", ["собака", "щенок", "собачка"]),
    ("tr", "トルコ語", ["köpek", "köpeğim"]),
    ("id", "インドネシア語", ["anjing", "anjing lucu"]),
    ("tl", "タガログ語", ["tuta", "aso ko"]),
    ("el", "ギリシャ語", ["σκύλος", "σκυλάκι"]),
    ("vi", "ベトナム語", ["chó", "cún con"]),
    ("hi", "ヒンディー語", ["कुत्ता", "पिल्ला"]),
    ("ko", "韓国語", ["강아지", "댕댕이"]),
    ("zh", "中国語", ["狗狗", "小狗"]),
    ("th", "タイ語", ["หมา", "ลูกหมา"]),
    ("ar", "アラビア語", ["كلب", "جرو"]),
]

# 「犬の動画か」を判定する言葉(タイトル・説明・タグのどれかに含まれていればOK)
# 空白で区切る言語は単語単位で判定(hundred を Hund と誤判定しないため)
WORD_MATCH = [
    "dog", "dogs", "puppy", "puppies", "doggy", "doggie", "doggo", "pup", "pups",
    "perro", "perros", "perrito", "perritos", "perrita", "cachorro", "cachorros", "cachorrinho",
    "chien", "chiens", "chienne", "chiot", "chiots",
    "hund", "hunde", "hündin", "welpe", "welpen", "hundar", "valp",
    "cagnolino", "cagnolina", "cucciolo", "cuccioli",
    "hond", "honden", "piesek", "szczeniak",
    "собака", "собаки", "собачка", "щенок", "щенки", "пёс", "пес",
    "köpek", "köpeğim", "köpekler", "anjing", "tuta",
    "σκύλος", "σκυλάκι", "σκυλί", "chó", "cún", "kutta",
    "corgi", "husky", "shiba", "labrador", "chihuahua", "pomeranian", "dachshund", "poodle", "beagle",
]
SUBSTR_MATCH = [
    "犬", "いぬ", "イヌ", "わんこ", "ワンコ", "わんちゃん", "ワンちゃん", "チワワ", "プードル", "ダックス", "ポメラニアン", "コーギー",
    "강아지", "댕댕이", "멍멍이", "狗", "หมา", "สุนัข", "कुत्ता", "पिल्ला", "كلب", "جرو",
]
EXCLUDE = re.compile(
    r"hot\s?dogs?|corn\s?dogs?|ホットドッグ|アメリカンドッグ|热狗|핫도그|dogecoin|\bdoge\b|watch\s?_?dogs|"
    r"reservoir\s+dogs|sea\s?dogs?|dog\s?fight|underdog|犬夜叉|犬神|ポケモン|pokemon|minecraft|fortnite|roblox",
    re.IGNORECASE,
)
# AIで作られた動画らしい言葉(投稿者がAIラベルを付けていない場合の保険)
AI_EXCLUDE = re.compile(
    r"(?<![A-Za-z])a\.?i(?![A-Za-z])|#ai\b|ai[\s-]?generated|ai\s?video|ai\s?art|generative|"
    r"\bsora\s?(ai|2)\b|openai|\bveo\s?\d\b|google\s?veo|midjourney|runway\s?(ml|gen)|\bkling\b|\bhailuo\b|\bpika\s?labs?\b|stable\s?diffusion|"
    r"生成AI|AI生成|AI動画|AIで作|AI作成|人工知能|AI生成視頻|AI 생성|인공지능",
    re.IGNORECASE,
)
# 除外するYouTubeカテゴリ(1=映画とアニメ、31=アニメ)
EXCLUDE_CATEGORIES = {"1", "31"}
# アニメ・イラスト系らしい言葉
ANIME_EXCLUDE = re.compile(
    r"anime|animation|animated|cartoon|\bmmd\b|blender|\b3d\s?(model|anim)|\bvtuber\b|"
    r"アニメ|漫画|マンガ|まんが|イラスト|手描き|ゆっくり実況|ボイスロイド|"
    r"动画片|动漫|卡通|애니|만화|caricatura|dibujos animados|dessin animé|zeichentrick|мультик|мультфильм",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in WORD_MATCH) + r")(?!\w)", re.IGNORECASE)

JA_SHARE = 0.3   # 日本語で検索する割合
KANA = re.compile(r"[\u3040-\u30ff]")   # ひらがな・カタカナ


def is_japanese(sn):
    """日本の動画か: 音声・メタデータの言語が日本語、またはタイトル・説明にかなが含まれる"""
    langs = (sn.get("defaultAudioLanguage", "") + " " + sn.get("defaultLanguage", "")).lower()
    if "ja" in langs.split() or langs.startswith("ja"):
        return True
    return bool(KANA.search(sn.get("title", "") + sn.get("description", "")[:300]))


FILE_PREFIX = ["IMG_", "MOV_", "VID_", "DSC_", "MVI_", "PXL_"]


def api(endpoint, **params):
    params["key"] = API_KEY
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        if "quotaExceeded" in body or "dailyLimitExceeded" in body:
            raise QuotaExceeded()
        print(f"  APIエラー {e.code}: {body[:300]}", file=sys.stderr)
        return None


class QuotaExceeded(Exception):
    pass


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_search():
    """検索条件をランダムに1つ作る"""
    # 日本の動画を増やすため、検索の約3割は日本語で行う
    if random.random() < JA_SHARE:
        lang, label, words = SEARCH_WORDS[0]
    else:
        lang, label, words = random.choice(SEARCH_WORDS[1:])
    word = random.choice(words)
    now = dt.datetime.now(dt.timezone.utc)
    params = dict(part="snippet", type="video", maxResults=50, safeSearch="strict",
                  videoEmbeddable="true", relevanceLanguage=lang)
    strategy = random.choices(["new", "past", "file"], weights=[4, 4, 2])[0]
    if strategy == "new":       # ここ数日に投稿されたもの
        params.update(q=word, order="date", publishedAfter=iso(now - dt.timedelta(days=4)))
    elif strategy == "past":    # 過去のランダムな2週間
        start = dt.datetime(2009, 1, 1, tzinfo=dt.timezone.utc)
        span = (now - dt.timedelta(days=30) - start).days
        a = start + dt.timedelta(days=random.randint(0, span))
        params.update(q=word, order="date", publishedAfter=iso(a), publishedBefore=iso(a + dt.timedelta(days=14)))
    else:                       # スマホ撮影のファイル名と組み合わせる
        p = random.choice(FILE_PREFIX)
        tail = (f"{random.randint(2012, 2026)}{random.randint(1, 12):02d}" if p in ("VID_", "PXL_")
                else f"{random.randint(0, 9999):04d}")
        params.update(q=f"{word} {p}{tail}", order="relevance")
    return params, lang, label, strategy


def seconds(d):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s


def is_dog(text):
    if EXCLUDE.search(text):
        return False
    if WORD_RE.search(text):
        return True
    return any(w in text for w in SUBSTR_MATCH)


def check_videos(ids, lang, label):
    data = api("videos", part="snippet,statistics,contentDetails,status", id=",".join(ids), maxResults=50)
    found = []
    for v in (data or {}).get("items", []):
        sn, st, cd, ss = v.get("snippet", {}), v.get("statistics", {}), v.get("contentDetails", {}), v.get("status", {})
        if "viewCount" not in st:
            continue
        views = int(st["viewCount"])
        sec = seconds(cd.get("duration"))
        text = " ".join([sn.get("title", ""), sn.get("description", "")[:500], " ".join(sn.get("tags", []))])
        if (views > MAX_VIEWS or not (MIN_SEC <= sec <= MAX_SEC)
                or not ss.get("embeddable") or ss.get("privacyStatus") != "public"
                or sn.get("liveBroadcastContent", "none") != "none"
                or cd.get("contentRating", {}).get("ytRating") == "ytAgeRestricted"
                or ss.get("madeForKids")                     # 子ども向け動画は埋め込みのルールが厳しいため除外
                or ss.get("containsSyntheticMedia")          # YouTubeの「改変・合成コンテンツ」ラベル
                or AI_EXCLUDE.search(text)
                or sn.get("categoryId") in EXCLUDE_CATEGORIES
                or ANIME_EXCLUDE.search(text)
                or not is_dog(text)):
            continue
        found.append({
            "id": v["id"],
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "views": views,
            "likes": int(st.get("likeCount", 0) or 0),
            "comments": int(st.get("commentCount", 0) or 0),
            "published": sn.get("publishedAt", "")[:10],
            "sec": sec,
            "jp": is_japanese(sn),
            "category": sn.get("categoryId", ""),
            "lang": label,
            "found": dt.date.today().isoformat(),
            "checked": dt.date.today().isoformat(),
        })
    return found


def refresh(pool):
    """保存済みの動画の情報を最新にする(50本で1ユニットと安い)。
    削除・非公開になった動画や、人気が出て条件を外れた動画はここで取り除かれる。
    YouTubeの規約上、APIから得たデータは30日以内に更新する必要があるため毎回行う。"""
    ids = list(pool)
    fresh = {}
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        for v in check_videos(batch, "", ""):
            old = pool[v["id"]]
            v["lang"] = old.get("lang", "")
            v["found"] = old.get("found", v["found"])
            fresh[v["id"]] = v
    return fresh


def load_blocked():
    """blocked.txt に書いた動画(URLかID)を読み込む"""
    path = os.path.join(os.path.dirname(OUT), "blocked.txt")
    ids = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.split("#")[0].strip()
                m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", line)
                if m:
                    ids.add(m.group(1))
                elif line:
                    ids.add(line)
    except FileNotFoundError:
        pass
    return ids


def load_reported():
    """Googleフォームに集まった「犬じゃなかった」を数え、しきい値以上の動画IDを返す"""
    if not REPORT_CSV_URL:
        return set()
    import csv, io, collections
    try:
        with urllib.request.urlopen(REPORT_CSV_URL, timeout=30) as r:
            rows = list(csv.reader(io.StringIO(r.read().decode("utf-8-sig"))))
    except Exception as e:
        print(f"  報告の読み込みに失敗: {e}", file=sys.stderr)
        return set()
    counts = collections.Counter()
    for row in rows[1:]:                 # 1行目は見出し、2列目が動画ID
        if len(row) > 1:
            m = re.search(r"[\w-]{11}", row[1])
            if m:
                counts[m.group(0)] += 1
    out = {k for k, n in counts.items() if n >= REPORT_THRESHOLD}
    print(f"「犬じゃなかった」の報告: {sum(counts.values())} 件 → {len(out)} 本を除外")
    return out


def load():
    try:
        with open(OUT, encoding="utf-8") as f:
            return {v["id"]: v for v in json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(pool):
    items = sorted(pool.values(), key=lambda v: v.get("found", ""), reverse=True)[:MAX_KEEP]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, separators=(",", ":"))
    return len(items)


def main():
    if not API_KEY:
        sys.exit("YOUTUBE_API_KEY が設定されていません")
    pool = load()
    blocked = load_blocked() | load_reported()
    pool = {k: v for k, v in pool.items() if k not in blocked}
    # 以前集めた動画からも、AI・アニメらしいもの、除外カテゴリのものを取り除く
    pool = {k: v for k, v in pool.items()
            if not AI_EXCLUDE.search(v.get("title", ""))
            and not ANIME_EXCLUDE.search(v.get("title", ""))
            and v.get("category") not in EXCLUDE_CATEGORIES}
    before = len(pool)
    added = 0
    try:
        if pool:
            pool = refresh(pool)
            print(f"保存済み {before} 本を更新 → {len(pool)} 本が条件を満たしています")
        for i in range(SEARCHES_PER_RUN):
            params, lang, label, strategy = make_search()
            res = api("search", **params)
            ids = [it["id"]["videoId"] for it in (res or {}).get("items", []) if it.get("id", {}).get("videoId")]
            ids = [x for x in ids if x not in pool and x not in blocked]
            got = check_videos(ids, lang, label) if ids else []
            for v in got:
                pool[v["id"]] = v
            added += len(got)
            print(f"[{i + 1}/{SEARCHES_PER_RUN}] {strategy:4} {params['q']!r:32} 候補{len(ids):2}件 → 採用{len(got):2}件")
    except QuotaExceeded:
        print("今日の利用上限に達したので終了します")
    total = save(pool)
    print(f"完了: 新規 {added} 本 / 合計 {total} 本(実行前 {before} 本)")


if __name__ == "__main__":
    main()
