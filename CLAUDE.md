# External Event Ledger — samsung.com 외부 요인 대시보드

## 프로젝트 개요
samsung.com organic traffic/revenue에 영향을 줄 수 있는 **외부 요인**(뉴스, 경쟁사, AI
플랫폼 변화, 거시경제)을 매일 자동 수집해 보여주는 무료 대시보드. 전부 무료 티어로만
구성 — 유료 API/서비스는 절대 쓰지 않는다는 게 하드 요구사항.

- **배포**: GitHub Pages (Source: GitHub Actions), 저장소 `hyunho0812/scom-external`
- **URL**: `https://hyunho0812.github.io/scom-external/`
- **UI 언어**: 한국어. 코드 주석/커밋은 영어.
- **자동화**: `.github/workflows/daily-update.yml`이 매일 21:00 UTC(06:00 KST) 전체
  파이프라인을 실행하고 결과를 커밋. 28일엔 IMF 월간 통계도 추가로 실행.

## 파일 구조와 역할

```
scripts/
  collect_gdelt.py    Layer 1a — GDELT 무료 뉴스풀 (키 불필요, 10개 쿼리 전부 시도)
  collect_news.py     Layer 1  — NewsAPI+GDELT → 키워드 사전필터 → LLM 판단체인
  collect_feeds.py    Layer 2  — 1차 소스 RSS(feeds.txt) → 키워드 사전필터 → LLM 판단체인
  llm_common.py       Gemini→Groq→Mistral 판단체인 (news/feeds 공유, FILTER_SYSTEM 프롬프트)
  collect_wiki.py     위키피디아 일별 조회수 (경쟁사 관심도 대리지표), 최초 730일 백필+이후 증분
  collect_imf.py      Layer 3 — IMF SDMX 월간 통계 (28일만 실행)
  optimize.py         매일 Gemini가 queries.txt/kw_filters.json 자동 튜닝 (최대 브랜드쿼리 4개)
  check_model.py      Gemini/Groq/Mistral 3개 모델 상태 체크 (매일) → data/model_status.json
  check_feeds.py       feeds.txt의 15개 피드 파싱 상태 체크 (매일) → data/feed_health.json
  merge_past_events.py 수동 도구 — 이벤트 배치를 events.json에 병합(스키마 검증·정렬·중복제거)
  check_feed_translation.py 수동 진단 — events.json 내 피드 항목 번역 품질 점검
  build.py             모든 data/*.json → index.html 재빌드 (대시보드 JS 전부 여기 있음)

data/                 자동 생성/갱신되는 JSON들 (스키마는 각 스크립트 상단 docstring 참고)
feeds.txt             1차 소스 RSS 목록 (15개: AI플랫폼4 + 회사1 + 트렌드10)
queries.txt           뉴스 검색어 10개 (optimize.py가 매일 조정)
interests.txt         우선순위 토픽 (LLM 프롬프트에 자동 반영)
index.html            빌드 산출물 — 직접 수정 금지, 항상 build.py로 재생성
```

## 핵심 설계 원칙 (바꾸기 전에 꼭 이해할 것)

### 1. 3단계 LLM 판단 체인 (news/feeds 동일)
`llm_common.py`의 `llm_filter(article)`이 **Gemini → Groq → Mistral** 순서로 시도.
세 개가 완전히 동일한 `FILTER_SYSTEM` 프롬프트와 JSON 스키마를 쓴다 — Gemini 할당량이
초과돼도 분류 품질이 하드코딩된 기본값으로 떨어지지 않고 Groq/Mistral이 똑같이 정밀
판단한다. **셋 다 실패하면 저장하지 않고 건너뛴다** (영어 원문이나 추측성 분류 저장 금지
원칙 — 이 프로젝트 전체에서 일관되게 지킴).

각 콜렉터는 이 판단 전에 **무료 키워드 사전필터**를 먼저 거친다 (LLM 호출 비용 절감).
사전필터를 통과 못 하면 LLM 호출 자체를 안 함.

- Gemini: `GEMINI_API_KEY`, `GEMINI_MODEL` (기본 `gemini-2.5-flash`)
- Groq: `GROQ_API_KEY`, `GROQ_MODEL` (기본 `openai/gpt-oss-120b` — llama-3.3-70b-versatile은
  2026-06-17 폐기공지 받아서 교체함)
- Mistral: `MISTRAL_API_KEY`, `MISTRAL_MODEL` (기본 `mistral-small-latest`, 무료
  Experiment 티어라 분당 2회 제한 — 3순위라 괜찮음)

### 2. "검증된 공식 소스만" 원칙
feeds.txt에 넣는 모든 RSS는 **반드시 실제로 fetch해서 검증** 후에만 추가. 3rd파티
스크래퍼/미러(예전에 Anthropic·Perplexity가 이랬음)는 정책상 제외 — 관리자가 손 놓으면
조용히 멈추는 리스크 때문. 회사 뉴스룸이 JS 렌더링 페이지라 RSS가 없으면 억지로 추측
URL을 넣지 말고, feeds.txt에 "확인했지만 없음" 주석으로 남길 것.

### 3. 이벤트 스키마의 "confidence"와 "impact_strength" 정의
- `confidence`: 이 판단(impact_direction/strength)이 맞다는 **확신도** (high/med/low).
  기사 정확도나 트렌드 일관성이 아님. FILTER_SYSTEM 프롬프트에 명시돼 있음.
- `impact_strength`: samsung.com **웹 트래픽**에 대한 영향 크기(1~5). revenue 아님.

### 4. 한글 번역 스타일
`description`은 "다/했다/이다"체로 끝나야 함(요/습니다체 금지), 두 번째 문장은 "구매에
미치는 영향"이 아니라 **"samsung.com 트래픽 자체에 미치는 영향"**을 다뤄야 함. 쉬운
일상 단어 사용(전문용어·딱딱한 문어체 금지).

### 5. 키워드 필터에서 거르지 않는 것 (2026-07 변경)
스포츠와 계절성/일반론 콘텐츠를 더 이상 자동으로 거르지 않음 — IDC/TrendForce/Gartner/
Pew Research 같은 정기 트렌드 리서치 소스를 새로 추가하면서, 이들의 콘텐츠(점진적 트렌드
분석)가 옛 규칙("특정 날짜있는 사건만") 때문에 계속 걸러지는 문제를 발견해서 완화함.

### 6. GitHub Actions 공유 IP의 레이트리밋
GDELT가 종종 429를 낸다 — 우리 요청량보다는 같은 IP 대역을 쓰는 다른 워크플로들 때문일
가능성이 큼. 그래서 **재시도 대기시간을 짧게(10초/20초)** 유지하고, 쿼리 수를 억지로
줄이기보다 **10개 다 시도하고 실패하면 그냥 스킵**하는 쪽을 택함(상한선을 두면 최대
커버리지만 낮아지고 성공률은 안 오를 수 있어서).

## 검증 체크리스트 (수정 후 항상 실행)

```bash
# 전체 컴파일
python3 -c "import py_compile,glob; [py_compile.compile(f,doraise=True) for f in glob.glob('scripts/*.py')]"

# events.json 무결성 (중복 없음, 정렬됨, 날짜 형식)
python3 -c "
import json
ev=json.load(open('data/events.json'))
ids=[e['event_id'] for e in ev]; dt=[(e['date'],e['title']) for e in ev]
assert len(ids)==len(set(ids)) and len(dt)==len(set(dt)) and ev==sorted(ev,key=lambda x:x['date'])
print(f'{len(ev)}건 통과')
"

# feeds.txt 파싱 확인
python3 -c "
import sys; sys.path.insert(0,'scripts')
import importlib.util
spec=importlib.util.spec_from_file_location('cf','scripts/collect_feeds.py')
cf=importlib.util.module_from_spec(spec); spec.loader.exec_module(cf)
print(len(cf.load_feeds()), '개 피드 파싱됨')
"

# 워크플로 YAML 파싱
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/daily-update.yml'))"

# 대시보드 재빌드
python3 scripts/build.py
```

## 현재 데이터 상태
- `data/events.json`: 57건 시드 (E101~E157), 전부 `llm: "Claude Sonnet 5"`로 표시(수기
  큐레이션). 실제 파이프라인이 돌면 Gemini/Groq/Mistral 중 하나의 모델명이 채워짐.
- `feeds.txt`: 15개 (AI플랫폼 4 고정 + 회사 1 고정 + 트렌드소스 10, 후자만 주기적 재검토
  대상 — 재검토 시 `data/query_performance.json`의 kept 수를 참고)
- `data/wiki_series.json`, `data/gdelt_pool.json` 등은 로컬에선 비어있거나 최소 상태 —
  실제 값은 GitHub Actions에서 처음 돌 때 채워짐 (네트워크 제약 때문에 로컬에서 검증 불가)

## 하지 말아야 할 것
- `index.html`을 직접 편집 — 항상 `build.py`가 생성
- LLM 프롬프트에 unverified RSS URL 추측해서 넣기 — 항상 실제 fetch로 검증
- `events.json`에 영어 원문이나 하드코딩된 기본값(confidence=low 등)으로 채운 이벤트 저장
  — 3-LLM 다 실패하면 skip이 원칙
- 워크플로 스텝에 새 API 키 쓰는 스크립트 추가할 때 `env:` 블록에 그 키 추가하는 걸
  깜빡하기 (실제로 한 번 이런 버그가 있었음 — check_model.py가 Groq/Mistral 키를 못 받아서
  "키 없음"으로 잘못 표시된 적 있음)
