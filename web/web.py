# ===== 표준 라이브러리 =====
import os
import re
import cv2
import uuid
import imghdr
from datetime import datetime
# ===== 외부 라이브러리 =====
from fastapi import FastAPI, UploadFile, File, HTTPException, Path
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy import (
    create_engine, Column, Integer, String, BigInteger,
    ForeignKey, UniqueConstraint, DateTime
)
from sqlalchemy.orm import (
    sessionmaker, declarative_base, relationship, joinedload
)
from PIL import Image
from celery.result import AsyncResult
from celery import Celery

#파일 저장용 공통저장소
upload_dir = "/mnt/shared/uploads"
os.makedirs(upload_dir, exist_ok=True)

# Celery 설정
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery(
    "ocr_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL
)

# ================= DB 연결 =================
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://battle_user:1234@localhost:5432/battle_db"
)
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
        {"boss_name": "부유하는 악몽의 진혼곡", "difficulty": "노말", "gate_number": 2, "boss_hp": 399401950809},
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


@app.get("/", response_class=FileResponse)
def chart_page():
    return FileResponse(os.path.join("templates", "index.html"))

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
            # 무조건 번호를 붙임 (1부터 시작)
            role_name = f"{p.role}{idx+1}"
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
            "battle_time": battle.battle_time,  
            "players": players_data
        }
        return result
    finally:
        db.close()

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    allowed_types = ["image/png", "image/jpeg", "image/jpg"]

    # 확장자 / Content-Type 체크
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")

    # 파일 저장
    temp_filename = f"{uuid.uuid4().hex}.tmp"
    temp_path = os.path.join(upload_dir, temp_filename)
    with open(temp_path, "wb") as f:
        f.write(await file.read())

    # 파일 확장자 검증
    img_type = imghdr.what(temp_path)
    if img_type not in ["png", "jpeg"]:
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail="이미지 형식이 올바르지 않습니다.")

    final_path = temp_path.replace(".tmp", f".{img_type}")
    os.rename(temp_path, final_path)

    # Celery Task 호출 (비동기 처리)
    try:
        # Celery를 통해 OCR 작업 전송
        task = celery_app.send_task(
            "ocr_tasks.process_ocr",           # Celery Task 이름
            args=[final_path]                 # 인자 (파일 경로)               
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시스템 오류! 전송 실패")

    return {"task_id": task.id}

@app.get("/task/{task_id}")
def get_task_status(task_id: str):
    result = AsyncResult(task_id, app=celery_app)

    if result.successful():
        # Worker가 status=fail을 반환했을 수도 있으니 추가 체크
        if isinstance(result.result, dict) and result.result.get("status") == "fail":
            return {"status": "FAIL", "error": result.result.get("error", "작업 실패")}
        return {"status": "SUCCESS", "result": result.result}

    elif result.failed():
        # Worker에서 Exception 터진 케이스
        return {"status": "FAIL", "error": str(result.result)}

    else:
        # PENDING, STARTED 등
        return {"status": result.status}