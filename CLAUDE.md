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
  llm_common.py       Gemini→Groq→Mistral 판단체인 + 공유 설정(MARKETS/queries.txt·kw_*.txt
                      파서/has_korean 등, 6개+ 스크립트가 여기서 import)
  collect_wiki.py     위키피디아 일별 조회수 (경쟁사 관심도 대리지표), 최초 730일 백필+이후 증분
  collect_imf.py      Layer 3 — IMF SDMX 월간 통계 (28일만 실행)
  collect_crux.py     공급축 — CrUX 실사용자 CWV 주간 시계열 (CRUX_API_KEY 없으면 조용히 스킵)
  optimize.py         매일 Gemini가 queries.txt/kw_news.txt/kw_feeds.txt 자동 튜닝
  check_model.py      Gemini/Groq/Mistral 3개 모델 상태 체크 (매일) → data/model_status.json
  check_feeds.py       feeds.txt의 15개 피드 파싱 상태 체크 (매일) → data/feed_health.json
  merge_past_events.py 수동 도구 — 이벤트 배치를 events.json에 병합(스키마 검증·정렬·중복제거)
  check_feed_translation.py 수동 진단 — events.json 내 피드 항목 번역 품질 점검
  build.py             모든 data/*.json → index.html 재빌드 (대시보드 JS 전부 여기 있음)

data/                 자동 생성/갱신되는 JSON들 (스키마는 각 스크립트 상단 docstring 참고)
feeds.txt             1차 소스 RSS 목록 (18개: AI플랫폼4 + 검색플랫폼(Google)2 + 회사2 + 트렌드10)
queries.txt           뉴스 검색어 10개, `category | query` 형식 (samsung/galaxy/ecommerce/
                      smartphone/other 5개 카테고리, optimize.py가 매일 조정)
kw_news.txt           뉴스 사전필터 KEEP/DROP (collect_news.py 전용, optimize.py가 매일 조정)
kw_feeds.txt          피드 사전필터 KEEP/DROP (collect_feeds.py 전용, 한글 키워드 포함,
                      optimize.py가 매일 조정) — news와 별도 파일인 이유는 아래 원칙 참고
interests.txt         우선순위 토픽 (LLM 프롬프트 + 양쪽 사전필터 KEEP에 자동 반영)
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
사전필터를 통과 못 하면 LLM 호출 자체를 안 함. 사전필터는 news/feeds가 **별도 파일**
(`kw_news.txt`/`kw_feeds.txt`)을 쓴다 — 같은 파일로 합치지 않는 이유는 언어가 다르기
때문(뉴스는 NewsAPI/GDELT 둘 다 영어만 요청하지만, feeds는 Samsung KR 피드처럼 한글
콘텐츠가 섞여 있어 한글 키워드가 필요함). `interests.txt`(우선순위 토픽)는 이 둘 모두의
KEEP 리스트에 로드 시점에 자동으로 합쳐짐. 둘 다 `optimize.py`가 매일 자동 튜닝.

두 콜렉터의 변수명도 동일(`KW_KEEP`/`KW_DROP`) — 예전엔 collect_feeds.py만 `KEYWORDS`/
`NEGATIVE`라는 다른 이름을 썼는데 2026-07-08 통일함. `queries.txt`/`kw_*.txt` 파싱,
`MARKETS`(12개국 리스트), `has_korean()` 같은 조각들은 전부 `llm_common.py`에만 정의돼
있고 나머지 스크립트(collect_news/collect_gdelt/collect_feeds/optimize/check_model/
merge_past_events/check_feed_translation)는 거기서 import — 예전엔 3~4곳에 따로
복붙돼 있어서 한 곳만 고치고 나머지를 깜빡하는 사고(Samsung KR 피드 사전필터 버그가
정확히 이런 식으로 생겼었음)가 났었음. **새 설정 상수나 파일 파서를 또 추가해야 하면
`llm_common.py`에 먼저 넣고 각 스크립트는 import만 하는 걸 기본으로 할 것.**

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

### 5. 키워드 필터에서 거르지 않는 것 (2026-07 변경, 2026-07-08 정정)
스포츠와 계절성/일반론 콘텐츠를 더 이상 자동으로 거르지 않음 — IDC/TrendForce/Gartner/
Pew Research 같은 정기 트렌드 리서치 소스를 새로 추가하면서, 이들의 콘텐츠(점진적 트렌드
분석)가 옛 규칙("특정 날짜있는 사건만") 때문에 계속 걸러지는 문제를 발견해서 완화함.
(정정: 이 정책이 FILTER_SYSTEM 프롬프트에는 반영됐지만 `KW_DROP`에는 football/cricket/
soccer/sport event가 그대로 남아있던 실제 불일치가 2026-07-08 발견돼 `kw_news.txt`에서
제거함 — 문서화된 정책과 실제 동작이 몇 주간 어긋나 있었다는 뜻이니, 이 항목을 다시 건드릴
땐 코드도 같이 확인할 것.)

### 5-1. 전망·예측·루머성 콘텐츠는 거름 (2026-07-08 신설)
"이 전망/유출 정보 때문에 트래픽이 미리 반영됐다"는 식의 해석은 인과관계가 너무 약해서
제외하기로 함. `FILTER_SYSTEM`(llm_common.py)에 명시적 REJECT 규칙 추가: 미래 예측/전망
수치("~년까지 X% 성장 전망"), 미확정 제품 루머/유출(가격 유출, 출시일 유출, "소식통에
따르면") 전부 거름. **단, 삼성이 직접 공식 발표한 미래 확정 사실**(예: "삼성이 7월 22일
출시를 공식 발표")은 루머가 아니라 실제 확정된 기업 행위이므로 계속 KEEP — 이건 5번
원칙의 "정기 트렌드 리서치 소스" 포함 정책과 상충하는 게 아니라, 그 정책이 다루는 "이미
실측된 데이터" 콘텐츠와 "미래 전망 수치" 콘텐츠를 구분하는 것. IDC/TrendForce/Gartner/
Pew Research 피드 자체는 과거 실측 통계도 발행하므로 feeds.txt에서 제거하지 않고, LLM
판단 단계에서 개별 기사 단위로 걸러지도록 함 (전망 위주 기사가 많아 이 소스들의 LLM
keep율은 낮아질 수 있음 — `data/query_performance.json`으로 news 쪽은 추적 가능하나
feeds 쪽은 개별 소스 단위 추적 지표가 없어 육안 확인 필요).
2026-07-08 소급 정리: 기존 events.json에서 전망/유출성 이벤트 10건(AI 칩 시장 전망,
갤럭시 폴드8 가격/출시일 유출, IMF 성장 전망, 스마트폰 출하 전망 등) 제거, 104건→94건.

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

## 현재 데이터 상태 (2026-07-08 기준 실측)
- `data/events.json`: 총 104건 (중복 3건 제거 후). 시드 57건(E101~E157, 전부
  `llm: "Claude Sonnet 5"`로 표시된 수기 큐레이션)에 더해, GitHub Actions 파이프라인이
  실제로 여러 번 돌면서 자동 수집된 47건(`FP...`/`A...` 형식 event_id, `llm` 값은
  `gemini-2.5-flash`/`mistral-small-latest` 등 실제 판단에 쓰인 모델명)이 이미 누적됨.
  Mistral이 `impact` 필드에서만 "IN KOREAN" 지시를 어긴 과거 15건은 재번역 완료, 재발
  방지 가드(`llm_common.py`의 `_korean_fields_ok`)도 추가됨.
- `feeds.txt`: 18개 (AI플랫폼 4 고정 + 검색플랫폼(Google) 2 고정 + 회사 2 고정 + 트렌드소스
  10, 트렌드소스만 주기적 재검토 대상 — 재검토 시 `data/query_performance.json`의 kept 수를
  참고). 검색플랫폼 2개(Search Status Dashboard Atom, Search Central Blog FeedBurner)와
  Samsung newsroom KR은 2026-07-08 소유자가 브라우저로 직접 XML 로드를 확인해 검증함.
  Samsung KR 피드는 한국어 콘텐츠라 `kw_feeds.txt` KEEP에 한글 키워드(삼성/갤럭시/
  비스포크)가 들어있음 — 이 키워드들을 지우면 KR 피드 항목이 사전필터에서 전멸하니 주의.
- 사전필터/검색어 구조가 2026-07-08 대대적으로 개편됨: `data/kw_filters.json`(뉴스 전용,
  JSON) 삭제, `kw_news.txt`+`kw_feeds.txt`(콜렉터별 분리, txt) 신설. `queries.txt`는
  `category | query` 형식으로 바뀌어 samsung/galaxy/ecommerce/smartphone/other 5개
  카테고리를 명시적으로 태그함 — `optimize.py`는 이제 카테고리별 최대 1개 교체, 브랜드
  카테고리(samsung/galaxy/ecommerce/smartphone)는 각자 카테고리명을 포함한 쿼리를 최소
  1개 항상 유지하도록 강제함(자세한 내용은 `optimize.py`의 `apply_query_constraints()`
  docstring 참고).
- `data/wiki_series.json`(dict, 3개 시리즈), `data/gdelt_pool.json`(list, 33건),
  `data/feed_state.json`(dict, 13개), `data/imf_series.json`(dict, 4개) 등은 더 이상
  비어있지 않음 — GitHub Actions가 이미 여러 차례 돌면서 채워진 상태. 로컬 클론 직후에는
  git에 커밋된 최신 스냅샷이 그대로 보이므로, "비어있다"고 가정하지 말고 실제 파일을
  확인할 것.

## 하지 말아야 할 것
- `index.html`을 직접 편집 — 항상 `build.py`가 생성
- LLM 프롬프트에 unverified RSS URL 추측해서 넣기 — 항상 실제 fetch로 검증
- `events.json`에 영어 원문이나 하드코딩된 기본값(confidence=low 등)으로 채운 이벤트 저장
  — 3-LLM 다 실패하면 skip이 원칙
- 워크플로 스텝에 새 API 키 쓰는 스크립트 추가할 때 `env:` 블록에 그 키 추가하는 걸
  깜빡하기 (실제로 한 번 이런 버그가 있었음 — check_model.py가 Groq/Mistral 키를 못 받아서
  "키 없음"으로 잘못 표시된 적 있음)
