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

-- 국내 경쟁 상황 (네이버 API)
create table if not exists domestic_signals (
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

-- Phase 1 검증용: 키워드 단위로 네이버 조회 결과를 그대로 쌓아 두는 테이블.
-- 클러스터가 아직 없을 때(Phase 1~2) 키워드별 국내 경쟁 추이를 보기 위해 쓴다.
create table if not exists keyword_snapshots (
  id bigserial primary key,
  keyword text not null,
  category text,
  collected_at date not null,
  naver_product_count int,
  naver_seller_count int,
  naver_min_price_krw int,
  naver_avg_price_krw int,
  naver_median_price_krw int,
  sample_size int,                 -- 판매처 수 추정에 사용한 상품 수
  unique (keyword, collected_at)
);

-- 자주 쓰는 조회용 인덱스
create index if not exists idx_raw_products_source_date on raw_products (source, collected_at);
create index if not exists idx_opportunity_scores_date on opportunity_scores (scored_at, total_score desc);
create index if not exists idx_keyword_snapshots_date on keyword_snapshots (collected_at);
