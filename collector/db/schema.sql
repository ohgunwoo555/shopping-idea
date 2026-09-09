-- sourcing-radar DB 스키마
-- 적용 방법: Supabase 대시보드 > SQL Editor > 이 파일 내용을 붙여넣고 Run
-- (여러 번 실행해도 안전하도록 if not exists 를 붙였다)

-- 해외에서 수집한 원본 상품
create table if not exists raw_products (
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
create table if not exists clusters (
  id bigserial primary key,
  label text,                      -- 대표 상품명(한글 번역)
  representative_image text,
  category text,
  created_at timestamptz default now()
);

create table if not exists cluster_members (
  cluster_id bigint references clusters(id),
  raw_product_id bigint references raw_products(id),
  primary key (cluster_id, raw_product_id)
);

-- 국내 경쟁 상황 (검색광고 API + 쿠팡 파트너스 API + 데이터랩)
-- ※ 네이버 쇼핑 검색 API(상품수·판매처수)는 2026-07-31 종료되어 아래 지표로 대체했다.
create table if not exists domestic_signals (
  cluster_id bigint references clusters(id),
  collected_at date not null,
  keyword text,
  ad_monthly_search int,           -- 검색광고: 월간 검색수 (PC+모바일)
  ad_monthly_clicks numeric,       -- 검색광고: 월평균 광고 클릭수 (PC+모바일)
  ad_comp_idx text,                -- 검색광고: 경쟁정도 (낮음|중간|높음)
  ad_comp_score numeric,           -- 경쟁정도를 0/0.5/1 로 바꾼 값
  coupang_min_price_krw int,       -- 쿠팡 파트너스 검색 결과 최저가
  coupang_avg_price_krw int,       -- 쿠팡 파트너스 검색 결과 평균가
  search_trend_30d numeric,        -- 데이터랩 검색어트렌드: 최근30일/직전30일 − 1
  shopping_click_trend_30d numeric,-- 데이터랩 쇼핑인사이트: 최근30일/직전30일 − 1
  primary key (cluster_id, collected_at)
);

-- 소싱 원가
create table if not exists sourcing_costs (
  cluster_id bigint references clusters(id),
  source text,                     -- 1688 | aliexpress
  unit_cost_usd numeric,
  moq int,
  collected_at date
);

-- 최종 점수 (대시보드가 읽는 테이블)
create table if not exists opportunity_scores (
  cluster_id bigint references clusters(id),
  scored_at date not null,
  demand_score numeric,            -- 해외 수요
  competition_score numeric,       -- 국내 경쟁(낮을수록 좋음)
  margin_score numeric,            -- 예상 마진율
  total_score numeric,
  est_margin_rate numeric,
  primary key (cluster_id, scored_at)
);

-- Phase 1 검증용: 키워드 단위로 국내 신호를 그대로 쌓아 두는 테이블.
-- 클러스터가 아직 없을 때(Phase 1~2) 키워드별 국내 경쟁 추이를 보기 위해 쓴다.
-- 세 수집기(naver_searchad / coupang_partners / naver_datalab)가 각자 자기 컬럼만 채운다.
create table if not exists keyword_snapshots (
  id bigserial primary key,
  keyword text not null,
  category text,
  collected_at date not null,
  -- 네이버 검색광고 키워드도구
  ad_monthly_search_pc int,
  ad_monthly_search_mobile int,
  ad_monthly_clicks numeric,
  ad_comp_idx text,
  ad_comp_score numeric,
  ad_pl_avg_depth int,             -- 월평균 광고 노출 순위 깊이 (클수록 광고주 많음)
  -- 쿠팡 파트너스 상품 검색
  coupang_sample_size int,
  coupang_min_price_krw int,
  coupang_avg_price_krw int,
  coupang_median_price_krw int,
  coupang_rocket_ratio numeric,    -- 로켓배송 비율 (0~1)
  -- 네이버 데이터랩 (NAVER API HUB)
  search_trend_30d numeric,
  shopping_click_trend_30d numeric,
  unique (keyword, collected_at)
);

-- 자주 쓰는 조회용 인덱스
create index if not exists idx_raw_products_source_date on raw_products (source, collected_at);
create index if not exists idx_opportunity_scores_date on opportunity_scores (scored_at, total_score desc);
create index if not exists idx_keyword_snapshots_date on keyword_snapshots (collected_at);
