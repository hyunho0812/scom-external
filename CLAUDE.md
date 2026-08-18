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
                      + 근접 중복 억제 DupIndex/title_sim (아래 원칙 9)
  collect_wiki.py     위키피디아 일별 조회수 (경쟁사 관심도 대리지표), 최초 730일 백필+이후 증분
  collect_imf.py      Layer 3 — IMF SDMX 월간 통계 (28일만 실행)
  collect_crux.py     공급축 — CrUX 실사용자 CWV 주간 시계열 (CRUX_API_KEY 없으면 조용히 스킵)
  optimize.py         매일 Gemini가 queries.txt/kw_news.txt/kw_feeds.txt 자동 튜닝
  check_model.py      Gemini/Groq/Mistral 3개 모델 상태 체크 (매일) → data/model_status.json
                      ※ 메타데이터 GET일 뿐 생성을 안 해봄 — 아래 llm_usage.json 참고
  check_feeds.py       feeds.txt의 20개 피드 파싱 상태 체크 (매일) → data/feed_health.json
  merge_past_events.py 수동 도구 — 이벤트 배치를 events.json에 병합(스키마 검증·정렬·중복제거)
  check_feed_translation.py 수동 진단 — events.json 내 피드 항목 번역 품질 점검
  score_predictions.py 신뢰도 계층 (매일) — 이벤트 원장을 반증 가능하게 만듦.
                      ① 이벤트 압력지수(일별 시계열화) → data/event_pressure.json
                      ② 사후 채점·교정곡선·순열검정·축 검증 → data/prediction_scores.json
                      API 키 불필요 (events.json + wiki_series.json만 읽음)
  check_llm_agreement.py 주간(월) — 같은 기사를 3개 provider에 독립 판정시켜 라벨
                      일치도 측정 → data/llm_agreement.json. 라벨 신뢰도의 상한
  repair_event_dates.py 1회용 복구 — 2026-08-10 날짜 버그로 어긋난 date 교정
                      (아래 "날짜 앵커링 사고" 참고). --dry-run 기본, --apply로 저장
  build.py             모든 data/*.json → index.html 재빌드 (대시보드 JS 전부 여기 있음)

data/                 자동 생성/갱신되는 JSON들 (스키마는 각 스크립트 상단 docstring 참고)
  prediction_scores.json (2026-08-10 신설) 방향 적중률·강도별 교정곡선·압력지수 상관·
                      순열검정 p값·축 검증. 대시보드 "예측 검증" 패널이 이걸 읽음.
                      **재계산하지 않고 읽기만 함** — 화면과 저장된 근거가 어긋날 수 없게.
  event_pressure.json (2026-08-10 신설) 축별 일별 이벤트 압력 시계열
  llm_agreement.json  (2026-08-10 신설) provider 간 라벨 일치도, 최근 12회 보존
  llm_usage.json      (2026-08-05 신설) 콜렉터 실행별 provider 텔레메트리 —
                      attempt/ok/ko_reject/empty/http_429/http_auth/http_other/
                      exception/skipped_off. `llm_common.save_usage()`가
                      `diag_summary(label)` 끝에서 기록, 30일 보존.
                      **폴백은 항목당 비용이 아니라 런당 비용** — 429 한 번이면
                      off 플래그가 켜져 그 런의 나머지는 요청 없이 스킵되므로,
                      실제 요청 수는 `attempt` 합계(=`total_attempts`)로 볼 것.
feeds.txt             1차 소스 RSS 목록 (15개: AI플랫폼4 + 검색플랫폼(Google)2 + 회사2 + 트렌드7)
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

**판단은 1건씩이 아니라 `LLM_BATCH`(기본 5)건씩 묶어서 한 요청으로 보낸다**
(`llm_filter_batch()`). `FILTER_SYSTEM`이 ~1.1k 토큰이라 예전엔 입력 토큰의 **93%가
기사마다 재전송되는 동일 지시문**이었음 — 배치가 이걸 N건이 분담한다. 토큰보다 중요한 건
**요청 수**가 같은 배수로 줄어든다는 점(무료 티어가 실제로 배급하는 자원이고, Mistral의
분당 2회 제한은 요청당 31초 sleep으로 런타임에 직결됨 — 39건 기준 20분→4분).
배치가 개수를 안 맞춰 오거나(`batch_shape_fail`), 특정 항목이 한국어 가드에 걸리면
**그 항목만 개별 재판정**으로 떨어진다 — 최악의 경우가 기존 개별 처리 동작이라 품질이
나빠질 수 없는 구조. `llm_usage.json`의 `batch_shape_fail`이 오르면 `LLM_BATCH`를 낮출 것.

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

- Gemini: `GEMINI_API_KEY`, `GEMINI_MODEL` (기본 `gemini-2.5-flash`).
  `thinkingConfig.thinkingBudget=0`으로 사고 토큰을 끄고 호출함 — 안 그러면 사고 토큰이
  `maxOutputTokens`를 다 먹고 본문이 비어 나옴.
- Groq: `GROQ_API_KEY`, `GROQ_MODEL` (기본 `openai/gpt-oss-120b` — llama-3.3-70b-versatile은
  2026-06-17 폐기공지 받아서 교체함), `GROQ_MAX_TOKENS`(기본 1500),
  `GROQ_REASONING_EFFORT`(기본 `low`, 빈 문자열이면 기능 끔).
  **gpt-oss는 추론(reasoning) 모델이라 Gemini와 똑같은 함정이 있음** — 추론 토큰이
  `max_tokens`에 포함돼서 공용 600 상한으로는 `content`가 빈 채로 돌아오고, 체인이 조용히
  Mistral로 떨어짐. 2026-07-06 Groq 도입 이후 **kept 이벤트 0건**이 정확히 이 증상이었고
  2026-08-05에 `reasoning_effort`+상향된 max_tokens로 대응함. Groq 전용 필드라 400이 나면
  `_groq_no_extra`가 래치되어 그 런에서는 필드를 빼고 재시도함(도입 전보다 나빠질 수 없음).
- Mistral: `MISTRAL_API_KEY`, `MISTRAL_MODEL` (기본 `mistral-small-latest`, 무료
  Experiment 티어라 분당 2회 제한 — 3순위라 괜찮음)

**`check_model.py`의 "ok"를 작동 증거로 믿지 말 것.** 이건 모델 메타데이터 GET이라
생성을 안 해봄 — 위 Groq 증상은 한 달 내내 `model_status.json`에 `ok`로 찍혀 있었음.
실제 작동 여부는 `data/llm_usage.json`의 `ok`/`empty`/`ko_reject`로 판단할 것.

### 2. "검증된 공식 소스만" 원칙
feeds.txt에 넣는 모든 RSS는 **반드시 실제로 fetch해서 검증** 후에만 추가. 3rd파티
스크래퍼/미러(예전에 Anthropic·Perplexity가 이랬음)는 정책상 제외 — 관리자가 손 놓으면
조용히 멈추는 리스크 때문. 회사 뉴스룸이 JS 렌더링 페이지라 RSS가 없으면 억지로 추측
URL을 넣지 말고, feeds.txt에 "확인했지만 없음" 주석으로 남길 것.

### 3. 이벤트 스키마의 "confidence"와 "impact_strength" 정의
- `confidence`: 이 판단(impact_direction/strength)이 맞다는 **확신도** (high/med/low).
  기사 정확도나 트렌드 일관성이 아님. FILTER_SYSTEM 프롬프트에 명시돼 있음.
- `impact_strength`: samsung.com **웹 트래픽**에 대한 영향 크기(1~5). revenue 아님.
- `axis`: 대시보드 3축 진단 패널(수요/점유/공급)이 이 이벤트를 어느 축에 배정할지 —
  `demand|share|supply` 중 하나, LLM이 판단 시점에 직접 분류(FILTER_SYSTEM, 2026-07-14
  추가). demand=시장 전체에 고르게 영향(특정 경쟁사 대상 아님), share=삼성 vs **특정
  경쟁사** 간 재분배, supply=samsung.com 자체 사이트 이슈. 값이 비어있으면(이 필드
  추가 이전 수집분) `build.py`의 `axisOf()`가 카테고리/키워드 휴리스틱으로 대체 추정함
  — 즉 값이 있으면 LLM 판단을 신뢰하고, 없으면만 휴리스틱으로 폴백.

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
실측된 데이터" 콘텐츠와 "미래 전망 수치" 콘텐츠를 구분하는 것. IDC/TrendForce/Pew
Research 같은 정기 리서치 피드 자체는 과거 실측 통계도 발행하므로 (전망 콘텐츠라는
이유로는) feeds.txt에서 제거하지 않고, LLM 판단 단계에서 개별 기사 단위로 걸러지도록 함
(전망 위주 기사가 많아 이 소스들의 LLM keep율은 낮아질 수 있음 — `data/feed_performance.json`
으로 소스별 kw_pass_rate/keep_rate 추적 가능해짐, 2026-07-14 추가. `optimize.py`가 이걸
`kw_feeds.txt` 튜닝 프롬프트에 넣어줌 — keep_rate가 낮은 소스는 "주제는 맞는데 전망
위주라 계속 걸러짐"으로 해석). *Gartner Newsroom은 이 정책과 무관하게 지속적인 HTTP 403
때문에 2026-07-14 feeds.txt에서 별도로 제거됨 — feeds.txt의 "Removed" 주석 참고.*
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
- `feeds.txt`: 20개 (AI플랫폼 4 고정 + 검색플랫폼(Google) 2 고정 + 회사 2 고정 + 트렌드소스
  12, 트렌드소스만 주기적 재검토 대상 — 재검토 시 `data/feed_performance.json`의
  kw_pass_rate/keep_rate를 참고). 검색플랫폼 2개(Search Status Dashboard Atom, Search
  Central Blog FeedBurner)와 Samsung newsroom KR은 2026-07-08 소유자가 브라우저로 직접
  XML 로드를 확인해 검증함. Samsung KR 피드는 한국어 콘텐츠라 `kw_feeds.txt` KEEP에
  한글 키워드(삼성/갤럭시/비스포크)가 들어있음 — 이 키워드들을 지우면 KR 피드 항목이
  사전필터에서 전멸하니 주의. 트렌드소스 중 Gartner Newsroom(HTTP 403 지속),
  TrendForce Consumer Electronics(0건 지속), Search Engine Land(HTTP 403 지속) 3개는
  `data/feed_health.json`에서 여러 날 연속 문제로 확인돼 2026-07-14 제거함 (10→7).
  **2026-08-04: "벤더/개인 블로그 제외" 룰 폐지** (7→12). 발행 주체의 형식은 개별 기사가
  사전필터·LLM 판단체인을 통과하는지와 무관하고, 소스별 실효성은 `feed_performance.json`이
  훨씬 정확히 측정하기 때문. 그때 빠졌던 Semrush/Ahrefs/Moz/HubSpot Marketing/Neil Patel
  5개 복구 — 활동 당시 `data/feed_state.json` 9일치(06-29~07-06) 전 회차에서 각각
  20/10/10/50/10건을 안정적으로 반환한 게 검증 근거(세션 egress 차단으로 실시간 재fetch는
  불가, 다음 `check_feeds.py` 일간 실행이 재확인). **이제 소스를 배제하는 사유는 딱 둘,
  둘 다 관찰 가능한 사실이며 편집 판단이 아님**: (1) 에러/0건, (2) 미러(퍼블리셔 자체 피드가
  아님). 같이 빠졌던 Shopify Blog는 복구 대상이 아님 — 같은 9회차 전부 0건이라 (1)에 해당
  (TrendForce Consumer Electronics와 동일 패턴). Anthropic/Perplexity도 (2)라 계속 제외.
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

### 7. 날짜 앵커링 사고 (2026-08-10) — 새 LLM 필드를 믿기 전에 읽을 것
`FILTER_SYSTEM`에 **오늘 날짜가 없었고**, 콜렉터는 LLM이 준 날짜를 정규식
`^\d{4}-\d{2}-\d{2}$` 하나로만 검사했다. 시계가 없는 모델은 추출 날짜를 **학습
데이터 시기(2024년)에 앵커링**했고, 그 결과 자동수집 325건 중 **291건(90%)이 수집일보다
1년 이상 과거**로 저장됐다 — 2026-08-04에 가져온 Galaxy Z Fold 8 기사가 2024-08-22로,
Apple Watch Series 11이 2024-09-01로. 정규식은 `2024-05-00`(00일)도 통과시켜 5건이
파싱 불가 상태로 들어와 있었다.

**대시보드의 기간 필터·추세 차트·3축 배분이 전부 `date`에 걸려 있어서, 두 해쯤 어긋난
데이터를 분석하고 있었다.** 증상은 "특정 기간을 골라도 이벤트가 몇 건 안 잡힌다"였는데
한동안 원인으로 연결되지 않았다.

대응 3종:
- `_today_note()`가 프롬프트에 오늘 날짜를 주입 (단건·배치 양쪽)
- `_item_block()`이 소스 발행일을 `PUBLISHED:`로 같이 전달
- `clean_date()`가 **엄격 파싱 + 미래 거부 + 과도한 소급(기본 180일 초과) 거부**,
  실패 시 소스 발행일로 폴백. `collect_feeds.py`는 `feed_date()`로 RSS `pubDate` /
  Atom `updated`를 파싱 — 예전엔 발행일을 버리고 무조건 "오늘"로 채우고 있었다.
- 원본 발행일은 `raw_date`에 보존 → 다음에 또 어긋나도 복구 가능

**교훈: LLM이 채우는 새 필드를 스키마 검사만으로 받아들이지 말 것.** 그 값이 물리적으로
가능한 범위인지(미래 아님, 파이프라인 특성상 가능한 과거 범위 안) 함께 검사하고, 가능하면
독립적인 근거(발행일)를 폴백으로 둘 것. `date_source` 필드가 이제 그 근거를 기록한다
(`url`=URL에서 추출한 발행일, `llm`=모델 값 채택, `capture`=수집일로 추정, `seed`=수기).

### 8. 정성 → 정량의 다리 (2026-08-10 신설)
예전 대시보드는 **산술 분해로 나온 축 퍼센트**와 **LLM이 분류한 이벤트 목록**을 나란히
놓기만 했다. 둘은 서로를 제약하지 않아서, 읽는 사람이 머릿속에서 연결할 뿐 **틀릴 수 없는
= 증명도 아닌** 구조였다. `score_predictions.py`가 그 다리를 놓는다:
- **압력지수**: 이산 이벤트를 `strength × confidence × 0.5^(경과/반감기)`로 일별
  시계열화. horizon별 반감기 immediate 3일 / weeks 14일 / months 60일.
  자료형이 같아져야 트래픽과 비교가 된다 — 나머지 전부의 전제.
- **사후 채점**: 저장된 `impact_direction/strength/horizon`은 그 자체로 예측이다.
  horizon 경과 후 실측과 대조해 적중률·강도별 교정곡선을 만든다.
- **순열검정**: 이벤트 날짜만 무작위로 섞어 귀무분포를 만든다. 일별 관측은 자기상관이
  강해 일반 t검정은 과신하므로 **순열 p값이 유일하게 믿을 기준**.
- **축 검증**: demand 압력이 실제로 market_total을, share가 samsung_share를
  예측하는지. 안 되면 축 라벨은 장식이다.
- **계절성 기준선**(build.py `seasonalBaseline()`): 같은 비교를 과거로 반복 재생해
  중앙값=예상분, MAD=변동폭. 관측 변화를 "예상되던 몫 + 설명이 필요한 몫"으로 쪼개고
  z로 이례성을 표시. 예전엔 어차피 일어났을 변화까지 뉴스 탓으로 돌리고 있었다.

**2026-08-10 첫 측정 결과: 전부 유의하지 않음** (적중률 53%, 압력-트래픽 r=0.14,
순열 p=0.998, 축 검증 p=0.08~0.35). 조밀 구간이 39일뿐이라 검정력이 거의 없다 —
귀무 |r| 95%가 0.69다. **고장이 아니라 "아직 결론 낼 수 없다"를 정확히 말하고 있는
것이고, 이 계측을 지금 시작해야 몇 달 뒤에 쓸 수 있다.**

### 9. 근접 중복 억제 (2026-08-18 신설)
소스가 12개 피드 + NewsAPI + GDELT라 **같은 사건이 여러 번 쌓인다**. 기존 중복 검사는
event_id(=md5(제목) / md5(라벨+제목))와 (제목,날짜) 쌍뿐이라 소스마다 헤드라인이 다르면
전혀 못 걸렀다. 규칙: **`DEDUP_WINDOW_DAYS`(기본 7일) 안에 비슷한 내용이 이미 있으면
첫 번째 소스만 남기고 이후는 저장하지 않는다.**

`llm_common.DupIndex`가 판정하고 두 콜렉터가 공유한다. 비교는 **문자 3-gram과 단어 집합
Jaccard 중 큰 값** — 한국어는 조사가 붙어 공백 토큰이 불안정해 n-gram이, 영어는 어순에
강한 단어 집합이 각각 유리해서 둘 다 본다. **검사 지점이 둘인 이유가 핵심이다**(454건
실측으로 임계값을 잡음):

| 단계 | 비교 대상 | 임계값 | 왜 |
|---|---|---|---|
| LLM 호출 **전** | 소스 원문 헤드라인 `raw_title` + URL | `DEDUP_RAW_SIM` 0.50 | 진짜 교차소스 중복은 0.47 이상, 무관한 다음 쌍이 0.43 — 사이가 비어 있음. 여기서 걸리면 **LLM 요청을 아예 안 쓴다** |
| LLM 판단 **후** | LLM이 쓴 한글 `title` | `DEDUP_KO_SIM` 0.70 | 삼성 KR 뉴스룸(한글)과 같은 사건의 영문 기사는 영문 유사도가 **0.00**이라 이쪽으로만 잡힌다. 대신 모델이 상투적 제목을 써서 무관한 사건이 충돌함("갤럭시 A57 최저가 할인" vs "갤럭시 S26 최저가 할인" = 0.60)이라 문턱이 훨씬 높다 |

URL은 정규화(스킴·www·쿼리·프래그먼트 제거) 후 완전일치면 창과 무관하게 중복 —
같은 페이지가 utm 파라미터만 바꿔 다시 오는 경우다.

**임계값은 일부러 보수적이다. 중복을 놓치면 행 하나가 늘 뿐이지만, 잘못 매칭하면 진짜
이벤트가 영구히 사라진다.** 전체 이력 재생 결과 454건 중 18건(4.0%)이 걸렀고 — url 10 /
raw_title 4 / title 4 — 그중 가장 논쟁적인 건 "폴드8 울트라 인도 출시"와 "호주 출시"가
같은 출시 스토리로 묶인 것(raw 0.59). 시장별로 따로 보고 싶으면 `DEDUP_RAW_SIM`을 0.6으로
올릴 것. 전부 환경변수로 조정 가능하다.

한 런 안에서 뒤늦게 들어온 중복은 **판단은 받되 저장 직전에** 걸린다(사전 단계에선 아직
색인에 없으므로). LLM 요청 1건을 더 쓰지만, 아직 판정도 안 된 후보를 색인에 미리 넣으면
"먼저 온 쪽이 irrelevant로 탈락했는데 그 사본까지 같이 죽는" 경우가 생겨서 그렇게 두었다.

억제량은 `data/query_performance.json`·`data/feed_performance.json`의 `dup_near`에
기록되고, `optimize.py`가 쿼리별 `near_dup_rate`로 프롬프트에 넣는다 — "이 검색어는 다른
소스가 이미 보도한 것만 가져온다"는 신호라 near-synonym 쿼리를 정리하는 근거가 된다.

## 하지 말아야 할 것
- `index.html`을 직접 편집 — 항상 `build.py`가 생성
- LLM 프롬프트에 unverified RSS URL 추측해서 넣기 — 항상 실제 fetch로 검증
- `events.json`에 영어 원문이나 하드코딩된 기본값(confidence=low 등)으로 채운 이벤트 저장
  — 3-LLM 다 실패하면 skip이 원칙
- 대시보드에서 `prediction_scores.json`의 수치를 **다시 계산**하기 — 읽기만 할 것
  (화면과 저장된 근거가 어긋나면 신뢰도 패널의 존재 이유가 사라짐)
- 워크플로 스텝에 새 API 키 쓰는 스크립트 추가할 때 `env:` 블록에 그 키 추가하는 걸
  깜빡하기 (실제로 한 번 이런 버그가 있었음 — check_model.py가 Groq/Mistral 키를 못 받아서
  "키 없음"으로 잘못 표시된 적 있음)
