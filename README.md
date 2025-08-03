# 전투 분석기 로그 (Battle Analyzer log)

OCR 기반으로 이미지에서 전투 정보를 인식하고, 웹 UI로 시각화하는 프로젝트입니다.
FastAPI + Celery + Redis + PaddleOCR을 사용합니다.

**서비스 주소**: [https://lostark-log.duckdns.org](https://lostark-log.duckdns.org)

![전투 분석기 스크린샷](img/스크린샷%202025-07-31%20121742.png)

---

## 개발 및 서비스 오픈 과정 (7월26일 ~ 7월30일)

### 7월 26일 – 초기 기획 및 로컬 테스트

* 전투 분석기 기본 아이디어 구체화 (OCR 기반 자동 데이터화 + 웹 시각화)
* **PaddleOCR 모델 테스트:** 여러 모델 비교 후 `korean_PP-OCRv5_mobile_rec` 선택 (인식률 88%)
* 로컬 환경에서 FastAPI 기반 이미지 업로드/OCR/DB 저장 기능 프로토타입 완성
* 원형 차트에 딜량 비율 표기, 오류값 제거를 위한 1% 미만 딜 제외 등등 기능 추가

### 7월 27일 – 아키텍처 개선 및 기능 확장

* 서비스 환경을 고려해 **Redis + Celery 비동기 구조 도입**

  * 이미지 업로드 시 OCR 처리 중에도 검색 기능을 사용할 수 있도록 개선
  * 여러 사용자가 동시에 업로드해도 **Redis 큐에 요청을 쌓아 순차적으로 처리** 가능하도록 구성
* 전투 기록 조회/검색, 통계 API 등 세부 기능 추가
* 웹 UI 시각화 보강 (검색 필터링 기능,차트 중앙 전투 시간, OCR Raw Data 표시 등)

### 7월 28일 – 배포 환경 구축

* Docker Compose 기반 **web + worker + redis 컨테이너화**
  → Azure VM(4vCPU, 16GB) 환경에서 독립적으로 서비스 실행 가능하도록 설정
* **Nginx + Certbot**으로 HTTPS 지원 및 리버스 프록시 구성
* 공유 볼륨(shared) 권한 설정 및 파일 보안 정책 반영

### 7월 29일 – 서비스 홍보

* 새벽 1시 로스트아크 인벤 커뮤니티에 홍보글 게시
* 초기 사용자 피드백 중 우선도 높은 피드백 바로 반영(업로드 제한 조정)

### 7월 30일 – 피드백 반영

* 전투력 입력 추가
* UI개선 및 로직 수정

---

## 사용자 피드백

* **홍보 및 초기 사용자 유입**
  2025년 7월 29일 인벤에 홍보글 게시 → 3일 후 조회수 **6,179회**, 댓글 24개.
  사용자들이 피드백 제공(업로드 용량 제한, 전투력 입력 기능 요청 등).
  
* **피드백 반영 및 개선**

  * 고해상도 유저를 위한 이미지 업로드 용량 제한 완화(1MB > 3MB)
  * 전투력 입력 기능 추가
  * UI 개선 (전투 시간 위치 수정, DPS, 전투력 표시 추가)
  * 중복 데이터 처리 로직 보완 ({record_info}, {battle_time}에서 {boss_name}, {difficulty}, {gate_number} 추가)
* **사용 현황 (8/1 기준)**

  * 업로드 횟수 **193건** (이 중 약 60건은 테스트/운영자가 업로드)
  * 총 133\~134판의 전투 로그 수집 및 분석됨

---

## 주요 기능

### 1) 이미지 업로드 및 OCR 인식

* PNG/JPG 이미지 업로드 지원 (파일 선택 / 드래그 앤 드롭 / Ctrl+V 붙여넣기)
* 업로드 시 전투력 입력 가능 (100 단위)
* PaddleOCR 기반으로 **보스명, 전투 시간, 딜량** 자동 추출
* 업로드 완료 후 자동으로 전투 상세 화면으로 이동

### 2) 전투 기록 조회 & 검색

* DB에 저장된 전투 기록을 최신순으로 목록 조회
* **검색 기능**
  * 레이드 ID 직접 검색
  * 레이드 이름, 난이도, 관문, 날짜, 시간으로 필터링
* 전체 업로드된 판수를 실시간 카운트로 표시

### 3) 전투 상세 화면 (시각화)

* 원형 차트로 플레이어별 딜량 비율 표시
* **전투 시간 중앙 표시** (mm\:ss)
* DPS 계산 및 전투력 표시
* **필터링 검색 기능**
  * 1% 미만 딜량 제외(인식을 잘못한 경우 제외시키기 위해)
  * 에스더 딜량 제외 후 전체 데이터 재계산
* 오른쪽 요약 패널에서 플레이어별 딜량/비율/전투력 상세 확인 가능

### 4) OCR Raw Data 보기

* 플레이어별 OCR 인식 원본 텍스트를 개별적으로 확인 및 세부정보를 확안할 수 있는 기능 제공

### 5) 통계

* 업로드 횟수를 실시간 통계로 제공

---

## 배포 환경

* **구성**

  ```
  [클라이언트 브라우저]
          ↓ HTTPS (443)
   [Nginx + Certbot]
          ↓ 내부 프록시
   [Docker Compose: web, worker, redis]
  ```

  1. **Nginx**: 리버스 프록시 역할

     * `lostark-log.duckdns.org` 도메인으로 들어오는 트래픽을 FastAPI(`web`) 컨테이너로 전달
     * 정적 리소스 캐싱 가능
  2. **Certbot (Let's Encrypt)**:

     * DuckDNS 도메인으로 SSL 인증서 발급 및 자동 갱신
     * HTTPS 연결을 지원 (자동 80 → 443 리다이렉트)
  3. **Docker Compose**:

     * `web`(FastAPI) + `worker`(Celery) + `redis` 컨테이너를 내부 네트워크로 구동
     * VM 내부에서 서비스 간 통신만 가능하게 분리
  4. **VM 환경 (Azure)**:

     * VM: `Standard_D4_v4` (4 vCPU, 16GB RAM)
     * OS: Ubuntu 20.04 LTS
     * DuckDNS를 사용해 동적 IP 자동 업데이트

---

## OCR 모델 (PaddleOCR)

- **모델명**: `korean_PP-OCRv5_mobile_rec` (PaddleOCR 3.0 기준)
- **지원 언어**: 한국어, 영어, 숫자
- **평균 인식정확도**: 약 **88.0%** 
- **모델 크기**: 약 14 MB (모바일 최적화)
- **특징**:
  - PP‑OCRv4 대비 정밀도 약 +13 % 향상
  - 한국어 정식 지원, 한글/숫자 텍스트 인식에 특화
  - Standard_D4s_v4 4코어 CPU 환경에서도 1장에 5초정도 소모됨

---

## 사용자 요청 → 처리 흐름 요약

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

---

## API 주요 엔드포인트

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

## 보안 관점에서 신경 쓴 부분

### 1) 업로드 파일 보안

* **확장자(Content-Type) 이중 검증**
  업로드 시 타입(`image/png`, `image/jpeg`)과 실제 확장자를 동시에 체크합니다.

  ```python
  allowed_types = ["image/png", "image/jpeg"]
  if file.content_type not in allowed_types:
      raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")
  ```
* **`imghdr`로 실제 이미지 여부 확인**
  악성 스크립트를 이미지로 위장하는 공격을 막기 위해 Python `imghdr`로 확인합니다.

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
  혹시라도 OCR을 사용해서 악성 스크립트를 삽입 할 수도 있으니 클라이언트에서 OCR Raw Data나 사용자 입력값을 출력할 때 `innerHTML` 대신 `textContent`를 사용하여 스크립트 삽입(XSS) 차단.

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
---


### 4) 디렉토리/데이터 접근 제어 (실행 권한 제거)

* **공유 볼륨(`shared`)의 실행 권한 제거**

  * 업로드된 이미지가 저장되는 `shared` 디렉토리는 웹 서버에서 실행 권한을 제거해 두었기 때문에,
    혹시나 악성 스크립트 파일이 업로드되더라도 실행되지 않음.
  * 내부적으로 `FastAPI`와 `Celery Worker`가 파일을 읽기/삭제만 하며 외부 접근은 차단됨.

---

### 5) 서비스 안정성 & 기타

* **Docker 재시작 정책**
  `restart: unless-stopped` 설정으로 서비스가 비정상 종료돼도 자동으로 재시작.
* **파일 업로드 크기 제한**
  `LimitUploadSizeMiddleware` 로 업로드 파일 크기를 최대 3MB로 제한.

---

## 폴더 구조

```
.
├── web/                      # FastAPI 웹 서버 (UI, API)
│   ├── templates/            # HTML 템플릿 디렉토리
│   │   └── index.html        # 메인 UI 페이지
│   ├── dockerfile            # web 컨테이너 Docker 빌드 설정
│   ├── requirements.txt      # web 컨테이너 Python 의존성 패키지
│   └── web.py                 # FastAPI 서버 엔트리포인트
│
├── worker/                   # Celery Worker (OCR 처리)
│   ├── dockerfile            # worker 컨테이너 Docker 빌드 설정
│   ├── requirements.txt      # worker 컨테이너 Python 의존성 패키지
│   └── worker.py             # Celery Worker 엔트리포인트
│
├── shared/                   # web/worker 컨테이너가 공유하는 업로드 디렉토리 (자동 생성됨)
│
├── docker-compose.yml        # 컨테이너 구성
├── requirements.txt          # 프로젝트 공용 Python 의존성 패키지
└── .gitignore

```
---

