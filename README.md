# sourcing-radar

해외에서 잘 팔리는 상품을 추적하고, 국내(네이버)에서 판매자가 적은 상품을 찾아 **소싱 후보 TOP 20**을 뽑아 주는 도구입니다.
전체 설계는 [`CLAUDE.md`](./CLAUDE.md)에 있습니다.

## 지금 상태: Phase 1 (기반)

| # | 항목 | 상태 |
|---|---|---|
| 1 | Supabase 프로젝트 + `schema.sql` | 코드 준비됨 · **사용자가 적용해야 함** |
| 2 | 네이버 API 키 발급 → `.env` | **사용자가 발급해야 함** |
| 3 | `naver_shopping.py` (키워드 → 상품수·최저가·판매처 수) | 완료 (오프라인 테스트 통과) |
| 4 | `categories.yaml` 파일럿 키워드 20개 | 완료 |

## 처음 한 번만 하는 설정

### 0. Python 환경
```bash
cd collector
uv venv .venv && source .venv/bin/activate     # uv 가 없으면: python -m venv .venv
uv pip install -e ".[dev]"                      # 또는: pip install -e ".[dev]"
```
예상 출력: 패키지 설치 로그. 마지막에 에러 없이 프롬프트가 돌아오면 성공.

### 1. Supabase
1. https://supabase.com 에서 새 프로젝트 생성 (무료 티어).
2. 왼쪽 메뉴 **SQL Editor** → `collector/db/schema.sql` 내용을 붙여넣고 **Run**.
3. **Project Settings → API** 에서 `Project URL` 과 `service_role` 키를 복사.

### 2. 네이버 API 키
1. https://developers.naver.com → **Application → 애플리케이션 등록**.
2. 사용 API에 **검색** 과 **데이터랩(쇼핑인사이트)** 체크. 서비스 환경은 "WEB 설정"에 아무 URL(예: `http://localhost`)이나 넣으면 됩니다.
3. 발급된 `Client ID`, `Client Secret` 을 복사.

### 3. `.env` 만들기
```bash
cp .env.example .env     # 레포 루트에서
```
`.env` 를 열어 위에서 복사한 값을 채웁니다. 이 파일은 git 에 올라가지 않습니다.

## 실행 방법

모든 명령은 `collector/` 폴더에서, 가상환경을 켠 상태로 실행합니다.

### 키워드 1개 조회 (첫 성공 확인용)
```bash
python -m sources.naver_shopping --keyword "실리콘 주걱"
```
예상 출력:
```
INFO sources.base: [naver_shopping] fetch: 실리콘 주걱
키워드: 실리콘 주걱
  상품 수(전체)     : 152,340
  판매처 수(추정)   : 187  (상위 300개 기준)
  최저가            : 890원
  평균가 / 중앙값   : 6,420원 / 4,900원

(--save 를 붙이면 Supabase 의 keyword_snapshots 테이블에 저장됩니다)
```
숫자는 실제 검색 결과에 따라 다릅니다. 키가 없거나 틀리면 무엇을 고쳐야 하는지 한글로 안내가 뜹니다.

### 파일럿 키워드 20개 전부 조회
```bash
python -m sources.naver_shopping --all                # 화면 출력만
python -m sources.naver_shopping --all --limit 5      # 앞의 5개만
python -m sources.naver_shopping --all --save         # Supabase 에 저장
python -m sources.naver_shopping --all --json > today.json
```
예상 출력: 키워드마다 위와 같은 블록이 하나씩. `--save` 시 Supabase **Table Editor → keyword_snapshots** 에 20행이 생깁니다.

### 테스트 (인터넷·API 키 없이 실행 가능)
```bash
pytest
```
예상 출력: `7 passed`.

## 판매처 수는 어떻게 세나요?
네이버 API는 "판매처 수"를 직접 주지 않습니다. 검색 결과 상위 300개(`NAVER_MAX_ITEMS`)를 받아
서로 다른 **판매처 이름(mallName)** 이 몇 개인지 셉니다. 중고·단종·판매예정 상품은 제외하고,
가격비교 묶음("네이버")은 판매처로 세지 않습니다. 절대값보다는 키워드 간 **상대 비교**에 쓰는 지표입니다.

## 폴더 구조
```
collector/
├── config/categories.yaml   # 파일럿 키워드 20개 (한글 + 영문)
├── config/settings.py       # .env 읽기, 가중치·지연시간 설정
├── sources/base.py          # 수집기 공통 뼈대 (fetch → parse → save)
├── sources/naver_shopping.py
├── db/schema.sql            # Supabase 에 적용할 테이블 정의
├── db/client.py             # Supabase 저장/조회
└── tests/                   # 오프라인 테스트
```

## 다음 단계
Phase 2 — 알리익스프레스·아마존 베스트셀러 수집 (`CLAUDE.md` 7절 5~8번).
