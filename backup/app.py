from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import joinedload
from sqlalchemy import create_engine, Column, Integer, String, BigInteger, ForeignKey, UniqueConstraint, DateTime
from datetime import datetime
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
import cv2, os, re, uuid, imghdr
from paddleocr import PaddleOCR
from fastapi import Path
from fastapi.responses import FileResponse
from PIL import Image

# ================= DB 연결 =================
DATABASE_URL = "postgresql://battle_user:1234@localhost:5432/battle_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()

# ================= 보스 정보 테이블 =================
class BossInfo(Base):
    __tablename__ = "boss_info"
    id = Column(Integer, primary_key=True, index=True)
    boss_name = Column(String, nullable=False)  # unique 제거
    difficulty = Column(String, nullable=False)
    gate_number = Column(Integer, nullable=False)
    boss_hp = Column(BigInteger, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("boss_name", "difficulty", "gate_number", name="uix_boss_unique"),
    )

# ================= 전투 기록 테이블 =================
class Battle(Base):
    __tablename__ = "battle"
    id = Column(Integer, primary_key=True, index=True)
    boss_id = Column(Integer, ForeignKey("boss_info.id", ondelete="CASCADE"))
    record_info = Column(String, nullable=False)
    battle_time = Column(String, nullable=False)
    battle_key = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    boss = relationship("BossInfo", backref="battles")

# ================= 플레이어 피해량 테이블 =================
class PlayerDamage(Base):
    __tablename__ = "player_damage"
    id = Column(Integer, primary_key=True, index=True)
    battle_id = Column(Integer, ForeignKey("battle.id", ondelete="CASCADE"))
    role = Column(String, nullable=True)
    damage = Column(BigInteger, nullable=False)
    battle = relationship("Battle", backref="players")
    ocr_results = Column(String, nullable=True)  # OCR Raw Data 저장
Base.metadata.create_all(bind=engine)

# ================= 방문자 및 업로드 카운트 =================
class Stats(Base):
    __tablename__ = "stats"
    id = Column(Integer, primary_key=True, index=True)
    visit_count = Column(BigInteger, default=0)
    upload_count = Column(BigInteger, default=0)

# ================= PaddleOCR v5 초기화 =================
ocr = PaddleOCR(
    lang='korean',
    use_textline_orientation=True,
    det_db_box_thresh=0.8
)

# ================= 보스 정보 등록/업데이트 함수 =================
def upsert_boss_info(boss_name, difficulty, gate_number, boss_hp):
    db = SessionLocal()
    try:
        boss = db.query(BossInfo).filter(
            BossInfo.boss_name == boss_name,
            BossInfo.difficulty == difficulty,
            BossInfo.gate_number == gate_number
        ).first()

        if boss:
            boss.boss_hp = boss_hp
            boss.updated_at = datetime.utcnow()
            db.commit()
            print(f"[UPDATE] {boss_name} ({difficulty}, {gate_number}관문) → HP {boss_hp}")
        else:
            boss = BossInfo(
                boss_name=boss_name,
                difficulty=difficulty,
                gate_number=gate_number,
                boss_hp=boss_hp
            )
            db.add(boss)
            db.commit()
            print(f"[INSERT] {boss_name} ({difficulty}, {gate_number}관문) → HP {boss_hp}")
    finally:
        db.close()


# ================= FastAPI =================
app = FastAPI()


# 키워드 기반 보스 이름 매칭
BOSS_KEYWORDS = {
    "드렉탈라스": ["드렉","탈라","탈라스","라스"],
    "스콜라키아": ["스콜","콜라","라키아", "키아"],
    "아게오로스": ["아게","게오","오로","오로스"],
    "폭풍의 지휘관 베히모스": ["폭풍의 지휘관", "지휘관", "베히모스", "베히", "모스"],
    "붉어진 백야의 나선": ["서막", "붉어진", "백야","나선"],
    "대지를 부수는 업화의 궤적": ["1막", "대지","부수", "업화", "궤적"],
    "부유하는 악몽의 진혼곡": ["2막", "부유", "악몽", "진혼", "진혼곡"],
    "칠흑 폭풍의 밤": ["3막", "칠흑", "폭풍의 밤", "밤"]
}

@app.on_event("startup")
def startup_event():
    boss_data = [
        # === 가디언 보스 ===
        {"boss_name": "드렉탈라스", "difficulty": "전체", "gate_number": 0, "boss_hp": 150000000000},
        {"boss_name": "스콜라키아", "difficulty": "전체", "gate_number": 0, "boss_hp": 106000000000},
        {"boss_name": "아게오로스", "difficulty": "전체", "gate_number": 0, "boss_hp": 25000000000},
        # === 에픽 레이드 ====
        # 폭풍의 지휘관 베히모스 (노말만 존재)
        {"boss_name": "폭풍의 지휘관 베히모스", "difficulty": "노말", "gate_number": 1, "boss_hp": 280688129478},
        {"boss_name": "폭풍의 지휘관 베히모스", "difficulty": "노말", "gate_number": 2, "boss_hp": 395706606604},
        # === 카제로스 레이드 ===
        # 서막 1관문
        {"boss_name": "붉어진 백야의 나선", "difficulty": "노말", "gate_number": 1, "boss_hp": 62802745968},
        {"boss_name": "붉어진 백야의 나선", "difficulty": "하드", "gate_number": 1, "boss_hp": 108972915945},
        #서막 2관문
        {"boss_name": "붉어진 백야의 나선", "difficulty": "노말", "gate_number": 2, "boss_hp": 80672317989},
        {"boss_name": "붉어진 백야의 나선", "difficulty": "하드", "gate_number": 2, "boss_hp": 154486187002},
        # 1막 1관문
        {"boss_name": "대지를 부수는 업화의 궤적", "difficulty": "노말", "gate_number": 1, "boss_hp": 161517294610},
        {"boss_name": "대지를 부수는 업화의 궤적", "difficulty": "하드", "gate_number": 1, "boss_hp": 269870428126},
        # 1막 2관문
        {"boss_name": "대지를 부수는 업화의 궤적", "difficulty": "노말", "gate_number": 2, "boss_hp": 213231745024},
        {"boss_name": "대지를 부수는 업화의 궤적", "difficulty": "하드", "gate_number": 2, "boss_hp": 398607605792},
        # 2막 1관문
        {"boss_name": "부유하는 악몽의 진혼곡", "difficulty": "노말", "gate_number": 1, "boss_hp": 275449621248},
        {"boss_name": "부유하는 악몽의 진혼곡", "difficulty": "하드", "gate_number": 1, "boss_hp": 516125060783},
        # 2막 2관문
        {"boss_name": "부유하는 악몽의 진혼곡", "difficulty": "노말", "gate_number": 2, "boss_hp": 39940195809},
        {"boss_name": "부유하는 악몽의 진혼곡", "difficulty": "하드", "gate_number": 2, "boss_hp": 911639983772},
        # 3막 1관문
        {"boss_name": "칠흑 폭풍의 밤", "difficulty": "노말", "gate_number": 1, "boss_hp": 368773967531},
        {"boss_name": "칠흑 폭풍의 밤", "difficulty": "하드", "gate_number": 1, "boss_hp": 652499653375},
        # 3막 2관문
        {"boss_name": "칠흑 폭풍의 밤", "difficulty": "노말", "gate_number": 2, "boss_hp": 334691604286},
        {"boss_name": "칠흑 폭풍의 밤", "difficulty": "하드", "gate_number": 2, "boss_hp": 663116555628},
        # 3막 3관문
        {"boss_name": "칠흑 폭풍의 밤", "difficulty": "노말", "gate_number": 3, "boss_hp": 731975350664},
        {"boss_name": "칠흑 폭풍의 밤", "difficulty": "하드", "gate_number": 3, "boss_hp": 1473779836172}
    ]
    for b in boss_data:
        upsert_boss_info(b["boss_name"], b["difficulty"], b["gate_number"], b["boss_hp"])

def parse_boss_info(boss_name_raw: str):
    # 기본 전처리
    gate_match = re.search(r"(\d+)관문", boss_name_raw)
    gate_number = int(gate_match.group(1)) if gate_match else None

    difficulty_match = re.search(r"\[(.*?)\]", boss_name_raw)
    difficulty = difficulty_match.group(1) if difficulty_match else "노말"

    # 보스 이름 정제
    name = re.sub(r"\d+막[: ]?", "", boss_name_raw)
    name = re.sub(r"\[.*?\]", "", name)
    name = re.sub(r"\d+관문", "", name)
    boss_name_clean = name.strip()

    normalized = re.sub(r"[^가-힣a-zA-Z0-9]", "", boss_name_clean)

    for boss_name, keywords in BOSS_KEYWORDS.items():
        match_count = sum(1 for kw in keywords if kw in normalized)
        if match_count >= 1:
            # 가디언(관문/난이도 없음) 처리
            if boss_name in ["드렉탈라스", "스콜라키아", "아게오로스"]:
                return boss_name, "전체", 0
            # 레이드 보스
            return boss_name, difficulty, gate_number

    return boss_name_clean, difficulty, gate_number

# ================= 차트 페이지 =================
@app.get("/", response_class=FileResponse)
def chart_page():
    # 방문자 카운트 로직 제거
    return FileResponse(os.path.join("templates", "index.html"))

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    allowed_types = ["image/png", "image/jpeg", "image/jpg"]

    # 1) Content-Type 체크
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")

    # 2) 확장자 체크
    if not (file.filename.lower().endswith(".png") or 
            file.filename.lower().endswith(".jpg") or 
            file.filename.lower().endswith(".jpeg")):
        raise HTTPException(status_code=400, detail="허용되지 않는 파일 확장자입니다.")

    # 3) 임시 저장
    temp_filename = f"{uuid.uuid4().hex}.tmp"
    temp_path = os.path.join(".", temp_filename)
    with open(temp_path, "wb") as f:
        f.write(await file.read())

    try:
        # 4) 이미지 타입 확인
        img_type = imghdr.what(temp_path)
        if img_type not in ["png", "jpeg"]:
            os.remove(temp_path)
            raise HTTPException(status_code=400, detail="이미지 형식이 올바르지 않습니다.")

        # 5) Pillow 이미지 검증
        try:
            Image.open(temp_path).verify()
        except Exception:
            os.remove(temp_path)
            raise HTTPException(status_code=400, detail="손상된 이미지입니다.")

        # 6) 최종 확장자 붙여 저장
        final_path = temp_path.replace(".tmp", f".{img_type}")
        os.rename(temp_path, final_path)

        # 7) OpenCV로 이미지 로드 가능 여부 확인
        img = cv2.imread(final_path)
        if img is None:
            os.remove(final_path)
            return JSONResponse({"error": "이미지 로드 실패"}, status_code=400)

        # 8) OCR 전처리
        padded_img = cv2.copyMakeBorder(img, 150, 0, 150, 0, cv2.BORDER_CONSTANT, value=[0,0,0])
        cv2.imwrite("padded.jpg", padded_img)
        ocr_result = ocr.predict("padded.jpg")

 # OCR 결과 파싱
        boss_name_raw, record_info, battle_time, damage_title, damage, damage_value, role = None, None, None, None, None, None, None
        texts = []

        if ocr_result and len(ocr_result) > 0:
            data = ocr_result[0]
            texts = data.get("rec_texts", [])

            for t in texts:
                t_clean = t.strip()

                # boss_name으로 절대 쓰면 안 되는 조건들
                if len(t_clean) <= 2:
                    continue
                if any(kw in t_clean for kw in ["기록", "정보", "전투분석기", "전투", "분석기", "관리"]):
                    continue
                if re.match(r'^[0-9/]+$', t_clean):  # 숫자와 /만 있는 값
                    continue
                if "%" in t_clean or re.match(r'^\d+(\.\d+)?%$', t_clean):  # 퍼센트 값
                    continue
                if re.match(r'^\d{2}:\d{2}$', t_clean):  # 시간 형식
                    continue
                boss_name_raw = t_clean
                break

            for t in texts:
                if "기록" in t and "정보" in t:
                    record_info = re.sub(r"[^0-9]", "", t.strip())
                    break

            for t in texts:
                if "전투" in t and "시간" in t:
                    battle_time = re.sub(r"[^0-9]", "", t.strip())
                    break

            damage_idx = -1
            for idx, t in enumerate(texts):
                if ("피해량" in t or "조력" in t) and damage_title is None:
                    damage_title = t.strip()
                    damage_idx = idx
                    break
            for idx in range(damage_idx + 1, len(texts)):
                if "억" in texts[idx]:
                    damage = texts[idx].strip()
                    damage_idx = idx
                    break
            for idx in range(damage_idx + 1, len(texts)):
                if "," in texts[idx] and texts[idx].replace(",", "").isdigit():
                    damage_value = texts[idx].replace(",", "")
                    break

            if damage_title:
                role = "서포터" if "조력" in damage_title else "딜러"
            else:
                role = "서포터" if any("서포터" in t or "낙인" in t for t in texts) else "딜러"
                
        # === record_info, battle_time 없는 경우 업로드 실패 처리 ===
        if not record_info or not battle_time:
            return JSONResponse(
                {"error": "이미지에서 유효한 값을 인식하지 못했습니다. 이미지 확인 후 다시 시도해주세요."},
                status_code=400
            )
        battle_key = f"{record_info}_{battle_time}" if record_info and battle_time else "unknown"
        boss_name, difficulty, gate_number = parse_boss_info(boss_name_raw)

        # 9) DB 저장 로직
        db = SessionLocal()
        try:
            boss = db.query(BossInfo).filter(
                BossInfo.boss_name == boss_name,
                BossInfo.difficulty == difficulty,
                BossInfo.gate_number == gate_number
            ).first()

            if not boss:
                return JSONResponse(
                    {"error": f"BossInfo에 '{boss_name_raw}' 정보가 없습니다. 등록 필요"}, status_code=400
                )

            # Battle 저장
            battle = db.query(Battle).filter(Battle.battle_key == battle_key).first()
            if not battle:
                battle = Battle(
                    boss_id=boss.id,
                    record_info=record_info,
                    battle_time=battle_time,
                    battle_key=battle_key
                )
                db.add(battle)
                db.commit()
                db.refresh(battle)

            # PlayerDamage 저장
            if damage_value:
                exists = db.query(PlayerDamage).filter(
                    PlayerDamage.battle_id == battle.id,
                    PlayerDamage.damage == int(damage_value)
                ).first()

                if exists:
                    exists.ocr_results = "\n".join(texts)
                    db.commit()
                else:
                    db.add(PlayerDamage(
                        battle_id=battle.id,
                        role=role,
                        damage=int(damage_value),
                        ocr_results="\n".join(texts)
                    ))
                    db.commit()

            # 10) 업로드 카운트 증가
            stats = db.query(Stats).first()
            if stats:
                stats.upload_count += 1
                db.commit()

        finally:
            db.close()

        # 성공 반환
        return {
            "boss_name": boss_name_raw,
            "record_info": record_info,
            "battle_time": battle_time,
            "battle_key": battle_key,
            "difficulty": difficulty,
            "gate_number": gate_number,
            "role": role,
            "damage": damage,
            "damage_value": damage_value,
            "battle_id": battle.id,
            "ocr_results": texts
        }

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    finally:
        # 임시 파일 정리
        for f in ["padded.jpg", temp_path, locals().get("final_path", "")]:
            if f and os.path.exists(f):
                os.remove(f)


@app.post("/bossinfo/upsert")
async def bossinfo_upsert(data: dict):
    boss_name = data.get("boss_name")
    difficulty = data.get("difficulty")
    gate_number = data.get("gate_number")
    boss_hp = data.get("boss_hp")

    if not boss_name or not difficulty or not gate_number or not boss_hp:
        return JSONResponse({"error": "모든 필드가 필요합니다."}, status_code=400)

    upsert_boss_info(boss_name, difficulty, gate_number, boss_hp)
    return {"message": f"{boss_name} ({difficulty}, {gate_number}관문) 저장 완료"}

# ================= 전투 리스트 =================

@app.get("/battle-list")
def battle_list():
    db = SessionLocal()
    try:
        battles = db.query(Battle).options(joinedload(Battle.boss))\
                    .order_by(Battle.record_info.desc()).all()
        return [
            {
                "id": b.id,
                "boss_name": b.boss.boss_name,
                "difficulty": b.boss.difficulty,
                "gate_number": b.boss.gate_number,
                "record_info": b.record_info,
                "battle_time": b.battle_time,
                "created_at": b.created_at.strftime("%Y-%m-%d %H:%M:%S")
            }
            for b in battles
        ]
    finally:
        db.close()

# ================= 전투 상세 =================
@app.get("/battle/{battle_id}")
def battle_detail(battle_id: int):
    db = SessionLocal()
    try:
        battle = db.query(Battle).options(joinedload(Battle.boss))\
                    .filter(Battle.id == battle_id).first()
        if not battle:
            return JSONResponse({"error": "전투 기록 없음"}, status_code=404)

        players = db.query(PlayerDamage)\
            .filter(PlayerDamage.battle_id == battle_id)\
            .order_by(PlayerDamage.damage.desc()).all()

        total_hp = battle.boss.boss_hp
        total_damage = sum(p.damage for p in players)

        # 플레이어별 OCR Raw Data 포함
        players_data = []
        for idx, p in enumerate(players):
            role_name = (p.role if players.count(p.role) == 1 else f"{p.role}{idx+1}")
            players_data.append({
                "role": role_name,
                "damage": p.damage,
                "percent": round((p.damage / total_hp) * 100, 2),
                "damage_ratio": round((p.damage / total_damage) * 100, 2),
                "ocr_results": getattr(p, "ocr_results", "") or ""  # OCR raw data
            })

        result = {
            "boss_name": battle.boss.boss_name,
            "difficulty": battle.boss.difficulty,
            "gate_number": battle.boss.gate_number,
            "total_hp": total_hp,
            "total_damage": total_damage,
            "players": players_data
        }
        return result
    finally:
        db.close()

# 방문 횟수 및 업로드 횟수 api
@app.get("/stats")
def get_stats():
    db = SessionLocal()
    try:
        stats = db.query(Stats).first()
        if not stats:
            return {"visit_count": 0, "upload_count": 0}
        return {"visit_count": stats.visit_count, "upload_count": stats.upload_count}
    finally:
        db.close()