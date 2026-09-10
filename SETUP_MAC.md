# 맥에서 처음 실행하기 (Phase 1 확인용)

준비물: API 키 메모 (Supabase 2개, 검색광고 3개, 쿠팡 2개, NAVER API HUB 2개).
아래 명령은 **터미널** 앱(Spotlight에서 Cmd+Space → "터미널")에 한 줄씩 붙여 넣고 Enter.

## 1. 도구 확인 (처음 한 번)
```bash
git --version
python3 --version
```
- `git` 이 없다고 하면 설치 창이 뜹니다. **설치** 누르고 끝나면 다시 실행.
- `python3` 이 3.11 미만이거나 없으면 https://www.python.org/downloads/macos 에서 설치.

## 2. 코드 받기 (처음 한 번)
```bash
cd ~/Desktop
git clone -b claude/sourcing-radar-spec-eb6drc https://github.com/ohgunwoo555/shopping-idea.git
cd shopping-idea
```
이미 받아 둔 폴더가 있으면 대신:
```bash
cd ~/Desktop/shopping-idea
git pull
```

## 3. .env 만들기 (처음 한 번)
```bash
cp .env.example .env
open -e .env
```
텍스트 편집기가 열리면 등호 오른쪽에 키를 붙여 넣고 Cmd+S 로 저장 후 닫기.
HUB 항목은 이렇게 두 줄을 비워 둔 채 시작:
```
NAVER_HUB_BASE_URL=https://naverapihub.apigw.ntruss.com
NAVER_HUB_AUTH_STYLE=ncp
NAVER_HUB_SEARCH_PATH=
NAVER_HUB_SHOPPING_PATH=
```

## 4. Python 환경 (처음 한 번)
```bash
cd collector
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
마지막 줄 결과가 `20 passed` 면 준비 완료.

## 5. HUB 데이터랩 경로 찾기 (처음 한 번)
```bash
python -m sources.naver_datalab --probe
```
끝에 나오는 두 줄(`NAVER_HUB_SEARCH_PATH=…`, `NAVER_HUB_SHOPPING_PATH=…`)을 복사해서
```bash
open -e ../.env
```
로 `.env` 를 열고 같은 이름의 줄에 덮어쓴 뒤 저장.

## 6. 첫 실행
```bash
python -m sources.domestic --keyword "실리콘 주걱" --category kitchen_living
```
경쟁·가격·수요 세 줄에 숫자가 나오면 성공.
쿠팡이 아직 승인 전이면:
```bash
python -m sources.domestic --keyword "실리콘 주걱" --category kitchen_living --only searchad,datalab
```

## 7. Supabase 저장까지 확인
```bash
python -m sources.domestic --all --limit 3 --save
```
Supabase → Table Editor → keyword_snapshots 에 3행이 보이면 Phase 1 완료.

## 다음에 다시 열 때
터미널을 새로 열면 아래 두 줄만 먼저 실행하면 됩니다.
```bash
cd ~/Desktop/shopping-idea/collector
source .venv/bin/activate
```

## 막히면
화면에 나온 글자를 그대로 복사해 Claude 대화창에 붙여 넣기.
