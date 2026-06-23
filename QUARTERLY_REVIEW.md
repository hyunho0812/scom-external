<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>S.com External Factors</title>
<style>
:root{--blue:#1428A0;--blue-d:#0d1b6e;--ink:#202124;--muted:#6b7280;--line:#e8eaed;--bg:#f4f6f9;--card:#fff;--neg:#D0392B;--pos:#137a52;--neu:#9aa0a6;--accent:#1428A0}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Samsung Sharp Sans','SamsungOne',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Malgun Gothic',Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.55;padding:0;margin:0}
.wrap{max-width:1120px;margin:0 auto;padding:24px}
.brandbar{background:linear-gradient(100deg,var(--blue) 0%,var(--blue-d) 100%);color:#fff;padding:22px 28px;border-radius:16px;margin:20px 20px 0}
.brandbar h1{font-size:21px;font-weight:600;letter-spacing:-0.01em;color:#fff;margin:0}
.brandbar .sub{font-size:12.5px;color:rgba(255,255,255,0.82);margin-top:3px}
h1{font-size:20px;font-weight:600;color:var(--blue)}
.sub{font-size:13px;color:var(--muted)}
.mbadge{display:inline-flex;align-items:center;gap:7px;font-size:12px;padding:5px 11px;border-radius:20px;margin-bottom:18px;border:1px solid var(--line);background:#fff}
.mbadge .dot{width:8px;height:8px;border-radius:50%}
.mbadge.ok{background:#eaf6f0;border-color:#c2e6d4;color:#137a52}.mbadge.ok .dot{background:#137a52}
.mbadge.retired{background:#fbeae8;border-color:#f3c4bd;color:#a3271f}.mbadge.retired .dot{background:#D0392B}
.mbadge.unknown,.mbadge.error{background:#fef6e0;border-color:#f0e2b8;color:#8a6d1a}
.mbadge.unknown .dot,.mbadge.error .dot{background:#EF9F27}
.controls{display:block;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px;box-shadow:0 1px 2px rgba(20,40,160,0.04)}
.filterrow{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-bottom:16px}
.periodrow{display:flex;gap:14px;flex-wrap:wrap;align-items:stretch}
.pgroup{flex:1;min-width:300px;border-radius:12px;padding:14px 16px}
.pgroup.cmp{background:#f7f8fb;border:1px solid #dfe3ea}
.pgroup.cur{background:#eef1fb;border:1.5px solid #c5cef5}
.pglabel{display:flex;align-items:center;gap:7px;margin-bottom:10px;font-size:12px;font-weight:600}
.pgroup.cmp .pglabel{color:#5f6368}.pgroup.cur .pglabel{color:var(--blue)}
.pgdot{width:10px;height:10px;border-radius:3px}
.pgroup.cmp .pgdot{background:#9aa0a6}.pgroup.cur .pgdot{background:var(--blue)}
.pgfields{display:flex;gap:10px;flex-wrap:wrap}
.pgroup.cur input[type=date]{border-color:#c5cef5}
.parrow{display:flex;align-items:center;color:#bdc1c6;font-size:20px;padding:0 2px}
.ctrlbar{display:flex;justify-content:flex-end;margin-bottom:10px}
#csvbtn{padding:9px 18px;border:none;border-radius:9px;background:var(--blue);color:#fff;font-size:13px;font-weight:600;cursor:pointer;height:38px}
#csvbtn:hover{background:var(--blue-d)}
.ctrl{display:flex;flex-direction:column;gap:5px;min-width:120px}.ctrl label{font-size:11px;color:var(--muted);font-weight:500;white-space:nowrap}
.ctrl input[type=date]{width:150px}
.rowbreak{flex-basis:100%;height:0}
select,input[type=date]{width:120px;padding:8px 12px;border:1px solid var(--line);border-radius:9px;font-size:14px;background:#fff;cursor:pointer;height:38px;color:var(--ink)}
select:focus,input[type=date]:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px rgba(20,40,160,0.10)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:18px;box-shadow:0 1px 2px rgba(20,40,160,0.04)}
.phead{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:6px}
.ptitle{font-size:13px;font-weight:600}
.legend{display:flex;gap:14px;font-size:11px;color:var(--muted);flex-wrap:wrap}
.note{font-size:11px;color:#9aa0a6;margin-top:8px}
.evmap{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem;box-shadow:0 1px 2px rgba(20,40,160,0.04)}
.card .lbl{font-size:12px;color:var(--muted);margin-bottom:6px}.card .val{font-size:24px;font-weight:600}
.srcline{position:absolute;right:16px;bottom:12px;font-size:11px;color:#9aa0a6;max-width:45%;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.funnel{font-size:11px;color:var(--muted);margin-bottom:16px}
.evt{position:relative;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--neu);border-radius:12px;padding:15px 17px 30px;margin-bottom:12px;box-shadow:0 1px 2px rgba(20,40,160,0.04)}
.evt.pos{border-left-color:var(--pos)}.evt.neg{border-left-color:var(--neg)}
.evt .top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:5px}
.evt .ttl{font-size:15px;font-weight:500;display:flex;align-items:center;gap:9px}
.numbadge{flex:none;width:22px;height:22px;border-radius:50%;color:#fff;font-size:12px;font-weight:bold;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 1px 3px rgba(0,0,0,0.2)}
#trend{cursor:pointer}
.evt.flash{animation:flash 1.6s ease}
@keyframes flash{0%{box-shadow:0 0 0 0 rgba(20,40,160,0.0)}20%{box-shadow:0 0 0 3px rgba(20,40,160,0.35)}100%{box-shadow:0 0 0 0 rgba(20,40,160,0.0)}}
.evt .indent{margin-left:31px}
.evt .meta{font-size:12px;color:var(--muted)}
.evt .imp{font-size:13px;font-weight:500;border-radius:8px;padding:8px 10px;margin:6px 0 8px;line-height:1.5}
.evt .desc{font-size:13px;color:#444;line-height:1.65}
.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;background:#eef0f5;color:#444;margin-right:5px}
.kline{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px}.klbl{font-size:11px;color:var(--muted)}
.metaval{font-size:12px;color:var(--ink)}
.ktag{display:inline-block;font-size:11px;padding:2px 9px;border-radius:10px;margin-right:5px;font-weight:500}
.empty{padding:30px;text-align:center;color:var(--muted)}
.foot{font-size:12px;color:#8a6d1a;margin-top:16px;padding:12px;background:#fff8e8;border:1px solid #f0e2b8;border-radius:10px}
</style></head><body>
<div class="brandbar"><h1>S.com External Factors</h1>
  <div class="sub">samsung.com 외부 요인 트래커 · 매일 자동 갱신 · 마지막 빌드 2026-06-23 06:15 UTC</div></div>
<div class="wrap">
<div class="mbadge unknown" title="Run check_model.py once to populate."><span class="dot"></span>
  <span>필터 모델: <strong>gemini-2.5-flash</strong> — 키 없음 (키워드 필터만) · 점검 pending</span></div>
<div class="ctrlbar">
  <button id="csvbtn">CSV 내보내기</button>
</div>
<div class="controls">
 <div class="filterrow">
  <div class="ctrl"><label>지역</label><select id="region"></select></div>
  <div class="ctrl"><label>국가</label><select id="country"></select></div>
  <div class="ctrl"><label>사업부</label><select id="div">
    <option value="ALL">전체</option><option value="MX">MX</option><option value="VD">VD</option><option value="DA">DA</option></select></div>
  <div class="ctrl"><label>KPI</label><select id="kpi">
    <option value="ALL">전체</option><option>Impression</option><option>Click</option><option selected>Traffic</option><option>Order</option><option>CVR</option><option>Revenue</option><option>AOV</option></select></div>
 </div>
 <div class="periodrow">
  <div class="pgroup cmp">
   <div class="pglabel"><span class="pgdot"></span>비교 기간</div>
   <div class="pgfields">
    <div class="ctrl"><label>시작일</label><input type="date" id="csd" value="2026-06-09"></div>
    <div class="ctrl"><label>종료일</label><input type="date" id="ced" value="2026-06-15"></div>
   </div>
  </div>
  <div class="parrow">→</div>
  <div class="pgroup cur">
   <div class="pglabel"><span class="pgdot"></span>현재 기간</div>
   <div class="pgfields">
    <div class="ctrl"><label>시작일</label><input type="date" id="sd" value="2026-06-16"></div>
    <div class="ctrl"><label>종료일</label><input type="date" id="ed" value="2026-06-22"></div>
   </div>
  </div>
 </div>
</div>

<div class="panel">
  <div class="phead"><div class="ptitle">위키피디아 조회수 추세 <span id="tsub" style="font-size:11px;color:#999;font-weight:400"></span></div>
    <div class="legend" id="legend"></div></div>
  <div style="position:relative;height:250px"><canvas id="trend"></canvas></div>
  <div class="note">번호 핀 = 외부 요인 발생 시점 · 아래 요인 카드의 번호와 연결 · 위키피디아 일별 조회수(외부 추정 신호, 기업 실측 트래픽 아님)</div>
</div>

<div id="verdict" style="display:none;border-radius:12px;padding:14px 16px;margin-bottom:16px;font-size:14px"></div>

<div class="cards" id="cards"></div>
<div class="funnel">KPI 퍼널: 노출(Impression) → 클릭(Click) → 트래픽(Traffic) → 주문(Order) · 전환율(CVR) → 매출(Revenue) · 객단가(AOV)</div>
<div id="list"></div>
<div class="foot">이벤트는 samsung.com 관련성 기준으로 자동 수집·필터링됩니다.</div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/chartjs-plugin-annotation/3.0.1/chartjs-plugin-annotation.min.js"></script>
<script>
const EV=[{"event_id": "E001", "date": "2026-04-23", "captured_date": "2026-06-22", "scope": "US;GB;DE;FR;ES;PT;BR;MX_C;AU;IN;TR;KR", "divisions": "MX;VD", "kpi": "Impression;Click;Traffic", "category": "AI", "title": "OpenAI GPT-5.5 출시, ChatGPT 인용 패턴 변동", "description": "ChatGPT가 모델을 새로 바꿀 때마다 답변에서 어떤 브랜드·사이트를 인용할지가 달라집니다. samsung.com 페이지가 예전만큼 인용되지 않으면, AI를 통해 삼성을 접하고 클릭해 들어오는 경로(노출·클릭·트래픽)가 줄어듭니다.", "impact_direction": "-", "impact_horizon": "weeks", "confidence": "high", "metric": "traffic", "source": "searchenginejournal.com", "impact": "AI 답변이 삼성 페이지를 덜 인용 → AI 경유 노출·클릭·유입 감소"}, {"event_id": "E002", "date": "2026-02-09", "captured_date": "2026-06-22", "scope": "US;GB;DE;FR;ES;PT;BR;MX_C;AU;IN;TR;KR", "divisions": "MX", "kpi": "Impression;Click;Traffic", "category": "marketing", "title": "ChatGPT 광고 도입, 브랜드 인용 급락 후 회복", "description": "ChatGPT가 답변에 광고를 넣기 시작하면서 어떤 브랜드가 노출되는지가 불안정해졌습니다. AI를 통해 samsung.com으로 들어오던 길이 변동성이 커지고 링크도 줄어, 노출·클릭·유입이 출렁입니다.", "impact_direction": "-", "impact_horizon": "months", "confidence": "high", "metric": "traffic", "source": "builtin.com", "impact": "ChatGPT 광고 도입으로 AI 경유 유입이 흔들림 → 노출·클릭·트래픽 변동"}, {"event_id": "E003", "date": "2026-04-19", "captured_date": "2026-06-22", "scope": "US;DE;GB", "divisions": "MX", "kpi": "Impression;Traffic", "category": "AI", "title": "ChatGPT 실시간 웹 인용 축소, 학습 데이터 의존↑", "description": "ChatGPT가 실시간 웹을 덜 인용하고 내부 학습 지식에 더 의존하게 바뀌었습니다. 답변에 출처 링크가 줄면서, AI를 통해 삼성을 접하고 들어오는 노출·유입이 감소합니다.", "impact_direction": "-", "impact_horizon": "months", "confidence": "med", "metric": "traffic", "source": "seoclarity.net", "impact": "AI가 실시간 웹 대신 학습 데이터에 의존 → AI 경유 노출·유입 감소"}, {"event_id": "E004", "date": "2026-02-01", "captured_date": "2026-06-22", "scope": "US", "divisions": "MX;VD", "kpi": "Impression;Click;Traffic", "category": "marketing", "title": "LinkedIn, ChatGPT 인용원으로 급부상, Reddit 1위", "description": "ChatGPT가 LinkedIn·Reddit 같은 제3자 사이트를 많이 인용하게 됐습니다. 삼성 자사 페이지보다 외부 사이트가 더 자주 인용되면, 자사 경로로 들어오는 노출·클릭·유입의 구조가 바뀝니다.", "impact_direction": "neutral", "impact_horizon": "months", "confidence": "med", "metric": "traffic", "source": "nightwatch.io", "impact": "AI 인용이 제3자 사이트로 쏠림 → 자사 노출·클릭·유입 구조 변화"}, {"event_id": "E005", "date": "2026-06-08", "captured_date": "2026-06-22", "scope": "US;GB;DE;FR;ES;PT;BR;MX_C;AU;IN;TR;KR", "divisions": "MX", "kpi": "Impression;Click;Traffic;CVR", "category": "company", "title": "Apple WWDC: Siri AI 대대적 개편, 신규 파운데이션 모델", "description": "Apple이 강력한 AI Siri를 내세우면서 Galaxy AI와 정면 경쟁합니다. 프리미엄폰을 비교하던 사람들의 관심이 Apple로 쏠리면, samsung.com에서 갤럭시를 검색·클릭하는 양이 줄고(노출·클릭·트래픽 하락), 들어와도 구매로 덜 이어집니다(전환율 하락).", "impact_direction": "-", "impact_horizon": "months", "confidence": "high", "metric": "both", "source": "apple.com", "impact": "프리미엄 구매자 일부가 Apple로 이동 → 유입·전환 하락 압력"}, {"event_id": "E006", "date": "2026-06-08", "captured_date": "2026-06-22", "scope": "US;GB;DE;FR;KR", "divisions": "MX", "kpi": "Traffic;Order;Revenue", "category": "company", "title": "Apple 하반기 대량 출시: 폴더블 아이폰, 터치 맥북", "description": "Apple이 폴더블 아이폰을 비롯해 하반기에 신제품을 쏟아냅니다. 특히 폴더블은 Galaxy Z Fold와 직접 경쟁해서, 출시가 겹치는 시기에 삼성 폴더블을 찾는 유입과 주문, 매출이 눌릴 수 있습니다.", "impact_direction": "-", "impact_horizon": "months", "confidence": "high", "metric": "both", "source": "macrumors.com", "impact": "폴더블 아이폰이 Z Fold 수요를 잠식 → 트래픽·주문·매출 영향"}, {"event_id": "E007", "date": "2026-02-28", "captured_date": "2026-06-22", "scope": "IN;TR", "divisions": "MX;VD", "kpi": "Traffic;CVR;Order;Revenue", "category": "geopolitics", "title": "호르무즈 해협 사실상 봉쇄, 유가 공급 충격", "description": "호르무즈 해협 봉쇄로 유가와 물류비가 오르고 소비가 둔화됐습니다. 인도·튀르키예 같은 시장에서 사람들이 전자제품 지출을 줄이면, samsung.com 유입부터 전환·주문·매출까지 전반이 눌립니다.", "impact_direction": "-", "impact_horizon": "months", "confidence": "high", "metric": "both", "source": "eia.gov", "impact": "유가·물류비 급등과 수요 둔화 → 해당 시장 유입·전환·주문·매출 부담"}, {"event_id": "E008", "date": "2026-06-19", "captured_date": "2026-06-22", "scope": "US;GB;DE;FR;ES;PT;BR;MX_C;AU;IN;TR;KR", "divisions": "MX;VD;DA", "kpi": "CVR;Order;AOV;Revenue", "category": "economy", "title": "브렌트유 휴전으로 ~$77 완화, 여전히 높은 수준", "description": "유가가 조금 내렸지만 분쟁 전보다 여전히 높습니다. 에너지·생활비 부담이 크면 사람들은 비싼 전자제품 구매를 미루거나 더 싼 모델로 바꿉니다. samsung.com에 들어와도 결제까지 덜 가고(전환율↓), 주문 수가 줄며(주문↓), 한 번에 쓰는 금액도 작아져(객단가↓) 매출이 눌립니다.", "impact_direction": "-", "impact_horizon": "weeks", "confidence": "high", "metric": "both", "source": "tradingeconomics.com", "impact": "높은 에너지·물가로 소비 위축 → 전환·주문·객단가·매출 동반 하락"}, {"event_id": "E009", "date": "2026-01-01", "captured_date": "2026-06-22", "scope": "IN", "divisions": "", "kpi": "CVR;Order;AOV;Revenue", "category": "geopolitics", "title": "러시아 원유 제재로 인도 수급 재편", "description": "러시아 원유 제재로 인도의 물가와 환율이 출렁입니다. 핵심 물량 시장인 인도에서 구매력이 약해지면, 중급기 위주로 전환·주문·객단가·매출이 영향을 받습니다.", "impact_direction": "neutral", "impact_horizon": "months", "confidence": "med", "metric": "both", "source": "jpmorgan.com", "impact": "인도 인플레·환율 압력 → 중급기 전환·주문·객단가·매출 영향"}, {"event_id": "E010", "date": "2026-02-09", "captured_date": "2026-06-22", "scope": "DE;FR;GB", "divisions": "", "kpi": "Traffic;CVR", "category": "regulation", "title": "AI 답변 변화가 EU GDPR 규제와 교차", "description": "GDPR·EU AI법이 개인화와 트래킹을 제약합니다. 어디서 유입됐는지 추적이 어려워지면, samsung.com의 유입 기여도 분석과 전환 최적화가 까다로워집니다.", "impact_direction": "neutral", "impact_horizon": "months", "confidence": "low", "metric": "traffic", "source": "[verify - EU AI Act]", "impact": "EU 개인화·트래킹 제약 → 유입 기여도 분석과 전환 최적화에 영향"}];
const WIKI={"updated": "2026-06-22 06:00 UTC (시드)", "divisions": {"Samsung": "ALL", "Apple": "MX", "LG": "VD", "Whirlpool": "DA"}, "series": {"Samsung": [{"date": "2026-04-01", "views": 24100}, {"date": "2026-04-23", "views": 28800}, {"date": "2026-05-01", "views": 23500}, {"date": "2026-06-01", "views": 24900}, {"date": "2026-06-08", "views": 33200}, {"date": "2026-06-19", "views": 27600}, {"date": "2026-06-22", "views": 25800}], "Apple": [{"date": "2026-04-01", "views": 19800}, {"date": "2026-04-23", "views": 41027}, {"date": "2026-05-01", "views": 20100}, {"date": "2026-06-01", "views": 21500}, {"date": "2026-06-08", "views": 46300}, {"date": "2026-06-19", "views": 24800}, {"date": "2026-06-22", "views": 22100}], "LG": [{"date": "2026-04-01", "views": 6300}, {"date": "2026-04-23", "views": 9800}, {"date": "2026-05-01", "views": 6100}, {"date": "2026-06-01", "views": 6400}, {"date": "2026-06-08", "views": 8700}, {"date": "2026-06-19", "views": 6900}, {"date": "2026-06-22", "views": 6500}], "Whirlpool": [{"date": "2026-04-01", "views": 2100}, {"date": "2026-04-23", "views": 2200}, {"date": "2026-05-01", "views": 2050}, {"date": "2026-06-01", "views": 2150}, {"date": "2026-06-08", "views": 2300}, {"date": "2026-06-19", "views": 2600}, {"date": "2026-06-22", "views": 2250}]}};
const REGIONS={"ALL":null,"북미":["US"],"유럽":["GB","DE","FR","ES","PT"],"중남미":["BR","MX_C"],"동남아":["AU"],"서남아":["IN"],"중동":["TR"],"한국":["KR"]};
const COUNTRIES=[["ALL","전체"],["US","미국"],["GB","영국"],["DE","독일"],["FR","프랑스"],["ES","스페인"],["PT","포르투갈"],["BR","브라질"],["MX_C","멕시코"],["AU","호주"],["IN","인도"],["TR","튀르키예"],["KR","한국"]];
const DIV2COMP={MX:"Apple",VD:"LG",DA:"Whirlpool"};
const ALL_COUNTRIES=["US","GB","DE","FR","ES","PT","BR","MX_C","AU","IN","TR","KR"];
const ALL_DIVS=["MX","VD","DA"];
const C2KO={US:"미국",GB:"영국",DE:"독일",FR:"프랑스",ES:"스페인",PT:"포르투갈",BR:"브라질",MX_C:"멕시코",AU:"호주",IN:"인도",TR:"튀르키예",KR:"한국"};
// 영향 국가 표기: 12개국 전부면 '전체', 아니면 한글 나열
function scopeLabelKo(scope){
 const arr=(scope||'').split(';').filter(x=>x);
 if(!arr.length) return '—';
 if(ALL_COUNTRIES.every(c=>arr.includes(c))) return '전체';
 return arr.map(c=>C2KO[c]||c).join(', ');
}
// 영향 사업부 표기: MX/VD/DA 전부면 '전체', 없으면 '—'
function divLabel(divs){
 const arr=(divs||'').split(';').filter(x=>x);
 if(!arr.length) return '전체';
 if(ALL_DIVS.every(dd=>arr.includes(dd))) return '전체';
 return arr.join(', ');
}
const DIRLAB={"-":"negative","+":"positive","neutral":"neutral","unknown":"unknown"};
const DIRC={"-":"#E24B4A","+":"#1D9E75","neutral":"#9a9a96","unknown":"#9a9a96"};
const DIRCLS={"-":"neg","+":"pos","neutral":"","unknown":""};
const KPIORDER=["Impression","Click","Traffic","Order","CVR","Revenue","AOV"];
const KPICOL={Impression:"#185FA5",Click:"#185FA5",Traffic:"#185FA5",Order:"#534AB7",CVR:"#534AB7",Revenue:"#534AB7",AOV:"#534AB7"};
const KPIBG={Impression:"#E6F1FB",Click:"#E6F1FB",Traffic:"#E6F1FB",Order:"#EEEDFE",CVR:"#EEEDFE",Revenue:"#EEEDFE",AOV:"#EEEDFE"};
const region=document.getElementById('region'),country=document.getElementById('country'),dv=document.getElementById('div'),kpi=document.getElementById('kpi'),sd=document.getElementById('sd'),ed=document.getElementById('ed'),csd=document.getElementById('csd'),ced=document.getElementById('ced');
const CONFW={high:3,med:2,low:1};
let showAll=false;  // 더보기 펼침 상태
// 두 구간(비교 기간 vs 현재 기간) Samsung 평균 조회수 증감률 판정
function trendVerdict(){
 // 네 날짜가 모두 있어야 판정 (현재 기간 + 비교 기간)
 if(!(csd.value && ced.value && sd.value && ed.value)) return null;
 const sam=wikiSeries("Samsung"); if(!sam.length) return null;
 const avg=(from,to)=>{
  const vals=sam.filter(p=>p.date>=from && p.date<=to).map(p=>p.views);
  return vals.length? vals.reduce((a,b)=>a+b,0)/vals.length : null;
 };
 const baseAvg=avg(csd.value, ced.value);
 const curAvg=avg(sd.value, ed.value);
 if(baseAvg==null || curAvg==null || baseAvg===0) return null;
 const pct=(curAvg-baseAvg)/baseAvg*100;
 return {pct, dir: pct<0?'-':(pct>0?'+':'neutral'),
         baseFrom:csd.value, baseTo:ced.value, curFrom:sd.value, curTo:ed.value};
}
region.innerHTML=Object.keys(REGIONS).map((r,i)=>`<option value="${r}"${i===0?' selected':''}>${r==='ALL'?'전체':r}</option>`).join('');
function syncCountries(){const reg=REGIONS[region.value];
 const list=reg?COUNTRIES.filter(c=>c[0]==='ALL'||reg.includes(c[0])):COUNTRIES;
 country.innerHTML=list.map((c,i)=>`<option value="${c[0]}"${i===0?' selected':''}>${c[1]}</option>`).join('');}
syncCountries();
// 국가 선택 시 그 국가가 속한 지역으로 region 자동 변경
function regionOfCountry(code){
 for(const[rk,arr]of Object.entries(REGIONS)){ if(arr && arr.includes(code)) return rk; }
 return 'ALL';
}
function onCountryChange(){
 const picked=country.value;
 if(picked!=='ALL'){
  const rk=regionOfCountry(picked);
  if(region.value!==rk){
   region.value=rk;
   // 지역 바뀌면 국가 목록 재구성하되 선택값 유지
   const reg=REGIONS[rk];
   const list=reg?COUNTRIES.filter(c=>c[0]==='ALL'||reg.includes(c[0])):COUNTRIES;
   country.innerHTML=list.map(c=>`<option value="${c[0]}"${c[0]===picked?' selected':''}>${c[1]}</option>`).join('');
  }
 }
 showAll=false; render();
}
function activeCountrySet(){if(country.value!=='ALL')return [country.value];const reg=REGIONS[region.value];return reg?reg:null;}
function rows(){let r=EV.slice();
 // 국가/지역: 특정값이면 그 값(들) 중 하나라도 포함된 요인 / '전체'면 제한 없음(합집합)
 const cs=activeCountrySet();
 if(cs){ r=r.filter(e=>{const sc=(e.scope||'').split(';');return cs.some(c=>sc.includes(c));}); }
 // 사업부: 특정값이면 포함 / '전체'면 제한 없음
 if(dv.value!=='ALL'){ r=r.filter(e=>(e.divisions||'').split(';').includes(dv.value)); }
 // KPI: 특정값이면 포함 / '전체'면 제한 없음
 if(kpi.value!=='ALL'){ r=r.filter(e=>(e.kpi||'').split(';').includes(kpi.value)); }
 if(sd.value)r=r.filter(e=>(e.date||'')>=sd.value);
 if(ed.value)r=r.filter(e=>(e.date||'')<=ed.value);
 return r.sort((a,b)=>(b.date||'').localeCompare(a.date||''));}

// ---- trend graph ----
function wikiSeries(brand){return (WIKI.series&&WIKI.series[brand])||[];}
function compNames(){return dv.value==='ALL'?["Apple","LG","Whirlpool"]:[DIV2COMP[dv.value]];}
function compLabel(){return dv.value==='ALL'?'기업 합산':compNames()[0];}
let chart;
// 핀 모양(원형 본체+꼬리+발광 앵커점+연결선)을 그리는 커스텀 플러그인
const pinPlugin={
 id:'pins',
 afterDatasetsDraw(c){
  const ctx=c.ctx; const pins=c._pins||[];
  pins.forEach(p=>{
   const x=c.scales.x.getPixelForValue(p.xLabel);
   const yLine=c.scales.y.getPixelForValue(p.anchorY);
   const r=12, pinY=yLine-30;
   ctx.save();
   ctx.strokeStyle=p.color; ctx.lineWidth=1.5; ctx.globalAlpha=0.5;
   ctx.beginPath(); ctx.moveTo(x,yLine-3); ctx.lineTo(x,pinY+r); ctx.stroke();
   ctx.globalAlpha=1;
   ctx.beginPath(); ctx.arc(x,yLine,5,0,7); ctx.fillStyle=p.color; ctx.globalAlpha=0.25; ctx.fill();
   ctx.globalAlpha=1; ctx.beginPath(); ctx.arc(x,yLine,3,0,7); ctx.fillStyle=p.color; ctx.fill();
   ctx.strokeStyle='#fff'; ctx.lineWidth=1.5; ctx.stroke();
   ctx.shadowColor='rgba(0,0,0,0.18)'; ctx.shadowBlur=6; ctx.shadowOffsetY=2;
   ctx.beginPath(); ctx.moveTo(x-5,pinY+r-2); ctx.lineTo(x+5,pinY+r-2); ctx.lineTo(x,pinY+r+6); ctx.closePath();
   ctx.fillStyle=p.color; ctx.fill();
   ctx.beginPath(); ctx.arc(x,pinY,r,0,7); ctx.fillStyle=p.color; ctx.fill();
   ctx.shadowColor='transparent';
   ctx.lineWidth=2; ctx.strokeStyle='#fff'; ctx.stroke();
   ctx.fillStyle='#fff'; ctx.font='bold 12px -apple-system,Arial'; ctx.textAlign='center'; ctx.textBaseline='middle';
   ctx.fillText(String(p.n),x,pinY);
   ctx.restore();
  });
 }
};
// 핀 클릭 시 해당 번호 카드로 스크롤 + 하이라이트
function scrollToCard(n){
 let el=document.getElementById('evt-'+n);
 if(!el && !showAll){ showAll=true; render(); el=document.getElementById('evt-'+n); }
 if(el){
  el.scrollIntoView({behavior:'smooth',block:'center'});
  el.classList.add('flash');
  setTimeout(()=>el.classList.remove('flash'),1600);
 }
}
function drawTrend(evSortedAsc, numByDate){
 const sam=wikiSeries("Samsung");
 // 표시 범위: 비교 기간 시작일 ~ 현재 기간 종료일 (비교 기간 입력이 있으면), 아니면 현재 기간만
 let fromDate=sd.value||'', toDate=ed.value||'';
 if(csd.value) fromDate=csd.value;          // 비교 기간 시작일이 있으면 거기서부터
 if(ed.value)  toDate=ed.value;             // 현재 기간 종료일까지
 else if(ced.value) toDate=ced.value;
 let pts=sam.map(p=>p.date);
 if(fromDate)pts=pts.filter(dt=>dt>=fromDate);
 if(toDate)pts=pts.filter(dt=>dt<=toDate);
 const labels=pts;
 const samData=labels.map(dt=>{const f=sam.find(p=>p.date===dt);return f?f.views:null;});
 const names=compNames();
 const total=labels.map(dt=>names.reduce((s,n)=>{const ser=wikiSeries(n);const f=ser.find(p=>p.date===dt);return s+(f?f.views:0);},0));
 // y축 최댓값을 데이터 최고점보다 25% 높게 잡아 핀 공간 확보
 const dataMax=Math.max(1,...samData.filter(v=>v!=null),...total);
 const yMax=Math.ceil(dataMax*1.25/1000)*1000;
 const pins=[];
 evSortedAsc.forEach((e)=>{
  if(labels.length && (e.date<labels[0] || e.date>labels[labels.length-1])) return; // 범위 밖 요인은 생략
  let nearIdx=0; for(let k=0;k<labels.length;k++){ if(labels[k]<=e.date) nearIdx=k; }
  const sv=samData[nearIdx], tv=total[nearIdx];
  pins.push({n:(numByDate&&numByDate[e.date])||'',xLabel:labels[nearIdx],anchorY:Math.max(sv==null?0:sv, tv),color:DIRC[e.impact_direction]||'#999'});
 });
 document.getElementById('legend').innerHTML=
  `<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:2px;background:#1428A0;display:inline-block"></span>Samsung (기준)</span>`+
  `<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:2px;background:#888;display:inline-block"></span>${compLabel()}</span>`;
 document.getElementById('tsub').textContent='(일별 조회수, 합산)';
 if(chart)chart.destroy();
 chart=new Chart(document.getElementById('trend'),{type:'line',
  data:{labels,datasets:[
   {label:'Samsung',data:samData,borderColor:'#1428A0',backgroundColor:'#1428A014',tension:0.35,pointRadius:0,borderWidth:2.5,spanGaps:true},
   {label:compLabel(),data:total,borderColor:'#888780',backgroundColor:'#88878014',tension:0.35,pointRadius:0,borderWidth:2}]},
  options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:30}},
   onClick:(evt)=>{
     const rect=evt.chart.canvas.getBoundingClientRect();
     const px=evt.x; const py=evt.y;
     const ps=evt.chart._pins||[];
     let best=null,bestD=1e9;
     ps.forEach(p=>{
      const x=evt.chart.scales.x.getPixelForValue(p.xLabel);
      const yLine=evt.chart.scales.y.getPixelForValue(p.anchorY);
      const pinY=yLine-30;
      const dx=px-x, dy=py-pinY; const dist=Math.sqrt(dx*dx+dy*dy);
      if(dist<bestD){bestD=dist;best=p;}
     });
     if(best && bestD<24){ scrollToCard(best.n); }
   },
   plugins:{legend:{display:false},
     tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.parsed.y||0).toLocaleString()+'회'}}},
   scales:{x:{ticks:{color:'#888780',font:{size:11},maxTicksLimit:8},grid:{display:false}},
     y:{suggestedMax:yMax,ticks:{color:'#888780',font:{size:11},callback:v=>(v/1000)+'k'},grid:{color:'rgba(136,135,128,0.10)'}}}},
  plugins:[pinPlugin]});
 chart._pins=pins; chart.update();
}

function kpiTags(k){const list=(k||'').split(';').filter(x=>x).sort((a,b)=>KPIORDER.indexOf(a)-KPIORDER.indexOf(b));
 return list.map(x=>`<span class="ktag" style="background:${KPIBG[x]||'#eee'};color:${KPICOL[x]||'#444'}">${x}</span>`).join('');}

function render(){
 let r=rows();  // 기존 모든 필터(지역·국가·사업부·KPI·영향·기간) 적용된 결과
 // 비교기간 판정: 트렌드 방향 요인을 위로, 나머지도 제외 없이 신뢰도순(neutral 뒤로)
 const vd=trendVerdict();
 const vbox=document.getElementById('verdict');
 const confRank=e=>CONFW[e.confidence]||0;
 if(vd && vd.dir!=='neutral'){
  // 정렬: ① 트렌드 방향과 같은 요인 먼저 ② 신뢰도 high순 ③ neutral은 같은 신뢰도 안에서 뒤로 ④ 최신순
  const dirMatch=e=> e.impact_direction===vd.dir ? 0 : (e.impact_direction==='neutral'?2:1);
  r.sort((a,b)=>
    dirMatch(a)-dirMatch(b)
    || confRank(b)-confRank(a)
    || ((a.impact_direction==='neutral'?1:0)-(b.impact_direction==='neutral'?1:0))
    || (b.date||'').localeCompare(a.date||''));
  const vc=vd.dir==='-'?'#E24B4A':'#1D9E75';
  const arrow=vd.dir==='-'?'▼':'▲';
  const pickLabel=vd.dir==='-'?'트래픽 하락 → negative 요인 우선':'트래픽 상승 → positive 요인 우선';
  vbox.style.display='block'; vbox.style.background=vc+'14'; vbox.style.border='1px solid '+vc+'44';
  vbox.innerHTML=`<span style="color:${vc};font-weight:600">Samsung ${arrow} ${vd.pct.toFixed(1)}%</span> · <span style="color:var(--muted)">${pickLabel}, 신뢰도순 정렬 · 비교 ${vd.baseFrom}~${vd.baseTo} → 현재 ${vd.curFrom}~${vd.curTo}</span>`;
 } else if(vd){
  // 변화 미미: 신뢰도순(neutral 뒤로)
  r.sort((a,b)=> confRank(b)-confRank(a) || ((a.impact_direction==='neutral'?1:0)-(b.impact_direction==='neutral'?1:0)) || (b.date||'').localeCompare(a.date||''));
  vbox.style.display='block'; vbox.style.background='var(--bg)'; vbox.style.border='1px solid var(--line)';
  vbox.innerHTML=`<span style="color:var(--muted)">Samsung 변화 미미(${vd.pct.toFixed(1)}%) — 신뢰도순 정렬</span>`;
 } else { vbox.style.display='none'; }

 const numByDate={}; r.forEach((e,i)=>{ if(!(e.date in numByDate)) numByDate[e.date]=i+1; });
 const evAsc=r.slice().sort((a,b)=>(a.date||'').localeCompare(b.date||''));
 drawTrend(evAsc, numByDate);

 const neg=r.filter(x=>x.impact_direction==='-').length;
 const scopeLabel=country.value!=='ALL'?(COUNTRIES.find(c=>c[0]===country.value)||['','전체'])[1]:(region.value!=='ALL'?region.value:'전체');
 document.getElementById('cards').innerHTML=
  `<div class="card"><div class="lbl">전체 이벤트</div><div class="val">${r.length}</div></div>`+
  `<div class="card"><div class="lbl">negative</div><div class="val" style="color:var(--neg)">${neg}</div></div>`+
  `<div class="card"><div class="lbl">대상</div><div class="val" style="font-size:18px">${scopeLabel}</div></div>`;
 // 상위 10개 + 더보기
 const LIMIT=10;
 const shown=showAll?r:r.slice(0,LIMIT);
 const cardsHtml = r.length? shown.map((e,i)=>{
   const cls=DIRCLS[e.impact_direction]||'';const bc=DIRC[e.impact_direction]||'#9a9a96';
   const meta=[DIRLAB[e.impact_direction]||'',e.confidence||''].filter(x=>x);
   const imp=e.impact?`<div class="imp" style="color:${bc};background:${bc}14">${e.impact}</div>`:'';
   const badge=`<span class="numbadge" style="background:${bc}">${i+1}</span>`;
   // 본문에서 출처/필터 태그·"1차 출처 업데이트"·"원문:" 제거
   let desc=(e.description||'')
     .replace(/\s*\[출처:[^\]]*\]/g,'')
     .replace(/\s*\[filter:[^\]]*\]/g,'')
     .replace(/\s*\[source:[^\]]*\]/g,'')
     .replace(/1차 출처 업데이트[^—]*—\s*/g,'')
     .replace(/원문:\s*/g,'')
     .trim();
   const src=e.source||'';
   return `<div class="evt ${cls}" id="evt-${i+1}"><div class="top"><span class="ttl">${badge}${e.title}</span><span class="meta">${e.date||''}</span></div>
     <div class="indent">${meta.map(t=>`<span class="tag">${t}</span>`).join('')}</div>${imp?'<div class="indent">'+imp+'</div>':''}
     <div class="desc indent">${desc}</div>
     <div class="kline indent"><span class="klbl">영향 KPI:</span>${kpiTags(e.kpi)}</div>
     <div class="kline indent"><span class="klbl">영향 국가:</span><span class="metaval">${scopeLabelKo(e.scope)}</span></div>
     <div class="kline indent"><span class="klbl">영향 사업부:</span><span class="metaval">${divLabel(e.divisions)}</span></div>
     ${src?`<div class="srcline">source: ${src}</div>`:''}</div>`;}).join('') : '<div class="empty">해당 조건에 맞는 이벤트가 없습니다.</div>';
 const moreBtn = (r.length>LIMIT)? `<button id="morebtn" style="display:block;margin:4px auto 0;padding:9px 20px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--blue);font-size:13px;font-weight:500;cursor:pointer">${showAll?'접기':'더보기 ('+(r.length-LIMIT)+'개 더)'}</button>` : '';
 document.getElementById('list').innerHTML = cardsHtml + moreBtn;
 const mb=document.getElementById('morebtn');
 if(mb) mb.onclick=()=>{ showAll=!showAll; render(); };
}
function exportCSV(){const r=rows();
 const h=['date','scope','divisions','kpi','title','impact','description','impact_direction','confidence','source','raw_title','raw_desc','raw_url'];
 const csv=[h.join(',')].concat(r.map(x=>h.map(k=>`"${(x[k]||'').toString().replace(/"/g,'""')}"`).join(','))).join('\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+csv,{type:'text/csv;charset=utf-8'}]));a.download='scom_external_factors.csv';a.click();}
document.getElementById('csvbtn').onclick=exportCSV;
region.onchange=()=>{showAll=false;syncCountries();render();};
country.onchange=onCountryChange;
[dv,kpi,sd,ed,csd,ced].forEach(el=>el.onchange=()=>{showAll=false;render();});render();
</script></body></html>