# sourcing-radar

해외에서 잘 팔리는 상품을 추적하고, 국내에서 경쟁이 약한 상품을 찾아 **소싱 후보 TOP 20**을 뽑아 주는 도구입니다.
전체 설계는 [`CLAUDE.md`](./CLAUDE.md)에 있습니다.

## 지금 상태: Phase 1 (기반)

| # | 항목 | 상태 |
|---|---|---|
| 1 | Supabase 프로젝트 + `schema.sql` | 코드 준비됨 · **사용자가 적용해야 함** |
| 2 | API 키 3종 (검색광고 · 쿠팡 파트너스 · NAVER API HUB) → `.env` | **사용자가 발급해야 함** |
| 3 | 국내 신호 수집기 3개 + 합치기 (`domestic.py`) | 완료 (오프라인 테스트 18개 통과) |
| 4 | `categories.yaml` 파일럿 키워드 20개 | 완료 |

### 왜 API가 세 개인가
네이버 쇼핑 검색 API(상품수·판매처수)가 2026년 7월 31일 종료됐고 대체 API가 없습니다. 그래서 국내 신호를 세 공식 API로 나눠 받습니다.

| 알고 싶은 것 | 어디서 | 지표 |
|---|---|---|
| 경쟁이 얼마나 센가 | 네이버 검색광고 API 키워드도구 | 월간 검색수, 광고 클릭수, 경쟁정도(낮음·중간·높음) |
| 국내에서 얼마에 팔리나 | 쿠팡 파트너스 API 상품 검색 | 최저가·평균가·중앙값, 로켓배송 비율 |
| 수요가 늘고 있나 | NAVER API HUB 데이터랩 | 검색어트렌드·쇼핑클릭 30일 변화율 |

## 처음 한 번만 하는 설정

### 0. Python 환경
```bash
cd collector
python -m venv .venv && source .venv/bin/activate    # 윈도우: .venv\Scripts\activate
pip install -e ".[dev]"
```
예상 출력: 설치 로그 뒤 에러 없이 프롬프트가 돌아오면 성공.

### 1. Supabase
1. https://supabase.com → **Start your project** → GitHub 로그인 → **New project**.
2. 이름 `sourcing-radar`, 비밀번호는 **Generate** 후 메모, Region은 Seoul(없으면 Tokyo), Free 플랜 → **Create**.
3. 왼쪽 메뉴 **SQL Editor** → **New query** → `collector/db/schema.sql` 내용을 붙여넣고 **Run**. `Success. No rows returned` 가 뜨면 성공.
4. **Table Editor** 에 표 7개(raw_products, clusters, cluster_members, domestic_signals, sourcing_costs, opportunity_scores, keyword_snapshots)가 보이는지 확인.
5. **Project Settings → API** 에서 `Project URL` → `SUPABASE_URL`, `service_role` 키 → `SUPABASE_SERVICE_KEY`. (`anon` 키가 아닙니다.)

### 2-A. 네이버 검색광고 API (경쟁 지표)
광고를 실제로 집행할 필요는 없습니다. 계정과 API 키만 만들면 무료입니다.
1. https://searchad.naver.com → **신규가입** (네이버 아이디로 가입, 사업자 없어도 개인으로 가능).
2. 로그인 후 광고시스템으로 들어가 상단 **도구 → API 사용 관리**.
3. **네이버 검색광고 API 서비스 신청** 동의 → **액세스라이선스 발급**.
4. 화면에 나오는 **액세스라이선스** → `NAVER_AD_ACCESS_LICENSE`, **비밀키**(발급 직후 한 번만 보임) → `NAVER_AD_SECRET_KEY`.
5. 광고시스템 화면 **오른쪽 위 계정명 옆 숫자**(CUSTOMER_ID) → `NAVER_AD_CUSTOMER_ID`.

### 2-B. 쿠팡 파트너스 API (가격 지표)
1. https://partners.coupang.com → 쿠팡 계정으로 **가입**. 사이트/블로그 주소를 묻는데 없으면 SNS 주소나 `https://github.com/ohgunwoo555/shopping-idea` 를 적어도 됩니다.
2. 가입 승인 후 상단 **링크 생성 → API**.
3. **API 키 발급** → **Access Key** → `COUPANG_ACCESS_KEY`, **Secret Key** → `COUPANG_SECRET_KEY`.
4. 신규 계정은 "임시 승인" 상태로 시작합니다. 이 상태에서 API가 401을 돌려주면 최종 승인(보통 며칠, 활동 실적 필요)을 기다려야 합니다. 그동안은 `--only searchad,datalab` 으로 나머지 두 소스만 먼저 확인하세요.

### 2-C. NAVER API HUB (수요 추이)
1. https://www.ncloud.com → **회원가입**. 개인도 되지만 **본인인증과 결제수단(카드) 등록**이 필요합니다. HUB는 현재 무료라 과금되지 않습니다.
2. 오른쪽 위 **콘솔** → 왼쪽 위 **Services → Application Services → NAVER API HUB**.
3. 왼쪽 **Application → Application 등록** → API 목록에서 **데이터랩(검색어트렌드)** 와 **데이터랩(쇼핑인사이트)** 체크 → 다음 → 이름 `sourcing-radar` → 완료.
4. 목록에서 방금 만든 항목의 **인증 정보** → 두 값을 `NAVER_HUB_CLIENT_ID`, `NAVER_HUB_CLIENT_SECRET` 에.
5. 호출 주소는 `https://naverapihub.apigw.ntruss.com` 입니다(`.env.example` 기본값). 세부 경로는 3단계 뒤에 `python -m sources.naver_datalab --probe` 로 자동으로 찾습니다. 문서를 열어 볼 필요가 없습니다.

### 3. `.env` 만들기
```bash
cp .env.example .env        # 레포 루트에서. 윈도우: Copy-Item .env.example .env
```
`.env` 를 열어 위에서 모은 값을 등호 오른쪽에 따옴표 없이 붙입니다. 이 파일은 git 에 올라가지 않습니다.

## 실행 방법

모든 명령은 `collector/` 폴더에서, 가상환경을 켠 상태로 실행합니다.

### HUB 데이터랩 주소 찾기 (처음 한 번)
```bash
python -m sources.naver_datalab --probe
```
예상 출력:
```
[search] 기본 주소 https://naverapihub.apigw.ntruss.com · 헤더 X-NCP-APIGW-API-KEY-ID
   /datalab/v1/search                            → ✔ 사용 가능
   ...
.env 에 아래 두 줄을 넣으세요:
NAVER_HUB_SEARCH_PATH=/datalab/v1/search
NAVER_HUB_SHOPPING_PATH=/datalab/v1/shopping/category/keywords
```
출력된 두 줄을 `.env` 에 붙여 넣습니다. 전부 ✘ 이면 마지막 줄 안내대로 키·체크 항목·주소를 확인합니다.

### 키워드 1개 조회 (첫 성공 확인용)
```bash
python -m sources.domestic --keyword "실리콘 주걱" --category kitchen_living
```
예상 출력:
```
키워드: 실리콘 주걱
  [경쟁] 월간 검색수 18,400 · 광고 클릭 96.3 · 경쟁정도 높음
  [가격] 쿠팡 최저 1,900원 · 평균 7,850원 · 중앙값 5,900원 (상위 50개)
  [수요] 검색 추이 +4.2% · 쇼핑 클릭 추이 -1.8%

(--save 를 붙이면 Supabase 의 keyword_snapshots 테이블에 저장됩니다)
```
숫자는 실제 결과에 따라 다릅니다. 어느 한 소스가 실패하면 그 줄에 `(… 결과 없음)` 이 뜨고, 위쪽 로그에 어떤 키를 고쳐야 하는지 한글로 나옵니다.

### 소스 하나씩 따로 확인
```bash
python -m sources.naver_searchad   --keyword "실리콘 주걱"   # 경쟁
python -m sources.coupang_partners --keyword "실리콘 주걱"   # 가격
python -m sources.naver_datalab    --keyword "실리콘 주걱" --cid 50000008   # 수요
```

### 파일럿 키워드 20개 전부
```bash
python -m sources.domestic --all                       # 화면 출력만
python -m sources.domestic --all --limit 5             # 앞의 5개만
python -m sources.domestic --all --only searchad,datalab   # 쿠팡 승인 전
python -m sources.domestic --all --save                # Supabase 에 저장
python -m sources.domestic --all --json > today.json
```
`--save` 시 Supabase **Table Editor → keyword_snapshots** 에 20행이 생깁니다. 매일 실행하면 날짜별로 쌓입니다.

### 테스트 (인터넷·API 키 없이 실행 가능)
```bash
pytest
```
예상 출력: `18 passed`.

## 지표 읽는 법
- **경쟁정도**는 네이버가 광고 입찰 경쟁을 낮음·중간·높음으로 요약한 값입니다. 점수 계산에서는 0·0.5·1 로 씁니다. 판매처 수 대신 쓰는 대체 지표라 절대값보다 키워드 간 비교에 의미가 있습니다.
- **쿠팡 평균가**는 검색 상위 50개 기준입니다. 스펙의 마진 계산(`(평균가 − 1688단가×환율×1.35) / 평균가`)에 이 값을 넣습니다.
- **30일 변화율**은 데이터랩 지수의 최근 30일 평균을 직전 30일 평균으로 나눈 값에서 1을 뺀 것입니다. +0.2 면 수요가 20% 늘었다는 뜻입니다.

## 폴더 구조
```
collector/
├── config/categories.yaml      # 파일럿 키워드 20개 + 쇼핑인사이트 카테고리 코드
├── config/settings.py          # .env 읽기, 가중치·지연시간 설정
├── sources/base.py             # 수집기 공통 뼈대 (fetch → parse → save)
├── sources/naver_searchad.py   # 검색광고 키워드도구
├── sources/coupang_partners.py # 쿠팡 상품 검색
├── sources/naver_datalab.py    # HUB 데이터랩
├── sources/domestic.py         # 세 소스 합치기 + 저장
├── db/schema.sql               # Supabase 테이블 정의
├── db/client.py                # Supabase 저장/조회
└── tests/                      # 오프라인 테스트
```

## 다음 단계
Phase 2 — 알리익스프레스·아마존 베스트셀러 수집 (`CLAUDE.md` 7절 5~8번).
