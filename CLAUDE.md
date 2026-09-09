# sourcing-radar — 프로젝트 스펙 (Claude Code용)

> 이 파일을 새 레포의 `CLAUDE.md`로 저장하고 Claude Code를 실행하세요.
> 첫 프롬프트: "CLAUDE.md의 Phase 1을 순서대로 진행해줘. 각 단계마다 실행 방법을 알려주고 내가 확인한 뒤 다음으로 넘어가."

## 1. 목표
해외 온라인 채널에서 잘 팔리는 상품을 추적하고, 그와 유사한 상품이 **국내(쿠팡·네이버)에서 판매자가 적은 경우**를 찾아 소싱 후보로 점수화하는 시스템.
최종 산출물은 "오늘의 소싱 후보 TOP 20" 대시보드.

## 2. 원칙
- 국내 데이터는 **공식 API만** 사용 (네이버 쇼핑 검색 API, 네이버 데이터랩 API). 쿠팡 스크래핑은 하지 않는다.
- 해외 스크래핑은 하루 1~2회 배치, 요청 간 지연 2~5초, robots.txt 존중. 개인 분석 용도로 소량 수집.
- 첫 파일럿 카테고리는 **주방잡화·생활소품** 한 개. 검증 후 확장.
- 비전공자 사용자를 전제로 한다: 모든 스크립트는 `README`에 실행 방법 1줄과 예상 출력을 적는다.

## 3. 기술 스택
| 영역 | 선택 | 이유 |
|---|---|---|
| 수집·분석 | Python 3.12, Playwright, httpx, pandas | 동적 페이지 대응, 데이터 처리 |
| 임베딩 | sentence-transformers(다국어), open_clip(이미지) | 상품 유사도 클러스터링 |
| DB | Supabase (Postgres) | Vercel과 궁합, 무료 티어, 대시보드에서 바로 조회 |
| 대시보드 | Next.js 15 + TypeScript + Tailwind, Vercel 배포 | 기존 스택 재사용 |
| 스케줄 | GitHub Actions cron (매일 07:00 KST) | 로컬 PC 안 켜도 동작 |

## 4. 디렉터리 구조
```
sourcing-radar/
├── CLAUDE.md
├── README.md
├── collector/                 # Python
│   ├── pyproject.toml
│   ├── config/
│   │   ├── categories.yaml    # 파일럿 카테고리·키워드 정의
│   │   └── settings.py        # env 로딩, 지연시간, 프록시
│   ├── sources/
│   │   ├── base.py            # BaseCollector: fetch → parse → save
│   │   ├── aliexpress.py      # 검색 결과의 판매량(orders)·가격·이미지
│   │   ├── temu.py            # 카테고리 베스트 페이지
│   │   ├── amazon_bestseller.py  # movers-and-shakers 순위
│   │   ├── alibaba1688.py     # 도매가·MOQ (소싱 원가 추정용)
│   │   ├── naver_shopping.py  # 공식 API: 상품수·최저가·판매처 수
│   │   └── naver_datalab.py   # 공식 API: 키워드 검색 트렌드
│   ├── matching/
│   │   ├── embed.py           # 텍스트+이미지 임베딩 생성
│   │   └── cluster.py         # 유사 상품 클러스터링 (HDBSCAN)
│   ├── scoring/
│   │   └── opportunity.py     # 기회 점수 계산
│   ├── db/
│   │   ├── schema.sql
│   │   └── client.py          # Supabase 읽기/쓰기
│   └── run.py                 # 전체 파이프라인 1회 실행
├── dashboard/                 # Next.js
│   ├── app/
│   │   ├── page.tsx           # TOP 후보 리스트
│   │   ├── product/[id]/page.tsx  # 상세: 해외 신호·국내 경쟁·마진
│   │   └── api/               # Supabase 조회 라우트
│   └── lib/supabase.ts
└── .github/workflows/daily.yml
```

## 5. DB 스키마 (핵심 테이블)
```sql
-- 해외에서 수집한 원본 상품
create table raw_products (
  id bigserial primary key,
  source text not null,            -- aliexpress | temu | amazon | 1688
  source_id text not null,
  title text,
  price_usd numeric,
  sales_count int,                 -- 누적 판매량/주문수
  rank int,                        -- 베스트셀러 순위
  image_url text,
  product_url text,
  category text,
  collected_at date not null,
  unique (source, source_id, collected_at)
);

-- 유사 상품 묶음 (하나의 "소싱 후보")
create table clusters (
  id bigserial primary key,
  label text,                      -- 대표 상품명(한글 번역)
  representative_image text,
  category text,
  created_at timestamptz default now()
);

create table cluster_members (
  cluster_id bigint references clusters(id),
  raw_product_id bigint references raw_products(id),
  primary key (cluster_id, raw_product_id)
);

-- 국내 경쟁 상황 (네이버 API)
create table domestic_signals (
  cluster_id bigint references clusters(id),
  collected_at date not null,
  keyword text,
  naver_product_count int,         -- 검색 결과 상품 수
  naver_seller_count int,          -- 판매처 수(추정)
  naver_min_price_krw int,
  naver_avg_price_krw int,
  search_trend_30d numeric,        -- 데이터랩 지수 변화율
  primary key (cluster_id, collected_at)
);

-- 소싱 원가
create table sourcing_costs (
  cluster_id bigint references clusters(id),
  source text,                     -- 1688 | aliexpress
  unit_cost_usd numeric,
  moq int,
  collected_at date
);

-- 최종 점수 (대시보드가 읽는 테이블)
create table opportunity_scores (
  cluster_id bigint references clusters(id),
  scored_at date not null,
  demand_score numeric,            -- 해외 수요
  competition_score numeric,       -- 국내 경쟁(낮을수록 좋음)
  margin_score numeric,            -- 예상 마진율
  total_score numeric,
  est_margin_rate numeric,
  primary key (cluster_id, scored_at)
);
```

## 6. 기회 점수 로직 (`scoring/opportunity.py`)
```
demand      = 해외 판매량 7일 증가율 (0~1 정규화) × 0.6 + 순위 상승폭 × 0.4
competition = log(1 + 네이버 판매처 수) 정규화          # 낮을수록 기회
margin_rate = (네이버 평균가 − (1688 단가 × 환율 × 1.35)) / 네이버 평균가
              # 1.35 = 배송·관세·수수료 대략 계수, 나중에 조정
margin      = clip(margin_rate, 0, 0.6) / 0.6

total = demand × 0.4 + (1 − competition) × 0.35 + margin × 0.25
```
- `margin_rate < 0.25`인 후보는 총점과 무관하게 제외.
- 가중치는 `config/settings.py`에 두고 파일럿 결과 보며 조정.

## 7. 단계별 계획

### Phase 1 — 기반 (1주)
1. Supabase 프로젝트 생성, `schema.sql` 적용.
2. 네이버 개발자센터에서 쇼핑검색·데이터랩 API 키 발급 → `.env`.
3. `naver_shopping.py` 구현: 키워드 1개 넣으면 상품수·최저가·판매처 수 반환. **여기까지 되면 첫 성공.**
4. `categories.yaml`에 파일럿 키워드 20개 작성.

### Phase 2 — 해외 수집 (1~2주)
5. `aliexpress.py` (Playwright): 키워드 검색 → 상위 40개 판매량·가격·이미지 저장.
6. `amazon_bestseller.py`: movers-and-shakers 카테고리 페이지 파싱.
7. `temu.py`, `alibaba1688.py`는 5·6이 안정된 뒤.
8. 실패 시 재시도 3회·지연 랜덤화·User-Agent 로테이션을 `base.py`에 공통 구현.

### Phase 3 — 매칭·점수 (1주)
9. `embed.py`: 제목(다국어 임베딩) + 이미지(CLIP) → 벡터 결합.
10. `cluster.py`: HDBSCAN으로 묶고 대표 상품명 한글화.
11. 클러스터별 대표 키워드로 네이버 API 조회 → `domestic_signals`.
12. `opportunity.py` 실행 → `opportunity_scores` 채우기.

### Phase 4 — 대시보드·자동화 (1주)
13. Next.js: TOP 20 리스트(점수·예상마진·판매처수·대표이미지).
14. 상세 페이지: 해외 판매량 추이 그래프, 국내 경쟁 상품 링크, 1688 원가.
15. GitHub Actions 매일 실행 → Vercel 배포.

### Phase 5 — 검증 (2주)
16. TOP 10 중 2~3개를 소량 실제 소싱해서 점수 vs 실제 판매를 비교.
17. 가중치·계수 조정 후 카테고리 확장.

## 8. 환경변수 (`.env.example`)
```
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
PROXY_URL=            # 선택, 해외 스크래핑용
USD_KRW_RATE=1380     # 나중에 API로 대체
```

## 9. Claude Code에게 주는 작업 규칙
- 한 번에 한 Phase 항목만 구현하고, 실행 명령과 기대 출력을 사용자에게 보여준 뒤 다음으로 넘어간다.
- 스크래퍼는 반드시 `--limit 5 --dry-run` 옵션을 먼저 제공해서 소량 테스트가 가능하게 한다.
- 외부 사이트 구조가 바뀌어 파싱이 실패하면 예외를 삼키지 말고 어떤 셀렉터가 실패했는지 로그로 남긴다.
- 코드 설명은 비전공자 기준으로 짧게.
