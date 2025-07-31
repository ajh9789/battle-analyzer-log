# 전투 분석기 (Battle Analyzer)

OCR 기반으로 이미지에서 전투 정보를 인식하고, 웹 UI로 시각화하는 프로젝트입니다.
FastAPI + Celery + Redis + PaddleOCR을 사용합니다.

---

## 1. 폴더 구조

```
.
├── web/                  # FastAPI 웹 서버 (UI, API)
├── worker/               # Celery Worker (OCR 처리)
├── docker-compose.yml    # 컨테이너 구성
├── requirements.txt      # Python 의존성 패키지
└── .gitignore
```

---

## 2. 서비스 구성 (docker-compose)

```yaml
version: "3.9"
services:
  web:
    build: ./web
    container_name: battle-web
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://battle_user:password@10.1.0.1:5432/battle_db
      REDIS_URL: redis://redis:6379/0
    volumes:
      - ./shared:/mnt/shared
    depends_on:
      - redis
    networks:
      - battle-net
    restart: unless-stopped

  worker:
    build: ./worker
    container_name: battle-worker
    environment:
      DATABASE_URL: postgresql://battle_user:password@10.1.0.1:5432/battle_db
      REDIS_URL: redis://redis:6379/0
    volumes:
      - ./shared:/mnt/shared
    depends_on:
      - redis
    networks:
      - battle-net
    restart: unless-stopped

  redis:
    image: redis:7
    container_name: battle-redis
    ports:
      - "6379:6379"
    networks:
      - battle-net
    restart: unless-stopped

networks:
  battle-net:
    driver: bridge
```

---

## 3. 실행 방법

### 1) 의존성 설치

```bash
pip install -r requirements.txt
```

### 2) docker-compose로 실행

```bash
docker-compose up -d --build
```

* `http://localhost:8000` → 웹 UI 접속
* 이미지 업로드 시 Celery Worker가 비동기적으로 OCR 처리

---

## 4. 주요 기능

* **이미지 업로드**: PNG/JPG 업로드 시 자동으로 전투 정보 추출
* **OCR 처리**: PaddleOCR 기반 보스 이름, 전투 시간, 딜량 인식
* **데이터 저장**: PostgreSQL 기반 전투 기록, 플레이어 정보 저장
* **웹 UI 시각화**

  * Doughnut 차트로 딜 비율 표시
  * 전투 시간 중앙 표시
  * 1% 미만 딜러 제외, 에스더 딜량 제외 필터
  * OCR Raw Data 보기 지원

---

## 5. API 주요 엔드포인트

* `POST /upload`: 이미지 업로드 → task\_id 반환
* `GET /task/{task_id}`: OCR 처리 상태 조회
* `GET /battle-list`: 전투 목록 조회
* `GET /battle/{battle_id}`: 전투 상세 조회
* `GET /stats`: 방문자/업로드 카운트 조회


### 1) `POST /upload` : 이미지 업로드 및 OCR 처리 요청

* **요청**

  * 업로드할 이미지 파일 (`file`)
  * 전투력 정보(`power`, 선택값, step=100)
* **처리 과정**

  1. 이미지 파일 저장 (확장자/크기 검증 포함)
  2. Celery Task Queue에 OCR 작업 등록 → `task_id` 생성
  3. 클라이언트에게 `task_id` 반환
* **응답 예시**

  ```json
  { "task_id": "3f8f2bca-..." }
  ```
* **주요 역할**

  * 업로드된 이미지를 Celery Worker에게 비동기적으로 전달
  * 즉시 OCR 결과를 반환하지 않음 → `GET /task/{task_id}`로 상태 조회

---

### 2) `GET /task/{task_id}` : OCR 처리 상태 조회

* **요청**

  * Path 파라미터: `task_id`
* **처리 과정**

  1. Celery Worker의 작업 상태 확인

     * `PENDING` / `STARTED` / `SUCCESS` / `FAIL`
  2. 상태가 `SUCCESS`이면 OCR 결과 데이터를 함께 반환
* **응답 예시**

  ```json
  {
    "status": "SUCCESS",
    "result": {
      "battle_id": 12,
      "boss_name": "드렉탈라스",
      "battle_time": "0629",
      "players": [
        {"role": "딜러1", "damage": 12345678, "power": 1580, "ocr_results": "..."}
      ]
    }
  }
  ```
* **주요 역할**

  * 프론트엔드가 1초 간격으로 폴링(polling)하여 처리 완료 여부 확인
  * 실패 시 에러 메시지 반환

---

### 3) `GET /battle-list` : 전투 목록 조회

* **요청**

  * 파라미터 없음 (전체 목록)
* **처리 과정**

  1. DB에서 `Battle` 테이블 조회 (최신순)
  2. 전투 ID, 보스 정보, 기록 시간 등 요약 데이터 반환
* **응답 예시**

  ```json
  [
    {
      "id": 12,
      "boss_name": "드렉탈라스",
      "difficulty": "전체",
      "gate_number": 0,
      "record_info": "20250728",
      "battle_time": "0629",
      "created_at": "2025-07-28 13:12:22"
    }
  ]
  ```
* **주요 역할**

  * 웹 UI에서 전체 전투 리스트 표시 및 선택 필터링에 사용됨

---

### 4) `GET /battle/{battle_id}` : 전투 상세 조회

* **요청**

  * Path 파라미터: `battle_id`
* **처리 과정**

  1. DB에서 전투 정보(`Battle`) 및 참여자(`PlayerDamage`) 조회
  2. 총 HP, 총 피해량, 플레이어별 상세 딜량/전투력/Raw OCR 데이터 반환
* **응답 예시**

  ```json
  {
    "boss_name": "드렉탈라스",
    "difficulty": "전체",
    "gate_number": 0,
    "total_hp": 150000000000,
    "total_damage": 140000000000,
    "battle_time": "0629",
    "players": [
      {
        "role": "딜러1",
        "damage": 100000000000,
        "percent": 66.6,
        "damage_ratio": 71.4,
        "power": 1580,
        "ocr_results": "OCR 인식 원본 텍스트..."
      }
    ]
  }
  ```
* **주요 역할**

  * 선택된 전투를 차트와 요약 패널에 표시하기 위해 사용됨

---

### 5) `GET /stats` : 방문자/업로드 카운트 조회

* **요청**

  * 파라미터 없음
* **처리 과정**

  1. DB `Stats` 테이블 조회
  2. 방문 횟수(`visit_count`), 업로드 횟수(`upload_count`) 반환
* **응답 예시**

  ```json
  { "visit_count": 102, "upload_count": 23 }
  ```
* **주요 역할**

  * 웹 UI의 업로드 카운트 및 통계 표시용

---

## 6. 사용자 요청 → 처리 흐름 요약 (폴링 기반)

```
1. 사용자가 웹 UI에서 이미지 업로드
   ↓ (POST /upload)
2. 서버가 Celery Worker에게 OCR 작업 의뢰, task_id 반환
   ↓ (GET /task/{task_id})
3. 프론트엔드가 1초 간격으로 작업 상태 확인
   ↓
4. 작업이 완료되면 OCR 결과 + 전투 데이터 저장됨
   ↓ (GET /battle/{battle_id})
5. 차트 & 상세 정보 UI로 렌더링
```

네, 지금까지 신경 쓴 보안 항목들을 정리해서 README에 넣으면 좋을 **보안 관점 설명**을 완성해볼게요. 추가로 언급한 **악성 이미지 검증, XSS 방지, SQL 인젝션 방어**까지 넣었습니다.

---

## 7. 보안 관점에서 신경 쓴 부분

### 1) 업로드 파일 보안

* **확장자(Content-Type) 이중 검증**
  업로드 시 MIME 타입(`image/png`, `image/jpeg`)과 실제 확장자를 동시에 체크합니다.

  ```python
  allowed_types = ["image/png", "image/jpeg"]
  if file.content_type not in allowed_types:
      raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")
  ```
* **`imghdr`로 실제 이미지 여부 확인**
  악성 스크립트를 이미지로 위장하는 공격을 막기 위해 Python `imghdr`로 내부 시그니처를 확인합니다.

  ```python
  img_type = imghdr.what(temp_path)
  if img_type not in ["png", "jpeg"]:
      os.remove(temp_path)
      raise HTTPException(status_code=400, detail="이미지 형식이 올바르지 않습니다.")
  ```
* **임시 파일 삭제**
  업로드된 파일은 Celery Worker에서 작업 완료 후 즉시 삭제되어 서버에 남지 않습니다.

---

### 2) XSS 방지

* **Raw 데이터 출력 시 `innerHTML` 미사용**
  클라이언트에서 OCR Raw Data나 사용자 입력값을 출력할 때 `innerHTML` 대신 `textContent`를 사용하여 스크립트 삽입(XSS) 차단.

  ```javascript
  const pre = document.createElement("pre");
  pre.textContent = p.ocr_results;   // innerHTML 대신 textContent 사용
  ```
* **템플릿 직접 랜더링 금지**
  모든 데이터는 JSON API로 전달하며, 서버에서 동적으로 HTML을 생성하지 않음.

---

### 3) SQL 인젝션 방지

* **ORM 사용(SQLAlchemy)**
  DB 접근은 SQLAlchemy ORM으로만 수행하므로 직접 SQL 문자열을 조합하지 않습니다.

  ```python
  boss = db.query(BossInfo).filter(
      BossInfo.boss_name == boss_name,
      BossInfo.difficulty == difficulty
  ).first()
  ```

  → 자동으로 파라미터 바인딩 처리되므로 SQL Injection 방어됨.
* **Unique Constraint & Validation**

  * `battle_key`와 BossInfo(`boss_name`, `difficulty`, `gate_number`) 컬럼에 UniqueConstraint 적용 → 중복 입력 차단
  * 모든 입력값은 사전에 검증 후 DB에 저장

---


### 4) 디렉토리/데이터 접근 제어 (실행 권한 제거)

* **공유 볼륨(`shared`)의 실행 권한 제거**

  * 업로드된 이미지가 저장되는 `shared` 디렉토리는 웹 서버에서 실행 권한을 제거해 두었기 때문에,
    혹시나 악성 스크립트 파일이 업로드되더라도 실행되지 않음.
  * 내부적으로 `FastAPI`와 `Celery Worker`가 파일을 읽기/삭제만 하며 외부 접근은 차단됨.

* **Raw 파일 직접 다운로드 불가**

  * `shared` 디렉토리를 정적 파일 경로로 노출하지 않았고,
    파일 다운로드 API도 제공하지 않으므로 클라이언트가 업로드 파일 경로를 추측해 접근할 수 없음.

---

### 5) 서비스 안정성 & 기타

* **Docker 재시작 정책**
  `restart: unless-stopped` 설정으로 서비스가 비정상 종료돼도 자동으로 재시작.
* **에러 반환 설계**
  비정상적인 입력이나 내부 오류 발생 시 항상 명확한 JSON 에러 메시지 반환

  ```json
  { "status": "FAIL", "error": "OCR 결과 없음" }
  ```
* **파일 업로드 크기 제한**
  `LimitUploadSizeMiddleware` 로 업로드 파일 크기를 최대 3MB로 제한하여 Dos/대용량 공격 차단.

---


