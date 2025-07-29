import os
import re
import cv2
import uuid
import imghdr
from datetime import datetime
# ===== 외부 라이브러리 =====
from celery import Celery
from paddleocr import PaddleOCR
from PIL import Image
from sqlalchemy import (
    create_engine, Column, Integer, String, BigInteger,
    ForeignKey, UniqueConstraint, DateTime
)
from sqlalchemy.orm import (
    sessionmaker, declarative_base, relationship, joinedload
)
from fastapi import FastAPI, UploadFile, File, HTTPException, Path
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

# ===== Celery 설정 =====
celery_app = Celery(
    "ocr_tasks",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

print("[DEBUG] PaddleOCR 초기화 시작")
# ===== PaddleOCR 초기화 =====
ocr = PaddleOCR(
    lang='korean',
    det_db_box_thresh=0.8
)
print("[DEBUG] PaddleOCR 초기화 완료")

# ===== DB 연결 =====
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://battle_user:1234@localhost:5432/battle_db"
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

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

# ================= 방문자 및 업로드 카운트 =================
class Stats(Base):
    __tablename__ = "stats"
    id = Column(Integer, primary_key=True, index=True)
    visit_count = Column(BigInteger, default=0)
    upload_count = Column(BigInteger, default=0)

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


# ===== Celery Task =====
@celery_app.task(name="ocr_tasks.process_ocr")
def process_ocr(file_path: str):
    print(f"[DEBUG] Task 시작 - 파일경로: {file_path}")
    db = SessionLocal()
    padded_path = None  # 초기화
    try:
        print("[DEBUG] 이미지 로드 시도")
        img = cv2.imread(file_path)
        if img is None:
            os.remove(file_path)
            return JSONResponse({"error": "이미지 로드 실패"}, status_code=400)
        print("[DEBUG] 이미지 로드 완료")

        print("[DEBUG] OCR 전처리 시작")
        padded_img = cv2.copyMakeBorder(img, 150, 0, 150, 0, cv2.BORDER_CONSTANT, value=[0,0,0])
        print("[DEBUG] OCR 전처리 완료")

        padded_path = file_path.rsplit(".", 1)[0] + "_padded.jpg"
        cv2.imwrite(padded_path, padded_img)
        print(f"[DEBUG] OCR 실행 시작 (경로: {padded_path})")
        ocr_result = ocr.ocr(padded_path)
        print(f"[DEBUG] OCR 실행 완료 - 결과 길이: {len(ocr_result) if ocr_result else 0}")
        if not ocr_result or len(ocr_result) == 0:
            print("[ERROR] OCR 결과 없음")
            return {"status": "fail", "error": "OCR 결과 없음"}

        data = ocr_result[0]
        texts = data.get("rec_texts", [])
        print(f"[DEBUG] OCR 텍스트 추출 완료 - {len(texts)}개")

        boss_name_raw, record_info, battle_time = None, None, None
        damage_title, damage, damage_value, role = None, None, None, None

        print("[DEBUG] 보스 이름 추출 시작")
        for t in texts:
            t_clean = t.strip()
            if len(t_clean) <= 2:
                continue
            if any(kw in t_clean for kw in ["기록", "정보", "전투분석기", "전투", "관리"]):
                continue
            if re.match(r"^[0-9/]+$", t_clean):
                continue
            if "%" in t_clean or re.match(r"^\d+(\.\d+)?%$", t_clean):
                continue
            if re.match(r"^\d{2}:\d{2}$", t_clean):
                continue
            boss_name_raw = t_clean
            break
        print(f"[DEBUG] 보스 이름 추출 완료: {boss_name_raw}")

        for t in texts:
            if "기록" in t and "정보" in t:
                record_info = re.sub(r"[^0-9]", "", t.strip())
                break
        for t in texts:
            if "전투" in t and "시간" in t:
                battle_time = re.sub(r"[^0-9]", "", t.strip())
                break
        print(f"[DEBUG] 기록: {record_info}, 전투시간: {battle_time}")

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

        role = (
            "서포터" if (damage_title and "조력" in damage_title)
            else "서포터" if any("서포터" in t or "낙인" in t for t in texts)
            else "딜러"
        )

        if not record_info or not battle_time:
            print("[ERROR] 유효한 기록/전투시간 없음")
            return {
                "status": "fail",
                "error": "이미지에서 유효한 값을 인식하지 못했습니다. 이미지 확인 후 다시 시도해주세요."
            }

        boss_name, difficulty, gate_number = parse_boss_info(boss_name_raw)
        print(f"[DEBUG] 파싱된 보스 정보: {boss_name}, {difficulty}, {gate_number}")

        print("[DEBUG] DB 보스 조회 시작")
        boss = db.query(BossInfo).filter(
            BossInfo.boss_name == boss_name,
            BossInfo.difficulty == difficulty,
            BossInfo.gate_number == gate_number,
        ).first()

        if not boss:
            print("[ERROR] 보스 정보 없음")
            return {"status": "fail", "error": f"이미지를 인식하지 못 했습니다 확인 후 다시 시도해주세요."}

        battle_key = f"{record_info}_{battle_time}_{boss.id}"
        battle = db.query(Battle).filter(Battle.battle_key == battle_key).first()

        if not battle:
            print("[DEBUG] 새로운 전투 기록 생성")
            battle = Battle(
                boss_id=boss.id,
                record_info=record_info,
                battle_time=battle_time,
                battle_key=battle_key,
                created_at=datetime.utcnow(),
            )
            db.add(battle)
            db.commit()
            db.refresh(battle)

        if damage_value:
            exists = db.query(PlayerDamage).filter(
                PlayerDamage.battle_id == battle.id,
                PlayerDamage.damage == int(damage_value),
            ).first()

            if exists:
                exists.ocr_results = "\n".join(texts)
                db.commit()
            else:
                db.add(
                    PlayerDamage(
                        battle_id=battle.id,
                        role=role,
                        damage=int(damage_value),
                        ocr_results="\n".join(texts),
                    )
                )
                db.commit()

        stats = db.query(Stats).first()
        if not stats:
            stats = Stats(upload_count=1)
            db.add(stats)
        else:
            stats.upload_count += 1
        db.commit()

        print("[DEBUG] Task 완료 - 정상 종료")
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
        print(f"[ERROR] 예외 발생: {str(e)}")
        return {"status": "fail", "error": str(e)}
    finally:
        db.close()
        if os.path.exists(file_path):
            os.remove(file_path)
        if padded_path and os.path.exists(padded_path):
            os.remove(padded_path)
        print(f"[DEBUG] 파일 삭제 완료: {file_path}")