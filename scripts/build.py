#!/usr/bin/env python3
"""Build the self-contained Korean dashboard (index.html).
Filters: region(7) → country(12) → division(MX/VD/DA) → KPI → impact → date range.
Trend graph: Samsung baseline + selected-division company total (Wikipedia views),
with numbered callout markers for events mapped to a list below.
Cards: one-line impact summary + plain-language body + affected KPIs."""
import os, json
from datetime import datetime, timezone

HERE=os.path.dirname(__file__)
DATA=os.path.join(HERE,"..","data","events.json")
WIKI=os.path.join(HERE,"..","data","wiki_series.json")
MSTAT=os.path.join(HERE,"..","data","model_status.json")
OUT=os.path.join(HERE,"..","index.html")

events=json.load(open(DATA,encoding="utf-8"))
updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Default period: year-to-date YoY (current = Jan 1..today, comparison = last year Jan 1..same day)
_today = datetime.now(timezone.utc).date()
DEF_CUR_FROM = _today.replace(month=1, day=1).isoformat()
DEF_CUR_TO   = _today.isoformat()
try:
    _ly_to = _today.replace(year=_today.year-1)
except ValueError:
    _ly_to = _today.replace(year=_today.year-1, day=28)  # 2/29 보정
DEF_CMP_FROM = _ly_to.replace(month=1, day=1).isoformat()
DEF_CMP_TO   = _ly_to.isoformat()
try: wiki=json.load(open(WIKI,encoding="utf-8"))
except Exception: wiki={"series":{},"divisions":{}}
try: mstat=json.load(open(MSTAT,encoding="utf-8"))
except Exception: mstat={}
_MSTAT_DEFAULT={"model":"unknown","status":"unknown","note":""}
def _mstat_of(name):
    return mstat.get(name, _MSTAT_DEFAULT) or _MSTAT_DEFAULT
try: imf_series=json.load(open(os.path.join(HERE,"..","data","imf_series.json"),encoding="utf-8"))
except Exception: imf_series={"countries":{},"indicators":{},"data":{}}
try: crux=json.load(open(os.path.join(HERE,"..","data","crux_series.json"),encoding="utf-8"))
except Exception: crux={"metrics":{}}
# The country-statistics tab uses IMF monthly data only (World Bank removed)
stats_series=imf_series

HTML=r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>External Event Dashboard</title>
<style>
:root{--blue:#1428A0;--blue-d:#0d1b6e;--ink:#202124;--muted:#6b7280;--line:#e8eaed;--bg:#f4f6f9;--card:#fff;--neg:#D0392B;--pos:#137a52;--neu:#9aa0a6;--accent:#1428A0}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Samsung Sharp Sans','SamsungOne',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Malgun Gothic',Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.55;padding:0;margin:0}
.wrap{max-width:1120px;margin:0 auto;padding:24px}
.brandbar{background:linear-gradient(100deg,var(--blue) 0%,var(--blue-d) 100%);color:#fff;padding:22px 28px;border-radius:16px;margin:20px 20px 0}
.brandbar h1{font-size:21px;font-weight:600;letter-spacing:-0.01em;color:#fff;margin:0}
.brandbar .sub{font-size:12.5px;color:rgba(255,255,255,0.82);margin-top:3px}
.tabbar{display:flex;gap:4px;margin:16px 20px 0;border-bottom:2px solid var(--line)}
.tab{padding:11px 20px;font-size:14px;font-weight:600;color:var(--muted);cursor:pointer;border:none;background:none;border-bottom:2px solid transparent;margin-bottom:-2px}
.tab.active{color:var(--blue);border-bottom-color:var(--blue)}
.tabpane{display:none}.tabpane.active{display:block}
.cp-card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:0 1px 2px rgba(20,40,160,0.04);margin-bottom:12px}
.cp-cause{border:1px solid var(--line);border-radius:0;padding:11px 14px;margin-bottom:8px}
.cp-tag{font-size:11px;background:#f7f8fb;padding:3px 9px;border-radius:8px;margin-right:5px;color:#5f6368}
h1{font-size:20px;font-weight:600;color:var(--blue)}
.sub{font-size:13px;color:var(--muted)}
.mbadges{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}
.mbadge{display:inline-flex;align-items:center;gap:7px;font-size:12px;padding:5px 11px;border-radius:20px;margin-bottom:0;border:1px solid var(--line);background:#fff}
.mbadge .dot{width:8px;height:8px;border-radius:50%}
.mbadge.ok{background:#eaf6f0;border-color:#c2e6d4;color:#137a52}.mbadge.ok .dot{background:#137a52}
.mbadge.retired{background:#fbeae8;border-color:#f3c4bd;color:#a3271f}.mbadge.retired .dot{background:#D0392B}
.mbadge.unknown,.mbadge.error{background:#fef6e0;border-color:#f0e2b8;color:#8a6d1a}
.mbadge.unknown .dot,.mbadge.error .dot{background:#EF9F27}
.controls{display:block;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px;box-shadow:0 1px 2px rgba(20,40,160,0.04)}
.filterrow{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-bottom:16px}
.periodrow{display:flex;gap:14px;flex-wrap:wrap;align-items:stretch}
.periodpick{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;margin-bottom:14px;padding-bottom:14px;border-bottom:1px dashed var(--line)}
.periodpick .ctrl{min-width:130px}
.periodpick select{min-width:130px}
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

#csvbtn{padding:9px 18px;border:none;border-radius:9px;background:var(--blue);color:#fff;font-size:13px;font-weight:600;cursor:pointer;height:38px}
#csvbtn:hover{background:var(--blue-d)}
.ctrl{display:flex;flex-direction:column;gap:5px;min-width:120px}.ctrl label{font-size:11px;color:var(--muted);font-weight:500;white-space:nowrap}
.btn{height:38px;padding:0 14px;border:1px solid var(--line);border-radius:9px;background:#fff;color:var(--blue);font-size:13px;font-weight:500;cursor:pointer;white-space:nowrap}
.btn:hover{border-color:var(--blue);box-shadow:0 0 0 3px rgba(20,40,160,0.08)}
.btnwrap{display:flex;flex-direction:column;gap:5px;justify-content:flex-end}.btnwrap label{font-size:11px;color:transparent;font-weight:500;white-space:nowrap}
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
.srcline{display:flex;flex-direction:column;align-items:flex-end;gap:2px;margin-top:10px;font-size:11px;color:#9aa0a6}
.srcline>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
.llmtag{color:#b0b0aa;font-style:italic}
.evt{position:relative;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--neu);border-radius:12px;padding:15px 17px;margin-bottom:12px;box-shadow:0 1px 2px rgba(20,40,160,0.04)}
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
.empty{padding:30px;text-align:center;color:var(--muted)}
.foot{font-size:12px;color:#8a6d1a;margin-top:16px;padding:12px;background:#fff8e8;border:1px solid #f0e2b8;border-radius:10px}
</style></head><body>
<div class="brandbar"><h1>External Event Dashboard</h1>
  <div class="sub">S.com 외부 요인 모니터링 대시보드 · 매일 자동 갱신 · 마지막 빌드 __UPDATED__</div></div>
<div class="tabbar">
  <button class="tab active" data-tab="factors">외부 요인</button>
  <button class="tab" data-tab="stats">국가별 통계</button>
</div>
<div class="wrap">
<div id="tab-factors" class="tabpane active">
<div class="mbadges">__MBADGES__</div>
<div class="controls">
 <div class="filterrow">
  <div class="ctrl"><label>지역</label><select id="region"></select></div>
  <div class="ctrl"><label>국가</label><select id="country"></select></div>
  <div class="ctrl"><label>사업부</label><select id="div">
    <option value="ALL">전체</option><option value="MX">MX</option><option value="VD">VD</option><option value="DA">DA</option></select></div>
  <div class="ctrl"><label>기간</label>
   <select id="ptype">
    <option value="day">Day</option>
    <option value="week">Week</option>
    <option value="month">Month</option>
    <option value="quarter">Quarter</option>
    <option value="year">Year</option>
    <option value="mtd">MTD</option>
    <option value="qtd">QTD</option>
    <option value="ytd" selected>YTD</option>
   </select>
  </div>
  <div class="ctrl" id="pickerWrap"></div>
  <div class="ctrl"><label>비교 기간</label><select id="cmpBasis"></select></div>
 </div>
 <div class="filterrow" style="justify-content:flex-end">
  <div class="btnwrap"><label>.</label>
   <input type="file" id="trafficFile" accept=".csv" style="display:none">
   <button class="btn" id="uploadBtn" title="국가,날짜,트래픽 형식의 CSV. 브라우저에서만 처리되며 저장되지 않습니다.">Upload Traffic</button></div>
  <div class="btnwrap"><label>.</label>
   <button class="btn" id="clearTrafficBtn">Clear Upload</button></div>
 </div>
 <div class="filterrow" style="justify-content:flex-end">
  <div class="btnwrap"><label>.</label>
   <button class="btn" id="csvbtn">Download Events</button></div>
 </div>
 <div id="csvStatus" style="font-size:12px;color:var(--muted);margin-bottom:8px"></div>
 <div id="periodSummary" style="font-size:12px;color:var(--muted);margin-bottom:8px"></div>
 <div class="periodrow" style="display:none">
  <div class="pgroup cmp">
   <div class="pglabel"><span class="pgdot"></span>비교 기간</div>
   <div class="pgfields">
    <div class="ctrl"><label>시작일</label><input type="date" id="csd" value="__DEF_CMP_FROM__"></div>
    <div class="ctrl"><label>종료일</label><input type="date" id="ced" value="__DEF_CMP_TO__"></div>
   </div>
  </div>
  <div class="parrow">→</div>
  <div class="pgroup cur">
   <div class="pglabel"><span class="pgdot"></span>현재 기간</div>
   <div class="pgfields">
    <div class="ctrl"><label>시작일</label><input type="date" id="sd" value="__DEF_CUR_FROM__"></div>
    <div class="ctrl"><label>종료일</label><input type="date" id="ed" value="__DEF_CUR_TO__"></div>
   </div>
  </div>
 </div>
</div>

<div class="panel">
  <div class="phead"><div class="ptitle">위키피디아 조회수 추세 <span id="tsub" style="font-size:11px;color:#999;font-weight:400"></span></div>
    <div class="legend" id="legend"></div></div>
  <div style="position:relative;height:250px"><canvas id="trend"></canvas></div>
  <div class="note">번호 핀 = 외부 요인 발생 시점 · 아래 요인 카드의 번호와 연결 · 위키피디아 일별 조회수(외부 추정 신호, 기업 실측 트래픽 아님) · 영향강도=samsung.com 트래픽에 주는 영향 크기(1~5), 신뢰도=그 판단에 대한 확신(high/med/low)</div>
</div>

<div id="verdict" style="display:none;border-radius:12px;padding:14px 16px;margin-bottom:16px;font-size:14px"></div>

<div class="panel" id="axisPanel" style="display:none">
  <div class="phead"><div class="ptitle">3축 진단 — 수요 · 점유 · 공급 <span style="font-size:11px;color:#999;font-weight:400">(위키 관심도 기준 추정)</span></div></div>
  <div id="axisSummary" style="font-size:13px;padding:11px 14px;border-radius:10px;background:var(--bg);margin-bottom:12px"></div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px" id="axisCards"></div>
  <div class="note">수요 = 시장 전체 관심량(삼성+경쟁사 위키 조회수 합) · 점유 = 그중 삼성이 가져가는 몫(%) · 공급 = 실사용자 사이트 성능(CrUX CWV) + 인덱싱·크롤링·장애 이벤트 · 기여도(%)는 "삼성 관심량 = 시장 전체 × 점유율" 항등식의 로그 분해로 계산 — 수요·점유 합이 전체 변화를 정확히 설명하며, 공급은 CrUX 성능 회귀가 감지될 때만 휴리스틱으로 배분 · 카드의 요인 목록에서 "펼치기"로 축별 전체 이벤트를 딥다이브할 수 있습니다 · 대리지표 기반이며 인과 입증이 아닙니다</div>
</div>
<div id="analysis" style="display:none;margin-bottom:16px">
  <div id="ana-period"></div>
</div>
<div id="topfactors" style="display:none;margin-bottom:16px"></div>

<div class="cards" id="cards"></div>
<div id="list"></div>
<div class="foot">이벤트는 samsung.com 관련성 기준으로 자동 수집·필터링됩니다.</div>
</div><!-- /tab-factors -->

<div id="tab-stats" class="tabpane">
  <div class="controls" style="margin-top:16px">
    <div class="filterrow">
      <div class="ctrl"><label>국가</label><select id="st_country"></select></div>
      <div class="ctrl"><label>지표</label><select id="st_indicator"></select></div>
    </div>
  </div>
  <div class="panel">
    <div class="phead"><div class="ptitle" id="st_title">국가별 통계 추세</div>
      <div class="legend" id="st_meta"></div></div>
    <div style="position:relative;height:300px"><canvas id="st_chart"></canvas></div>
    <div class="note">IMF 월 단위 공개 통계(data.imf.org) · 매월 갱신 · 무료·자동</div>
  </div>
  <div class="foot">국가별 거시 통계는 뉴스·블로그 수집과 별개로, IMF 월 단위 공개 데이터(data.imf.org)를 기반으로 합니다. 일부 지표·국가는 IMF 제공 범위에 따라 비어 있을 수 있습니다.</div>
</div><!-- /tab-stats -->
</div><!-- /wrap -->

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/chartjs-plugin-annotation/3.0.1/chartjs-plugin-annotation.min.js"></script>
<script>
const EV=__DATA__;
const WIKI=__WIKI__;
const STATS=__STATS__;
const CRUX=__CRUX__;
const REGIONS={"ALL":null,"북미":["US"],"유럽":["GB","DE","FR","ES","PT"],"중남미":["BR","MX_C"],"동남아":["AU"],"서남아":["IN"],"중동":["TR"],"한국":["KR"]};
const COUNTRIES=[["ALL","전체"],["US","미국"],["GB","영국"],["DE","독일"],["FR","프랑스"],["ES","스페인"],["PT","포르투갈"],["BR","브라질"],["MX_C","멕시코"],["AU","호주"],["IN","인도"],["TR","튀르키예"],["KR","한국"]];
const DIV2COMP={MX:["Apple","Xiaomi","vivo","OPPO"],VD:["LG","TCL","Hisense"],DA:["LG","Whirlpool","Bosch"]};
const ALL_COUNTRIES=["US","GB","DE","FR","ES","PT","BR","MX_C","AU","IN","TR","KR"];
const ALL_DIVS=["MX","VD","DA"];
const C2KO={US:"미국",GB:"영국",DE:"독일",FR:"프랑스",ES:"스페인",PT:"포르투갈",BR:"브라질",MX_C:"멕시코",AU:"호주",IN:"인도",TR:"튀르키예",KR:"한국"};
// Scope label: 'all' if it covers all 12 markets, else list Korean names
function scopeLabelKo(scope){
 const arr=(scope||'').split(';').filter(x=>x);
 if(!arr.length) return '—';
 if(ALL_COUNTRIES.every(c=>arr.includes(c))) return '전체';
 return arr.map(c=>C2KO[c]||c).join(', ');
}
// Division label: 'all' if MX/VD/DA all present, '—' if none
function divLabel(divs){
 const arr=(divs||'').split(';').filter(x=>x);
 if(!arr.length) return '전체';
 if(ALL_DIVS.every(dd=>arr.includes(dd))) return '전체';
 return arr.join(', ');
}
const DIRC={"-":"#E24B4A","+":"#1D9E75","neutral":"#9a9a96","unknown":"#9a9a96"};
const CONFC={"high":"#1D9E75","med":"#EF9F27","low":"#9a9a96"};
const DIRCLS={"-":"neg","+":"pos","neutral":"","unknown":""};
const region=document.getElementById('region'),country=document.getElementById('country'),dv=document.getElementById('div'),sd=document.getElementById('sd'),ed=document.getElementById('ed'),csd=document.getElementById('csd'),ced=document.getElementById('ced');
const ptype=document.getElementById('ptype'),cmpBasis=document.getElementById('cmpBasis'),pickerWrap=document.getElementById('pickerWrap');

// ===== Flexible period selector =====
const PERIOD_PAIRS={
  day:["DoD","WoW","YoY"],
  week:["WoW","YoY"],
  month:["MoM","YoY"],
  quarter:["QoQ","YoY"],
  year:["YoY"],
  mtd:["MoM","YoY"],
  qtd:["QoQ","YoY"],
  ytd:["YoY"],
};
const MON_KO=["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];
function _isoDate(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function _wikiToday(){const s=wikiSeries("Samsung");return s.length?new Date(s[s.length-1].date+'T00:00'):new Date();}
function _yearOpts(sel){let o='';const ty=_wikiToday().getFullYear();for(let y=ty-2;y<=ty;y++)o+=`<option${y===sel?' selected':''}>${y}</option>`;return o;}
function buildPicker(t){
  const ty=_wikiToday();
  const lbl=s=>`<label>${s}</label>`;
  if(t==='day'||t==='week') return lbl(t==='week'?'주 (해당 주 아무 날)':'날짜')+`<input type="date" id="pv" value="${_isoDate(ty)}">`;
  if(t==='month') return lbl('연 · 월')+`<div style="display:flex;gap:6px"><select id="py">${_yearOpts(ty.getFullYear())}</select><select id="pm">${MON_KO.map((m,i)=>`<option value="${i}"${i===ty.getMonth()?' selected':''}>${m}</option>`).join('')}</select></div>`;
  if(t==='quarter') return lbl('연 · 분기')+`<div style="display:flex;gap:6px"><select id="py">${_yearOpts(ty.getFullYear())}</select><select id="pq">${[1,2,3,4].map(q=>`<option value="${q-1}"${(q-1)===Math.floor(ty.getMonth()/3)?' selected':''}>${q}분기</option>`).join('')}</select></div>`;
  if(t==='year') return lbl('연도')+`<select id="py" style="width:100%">${_yearOpts(ty.getFullYear())}</select>`;
  return `<label>&nbsp;</label><div style="font-size:11px;color:var(--muted);padding-top:9px">오늘(${_isoDate(ty)}) 기준 · 추가 입력 불필요</div>`;
}
function currentPeriod(t){
  const g=id=>document.getElementById(id), ty=_wikiToday();
  const y=ty.getFullYear(),m=ty.getMonth(),d=ty.getDate();
  if(t==='day'){const x=new Date(g('pv').value+'T00:00');return [x,x];}
  if(t==='week'){const x=new Date(g('pv').value+'T00:00');const s=new Date(x);s.setDate(x.getDate()-6);return [s,x];}
  if(t==='month'){const yy=+g('py').value,mm=+g('pm').value;return [new Date(yy,mm,1),new Date(yy,mm+1,0)];}
  if(t==='quarter'){const yy=+g('py').value,q=+g('pq').value,qs=q*3;return [new Date(yy,qs,1),new Date(yy,qs+3,0)];}
  if(t==='year'){const yy=+g('py').value;return [new Date(yy,0,1),new Date(yy,11,31)];}
  if(t==='mtd')return [new Date(y,m,1),new Date(y,m,d)];
  if(t==='qtd'){const qs=Math.floor(m/3)*3;return [new Date(y,qs,1),new Date(y,m,d)];}
  return [new Date(y,0,1),new Date(y,m,d)]; // ytd
}
function shiftPeriod(range,basis){
  const sh=dt=>{const x=new Date(dt);
    if(basis==='DoD')x.setDate(x.getDate()-1);
    else if(basis==='WoW')x.setDate(x.getDate()-7);
    else if(basis==='MoM')x.setMonth(x.getMonth()-1);
    else if(basis==='QoQ')x.setMonth(x.getMonth()-3);
    else if(basis==='YoY')x.setFullYear(x.getFullYear()-1);
    return x;};
  return [sh(range[0]),sh(range[1])];
}
function applyPeriod(){
  const t=ptype.value, basis=cmpBasis.value;
  const cur=currentPeriod(t), cm=shiftPeriod(cur,basis);
  sd.value=_isoDate(cur[0]); ed.value=_isoDate(cur[1]);
  csd.value=_isoDate(cm[0]); ced.value=_isoDate(cm[1]);
  const sumEl=document.getElementById('periodSummary');
  if(sumEl){
   const single=cur[0].getTime()===cur[1].getTime();
   const curTxt=single?_isoDate(cur[0]):`${_isoDate(cur[0])} ~ ${_isoDate(cur[1])}`;
   const cmTxt=single?_isoDate(cm[0]):`${_isoDate(cm[0])} ~ ${_isoDate(cm[1])}`;
   sumEl.innerHTML=`비교 <strong style="color:var(--ink)">${cmTxt}</strong> &nbsp;→&nbsp; 현재 <strong style="color:var(--blue)">${curTxt}</strong>`;
  }
}
function refreshPeriod(){
  const t=ptype.value;
  pickerWrap.innerHTML=buildPicker(t);
  pickerWrap.querySelectorAll('input,select').forEach(el=>el.onchange=()=>{applyPeriod();showAll=false;render();});
  cmpBasis.innerHTML=PERIOD_PAIRS[t].map((p,i)=>`<option value="${p}"${i===PERIOD_PAIRS[t].length-1?' selected':''}>${p}</option>`).join('');
  applyPeriod(); showAll=false; render();
}
const CONFW={high:3,med:2,low:1};
let showAll=false;  // 'show more' expanded state

// Detect change-points in Samsung wiki series within the current period (sd~ed).
// Method: compare 3-day trailing avg before vs 3-day avg after each day; flag days
// where the % change exceeds a threshold (sharp moves). Returns [{date,pct,dir}].
function detectChangePoints(fromD, toD, threshold){
 const sam=samSeries(); if(sam.length<11) return [];
 const inRange=sam.filter(p=>(!fromD||p.date>=fromD)&&(!toD||p.date<=toD)).sort((a,b)=>a.date.localeCompare(b.date));
 if(inRange.length<11) return [];
 const raw=inRange.map(p=>p.views), dates=inRange.map(p=>p.date);
 // 5-day moving average to suppress daily noise before detection
 const views=raw.map((_,i)=>{
  let s=0,c=0; for(let k=-2;k<=2;k++){const j=i+k; if(j>=0&&j<raw.length){s+=raw[j];c++;}}
  return s/c;
 });
 const cps=[];
 for(let i=5;i<views.length-4;i++){
  const before=(views[i-5]+views[i-4]+views[i-3])/3;
  const after=(views[i+2]+views[i+3]+views[i+4])/3;
  if(!before) continue;
  const pct=(after-before)/before*100;
  if(Math.abs(pct)>=threshold) cps.push({date:dates[i], pct, dir:pct<0?'-':'+', before:Math.round(before), after:Math.round(after)});
 }
 // Merge nearby change-points (within 10 days) keeping the largest-magnitude one
 const merged=[];
 cps.sort((a,b)=>a.date.localeCompare(b.date));
 for(const cp of cps){
  const last=merged[merged.length-1];
  if(last && Math.abs(new Date(cp.date)-new Date(last.date))<10*864e5){
   if(Math.abs(cp.pct)>Math.abs(last.pct)) merged[merged.length-1]=cp;
  } else merged.push(cp);
 }
 return merged;
}

// Verdict: % change of Samsung average views, comparison period vs current period
function trendVerdict(){
 // Needs all four dates (current + comparison)
 if(!(csd.value && ced.value && sd.value && ed.value)) return null;
 const sam=samSeries(); if(!sam.length) return null;
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
// Same idea as trendVerdict(), but for the competitor aggregate — lets us tell
// "market-wide" moves (competitors moved the same direction) apart from
// "samsung.com-only" moves (competitors didn't).
function compVerdict(){
 if(!(csd.value && ced.value && sd.value && ed.value)) return null;
 const names=compNames(); if(!names.length) return null;
 const avgSum=(from,to)=>{
  let total=0, any=false;
  names.forEach(n=>{
   const vals=wikiSeries(n).filter(p=>p.date>=from&&p.date<=to).map(p=>p.views);
   if(vals.length){ any=true; total+=vals.reduce((a,b)=>a+b,0)/vals.length; }
  });
  return any?total:null;
 };
 const baseAvg=avgSum(csd.value, ced.value);
 const curAvg=avgSum(sd.value, ed.value);
 if(baseAvg==null || curAvg==null || baseAvg===0) return null;
 const pct=(curAvg-baseAvg)/baseAvg*100;
 return {pct, dir: pct<0?'-':(pct>0?'+':'neutral')};
}
region.innerHTML=Object.keys(REGIONS).map((r,i)=>`<option value="${r}"${i===0?' selected':''}>${r==='ALL'?'전체':r}</option>`).join('');
function syncCountries(){const reg=REGIONS[region.value];
 const list=reg?COUNTRIES.filter(c=>c[0]==='ALL'||reg.includes(c[0])):COUNTRIES;
 country.innerHTML=list.map((c,i)=>`<option value="${c[0]}"${i===0?' selected':''}>${c[1]}</option>`).join('');}
syncCountries();
// When a country is picked, switch the region to that country's region
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
   // Rebuild the country list for the new region but keep the selection
   const reg=REGIONS[rk];
   const list=reg?COUNTRIES.filter(c=>c[0]==='ALL'||reg.includes(c[0])):COUNTRIES;
   country.innerHTML=list.map(c=>`<option value="${c[0]}"${c[0]===picked?' selected':''}>${c[1]}</option>`).join('');
  }
 }
 showAll=false; render();
}
function activeCountrySet(){if(country.value!=='ALL')return [country.value];const reg=REGIONS[region.value];return reg?reg:null;}
function rows(){let r=EV.slice();
 // Country/region: a specific value keeps events containing any of them; 'all' = no filter (union)
 const cs=activeCountrySet();
 if(cs){ r=r.filter(e=>{const sc=(e.scope||'').split(';');return cs.some(c=>sc.includes(c));}); }
 // Division: specific value = contains it; 'all' = no filter
 if(dv.value!=='ALL'){ r=r.filter(e=>(e.divisions||'').split(';').includes(dv.value)); }
 if(sd.value)r=r.filter(e=>(e.date||'')>=sd.value);
 if(ed.value)r=r.filter(e=>(e.date||'')<=ed.value);
 return r.sort((a,b)=>(b.date||'').localeCompare(a.date||''));}

// ---- trend graph ----
function wikiSeries(brand){return (WIKI.series&&WIKI.series[brand])||[];}

// ===== Uploaded real-traffic series (in-memory only, never persisted) =====
// CSV format: country,date,traffic (daily). Parsed in-browser; cleared on refresh.
let UPLOADED_TRAFFIC=null;  // {raw:[{country,date,traffic}], countries:Set}
// Aliases: map common CSV country codes to our internal codes.
// (UK -> GB; MX -> MX_C, since MX is reserved for the Apple division code.)
const COUNTRY_ALIAS={UK:'GB', MX:'MX_C', GBR:'GB', USA:'US', KOR:'KR'};
function _normCountry(c){
 const u=(c||'').trim().toUpperCase();
 return COUNTRY_ALIAS[u]||u;
}
function parseTrafficCSV(text){
 text=text.replace(/^\uFEFF/,'');  // strip BOM if present
 const lines=text.split(/\r?\n/).filter(l=>l.trim());
 if(!lines.length) return null;
 // detect header
 let start=0;
 const first=lines[0].toLowerCase();
 if(first.includes('date')||first.includes('날짜')||first.includes('country')||first.includes('국가')||first.includes('traffic')) start=1;
 const rows=[]; const countries=new Set();
 for(let i=start;i<lines.length;i++){
  const parts=lines[i].split(',').map(s=>s.trim());
  if(parts.length<3) continue;
  const country=_normCountry(parts[0]), date=parts[1], traffic=parts[2];
  const v=parseFloat(traffic.replace(/[^0-9.\-]/g,''));
  // normalize date to YYYY-MM-DD
  let d=date.replace(/\//g,'-');
  const m=d.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if(m) d=`${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
  if(!country||!d||isNaN(v)) continue;
  rows.push({country, date:d, traffic:v}); countries.add(country);
 }
 return rows.length?{raw:rows, countries}:null;
}
// Aggregate uploaded traffic for the currently selected country filter, as
// [{date,views}] so analysis code can treat it exactly like a wiki series.
function uploadedSeriesForFilter(){
 if(!UPLOADED_TRAFFIC) return null;
 const cv=country.value;  // 'ALL' or an internal country code (e.g. 'GB','MX_C')
 const byDate={};
 UPLOADED_TRAFFIC.raw.forEach(r=>{
  if(cv!=='ALL' && r.country!==cv) return;  // r.country already normalized to internal code
  byDate[r.date]=(byDate[r.date]||0)+r.traffic;
 });
 const out=Object.keys(byDate).sort().map(d=>({date:d, views:byDate[d]}));
 return out.length?out:null;
}
// Unified traffic source: uploaded real traffic if present, else wiki proxy.
function samSeries(){
 const up=uploadedSeriesForFilter();
 return up||wikiSeries("Samsung");
}
function trafficSourceLabel(){ return UPLOADED_TRAFFIC?'실제 트래픽(업로드)':'위키 조회수(대리지표)'; }
function compNames(){
 if(dv.value==='ALL'){
   const all=Object.values(DIV2COMP).flat();
   return all.filter((v,i)=>all.indexOf(v)===i);  // dedupe (LG appears in VD & DA)
 }
 return DIV2COMP[dv.value]||[];
}
function compLabel(){const n=compNames();return n.length>1?'경쟁사 합산':(n[0]||'');}
let chart;
// Custom plugin drawing event pins (circle body + tail + glowing anchor + connector)
const cpPlugin={
 id:'changepoints',
 afterDraw(c){
  const cps=(c._changePoints)||[]; if(!cps.length) return;
  const ctx=c.ctx, x=c.scales.x, y=c.scales.y;
  cps.forEach(cp=>{
   const px=x.getPixelForValue(cp.xIdx); if(px==null||isNaN(px)) return;
   const py=y.getPixelForValue(cp.after);
   const color=cp.dir==='-'?'#E24B4A':'#1D9E75';
   ctx.save();
   ctx.strokeStyle=color; ctx.setLineDash([4,3]); ctx.lineWidth=1.5;
   ctx.beginPath(); ctx.moveTo(px,y.top); ctx.lineTo(px,y.bottom); ctx.stroke();
   ctx.setLineDash([]);
   ctx.beginPath(); ctx.arc(px,py,6,0,Math.PI*2); ctx.fillStyle=color; ctx.fill();
   ctx.fillStyle='#fff'; ctx.beginPath(); ctx.arc(px,py,2.5,0,Math.PI*2); ctx.fill();
   ctx.fillStyle=color; ctx.font='600 11px sans-serif'; ctx.textAlign='center';
   ctx.fillText((cp.pct>=0?'+':'')+cp.pct.toFixed(0)+'%', px, y.top-4);
   ctx.restore();
  });
 }
};
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
// Clicking a pin scrolls to the matching numbered card and highlights it
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
 const upSeries=uploadedSeriesForFilter();  // real traffic for current country filter, or null
 const hasCmp=!!(csd.value && ced.value);
 // Instead of one long line spanning comparison-start..current-end (which could be
 // many months/years apart), show CURRENT and COMPARISON periods as two lines aligned
 // by relative day position (1일차, 2일차, ...) — this keeps the visible x-axis span
 // as short as a single period, and makes the two periods directly overlay-comparable.
 function datesInRange(from,to){
  return sam.map(p=>p.date).filter(dt=>(!from||dt>=from)&&(!to||dt<=to));
 }
 const curDates=datesInRange(sd.value, ed.value);
 const cmpDates=hasCmp?datesInRange(csd.value, ced.value):[];
 const N=Math.max(curDates.length, cmpDates.length, 1);
 const xLabels=Array.from({length:N},(_,i)=>i+1);
 const valAt=(dates,ser,i)=>{ if(i>=dates.length) return null; const f=ser.find(p=>p.date===dates[i]); return f?f.views:null; };
 const curData=xLabels.map((_,i)=>valAt(curDates,sam,i));
 const cmpData=hasCmp?xLabels.map((_,i)=>valAt(cmpDates,sam,i)):[];
 // Competitor total: current period only (kept as context; not duplicated for the
 // comparison period, to avoid an overly busy chart).
 const names=compNames();
 const total=xLabels.map((_,i)=>{
  if(i>=curDates.length) return 0;
  return names.reduce((s,n)=>{const ser=wikiSeries(n);const f=ser.find(p=>p.date===curDates[i]);return s+(f?f.views:0);},0);
 });
 // Uploaded real traffic, aligned the same way as Samsung wiki above.
 const upAt=(dates,i)=>{ if(!upSeries||i>=dates.length) return null; const f=upSeries.find(p=>p.date===dates[i]); return f?f.views:null; };
 const upCurData=xLabels.map((_,i)=>upAt(curDates,i));
 const upCmpData=hasCmp?xLabels.map((_,i)=>upAt(cmpDates,i)):[];
 const hasUpload=upSeries&&(upCurData.some(v=>v!=null)||upCmpData.some(v=>v!=null));
 // Change-points within the CURRENT period (sd~ed), threshold 8% (on active source)
 const changePoints=detectChangePoints(sd.value, ed.value, 8);
 window._changePoints=changePoints;  // real dates — used by render() for cause cards
 const chartChangePoints=changePoints.map(cp=>{
  let xIdx=null; for(let k=0;k<curDates.length;k++){ if(curDates[k]<=cp.date) xIdx=xLabels[k]; }
  return Object.assign({},cp,{xIdx});
 });
 const dataMax=Math.max(1,...curData.filter(v=>v!=null),...cmpData.filter(v=>v!=null));
 const yMax=Math.ceil(dataMax*1.25/1000)*1000;
 const compMax=Math.max(1,...total);
 const compYMax=Math.ceil(compMax*1.25/1000)*1000;
 // Format a YYYY-MM-DD date as "7/7" for x-axis ticks (current-period date at
 // that index; the comparison line's own real date still shows in tooltips).
 const fmtMD=(d)=>{ if(!d) return ''; const p=d.split('-'); return `${+p[1]}/${+p[2]}`; };
 // Pins: map each CURRENT-period event to its day-index on the 현재 기간 line
 const pins=[];
 evSortedAsc.forEach((e)=>{
  if(!curDates.length || e.date<curDates[0] || e.date>curDates[curDates.length-1]) return;
  let nearIdx=0; for(let k=0;k<curDates.length;k++){ if(curDates[k]<=e.date) nearIdx=k; }
  const sv=curData[nearIdx];
  pins.push({n:(numByDate&&numByDate[e.date])||'',xLabel:xLabels[nearIdx],anchorY:sv==null?0:sv,color:DIRC[e.impact_direction]||'#999'});
 });
 document.getElementById('legend').innerHTML=
  `<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:2px;background:#1428A0;display:inline-block"></span>Samsung 현재 기간</span>`+
  (hasCmp?`<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:2px;border-top:2px dashed #9a9a96;display:inline-block"></span>Samsung 비교 기간</span>`:'')+
  `<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:2px;background:#D9A441;display:inline-block"></span>${compLabel()} (현재)</span>`+
  (hasUpload?`<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:2px;background:#D0392B;display:inline-block"></span>실제 트래픽(현재)</span>`:'')+
  (hasUpload&&hasCmp?`<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:2px;border-top:2px dashed #D0392B;display:inline-block"></span>실제 트래픽(비교)</span>`:'');
 document.getElementById('tsub').textContent=hasCmp?`(현재·비교 기간을 일자 기준 나란히 비교, 각 ${N}일)`:`(현재 기간, ${N}일)`;
 if(chart)chart.destroy();
 const dsets=[
   {label:'Samsung 현재 기간',data:curData,borderColor:'#1428A0',backgroundColor:'#1428A014',tension:0.35,pointRadius:0,borderWidth:2.5,spanGaps:true,yAxisID:'y'}];
 if(hasCmp){
   dsets.push({label:'Samsung 비교 기간',data:cmpData,borderColor:'#9a9a96',backgroundColor:'transparent',tension:0.35,pointRadius:0,borderWidth:2,borderDash:[5,4],spanGaps:true,yAxisID:'y'});
 }
 dsets.push({label:compLabel()+' (현재)',data:total,borderColor:'#D9A441',backgroundColor:'#D9A44114',tension:0.35,pointRadius:0,borderWidth:2,yAxisID:'yComp'});
 if(hasUpload){
   dsets.push({label:'실제 트래픽(현재)',data:upCurData,borderColor:'#D0392B',backgroundColor:'#D0392B12',
     tension:0.35,pointRadius:0,borderWidth:2.5,spanGaps:true,yAxisID:'yUpload'});
   if(hasCmp){
     dsets.push({label:'실제 트래픽(비교)',data:upCmpData,borderColor:'#D0392B',backgroundColor:'transparent',
       tension:0.35,pointRadius:0,borderWidth:2,borderDash:[5,4],spanGaps:true,yAxisID:'yUpload'});
   }
 }
 chart=new Chart(document.getElementById('trend'),{type:'line',
  data:{labels:xLabels,datasets:dsets},
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
     tooltip:{callbacks:{
       title:(items)=>(items[0]?items[0].label+'일차':''),
       label:(c)=>{
         const i=c.dataIndex; const lbl=c.dataset.label;
         const isCmp=lbl.indexOf('비교')>=0;
         const d=isCmp?(cmpDates[i]||''):(curDates[i]||'');
         return `${lbl}${d?' ('+d+')':''}: ${(c.parsed.y||0).toLocaleString()}회`;
       }}}},
   scales:{x:{ticks:{color:'#888780',font:{size:11},maxTicksLimit:8,callback:(v,i)=>fmtMD(curDates[i])},grid:{display:false}},
     y:{suggestedMax:yMax,ticks:{color:'#888780',font:{size:11},callback:v=>(v/1000)+'k'},grid:{color:'rgba(136,135,128,0.10)'}},
     yComp:{display:true,position:'right',suggestedMax:compYMax,ticks:{color:'#D9A441',font:{size:10},callback:v=>(v/1000)+'k'},grid:{display:false},title:{display:true,text:compLabel(),color:'#D9A441',font:{size:10}}},
     yUpload:{display:hasUpload,position:'right',ticks:{color:'#D0392B',font:{size:10},callback:v=>(v/1000)+'k'},grid:{display:false},title:{display:true,text:'실제 트래픽',color:'#D0392B',font:{size:10}}}}},
  plugins:[pinPlugin,cpPlugin]});
 chart._pins=pins; chart._changePoints=chartChangePoints; chart.update();
}



// ===== 3-axis diagnosis (demand / share / supply) =====
// Decomposition frame: organic-traffic change = demand shift (how much the
// whole topic space is searched) x share shift (samsung.com's slice of it)
// x supply shift (indexing/site issues). Each event gets ONE primary axis so
// a drop can be triaged: demand -> market-wide causes, share -> competitor/
// search-result causes, supply -> crawl/site causes.
const AXIS_KO={demand:'수요',share:'점유',supply:'공급'};
const AXIS_COLOR={demand:'#185FA5',share:'#534AB7',supply:'#8a6d1a'};
const SUPPLY_KW=['인덱싱','크롤링','indexing','crawling','다운타임','downtime','장애','outage','core web vitals','사이트 속도','robots.txt','sitemap'];
const OWN_KW=['samsung','galaxy','삼성','갤럭시'];
// Named-rival mentions — the signal that a platform/AI/marketing-category
// event is actually a SHARE-axis event (redistributes visibility/traffic
// between Samsung and a specific competitor) rather than a market-wide shift
// that touches everyone's traffic equally (DEMAND-axis). E.g. "Google AI
// Overviews now answer 60% of queries" cuts click-through for the whole web,
// not just samsung.com vs named rivals -> demand. "Apple's AI feature launch
// draws comparison-shopping traffic away from samsung.com" -> share.
const COMPETITOR_KW=['apple','xiaomi','vivo','oppo','lg','tcl','hisense','whirlpool','bosch',
  '아이폰','애플','샤오미','비보','오포','엘지','보쉬'];
function axisOf(e){
 const t=((e.title||'')+' '+(e.impact||'')+' '+(e.description||'')).toLowerCase();
 if(SUPPLY_KW.some(k=>t.includes(k))) return 'supply';
 const c=e.category;
 if(c==='platform'||c==='AI'||c==='marketing')
  return COMPETITOR_KW.some(k=>t.includes(k)) ? 'share' : 'demand';
 // company: Samsung's own launches drive demand; competitor moves contest share
 if(c==='company') return OWN_KW.some(k=>t.includes(k))?'demand':'share';
 return 'demand'; // economy, holiday, culture, social_issue, geopolitics, regulation
}
function _wikiMaps(names){
 return names.map(n=>{const m={};wikiSeries(n).forEach(q=>m[q.date]=q.views);return m;});
}
// Whole-market attention: Samsung + selected-division competitors, summed per day
function marketTotalSeries(){
 const maps=_wikiMaps(compNames());
 return wikiSeries('Samsung').map(p=>({date:p.date,views:maps.reduce((s,m)=>s+(m[p.date]||0),p.views)}));
}
// Samsung's share of that attention, as a % per day
function shareSeries(){
 const maps=_wikiMaps(compNames());
 return wikiSeries('Samsung').map(p=>{
  const tot=maps.reduce((s,m)=>s+(m[p.date]||0),p.views);
  return {date:p.date,views:tot?p.views/tot*100:null};
 }).filter(p=>p.views!=null);
}
function avgInRange(ser,from,to){
 const vals=ser.filter(p=>(!from||p.date>=from)&&(!to||p.date<=to)).map(p=>p.views);
 return vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:null;
}
let axisCharts=[];
// Expand/collapse an axis card's full event list and bring the card into view
function toggleAxisList(axis){
 const el=document.getElementById('axis-full-'+axis);
 if(el) el.style.display = el.style.display==='none' ? 'block' : 'none';
 const card=document.getElementById('axis-card-'+axis);
 if(card) card.scrollIntoView({behavior:'smooth',block:'center'});
}
function renderAxisPanel(r,vd,numByDate){
 const panel=document.getElementById('axisPanel');
 if(!(csd.value&&ced.value&&sd.value&&ed.value)){panel.style.display='none';return;}
 axisCharts.forEach(c=>c.destroy()); axisCharts=[];
 const mkt=marketTotalSeries(), shr=shareSeries();
 const dCur=avgInRange(mkt,sd.value,ed.value), dCmp=avgInRange(mkt,csd.value,ced.value);
 const sCur=avgInRange(shr,sd.value,ed.value), sCmp=avgInRange(shr,csd.value,ced.value);
 const dPct=(dCur!=null&&dCmp)?(dCur-dCmp)/dCmp*100:null;
 const sPpt=(sCur!=null&&sCmp!=null)?(sCur-sCmp):null;
 const inCur=e=>(!sd.value||(e.date||'')>=sd.value)&&(!ed.value||(e.date||'')<=ed.value);
 const byAxis={demand:[],share:[],supply:[]};
 r.filter(inCur).forEach(e=>byAxis[axisOf(e)].push(e));
 const lcpSer=((CRUX.metrics||{}).lcp_ms)||[];
 const inpSer=((CRUX.metrics||{}).inp_ms)||[];
 const clsSer=((CRUX.metrics||{}).cls)||[];

 // ---- Attribution: split the total change into axis contribution shares ----
 // Identity: Samsung attention = market total x Samsung's share, so in log
 // space log(S ratio) = log(M ratio) + log(share ratio) EXACTLY. Therefore
 // demand frac = gM/gS and share frac = 1 - demand frac — an accounting
 // identity, not an estimate. Supply sits OUTSIDE the identity (the wiki
 // proxy can't see site health), so when CrUX shows a period-over-period
 // LCP regression beyond 10%, a heuristic slice (1%p of weight per 1% of
 // regression beyond 10%, capped at 25%) is carved out on down-moves and
 // demand/share are scaled down proportionally.
 let attr=null;
 if(vd && Math.abs(vd.pct)>=1 && dCur!=null && dCmp && sCur!=null && sCmp){
  const gS=Math.log(1+vd.pct/100), gM=Math.log(dCur/dCmp);
  if(Math.abs(gS)>1e-6){
   let fD=gM/gS, fSh=1-fD, fSu=0, lcpDelta=null;
   const lcpAsViews=lcpSer.map(p=>({date:p.date,views:p.p75}));
   const lCur=avgInRange(lcpAsViews,sd.value,ed.value), lCmp=avgInRange(lcpAsViews,csd.value,ced.value);
   if(lCur!=null&&lCmp){
    lcpDelta=(lCur-lCmp)/lCmp*100;
    if(lcpDelta>10 && vd.dir==='-'){ fSu=Math.min(0.25,(lcpDelta-10)/100); fD*=(1-fSu); fSh*=(1-fSu); }
   }
   attr={fD,fSh,fSu,lcpDelta};
  }
 }

 // Qualitative reading (kept as the headline sentence above the bar)
 const D_SIG=2.0, S_SIG=0.5; // thresholds: % for demand, %p for share
 let summary;
 if(!vd||vd.dir==='neutral'){
  summary='Samsung 관심량 변화가 미미해 축별 원인 진단은 참고용입니다.';
 } else {
  const word=vd.dir==='-'?'하락':'상승';
  const dHit=dPct!=null&&(vd.dir==='-'?dPct<=-D_SIG:dPct>=D_SIG);
  const sHit=sPpt!=null&&(vd.dir==='-'?sPpt<=-S_SIG:sPpt>=S_SIG);
  if(dHit&&sHit) summary=`<strong>수요·점유 동시 ${word}</strong> — 시장 전체 관심과 삼성 몫이 함께 움직였습니다.`;
  else if(dHit) summary=`<strong>수요 축 우세</strong> — 시장 전체 관심이 ${word}했고 삼성 몫은 크게 변하지 않았습니다.`;
  else if(sHit) summary=`<strong>점유 축 우세</strong> — 시장 전체 관심은 비슷한데 삼성이 가져가는 몫이 ${word}했습니다.`;
  else summary=`수요·점유 모두 뚜렷한 변화가 없습니다 — 공급 축 신호와 대리지표의 한계를 함께 확인하세요.`;
  if(byAxis.supply.length) summary+=` <span style="color:#8a6d1a">공급측 신호 ${byAxis.supply.length}건 감지.</span>`;
 }
 const fmtSigned=(v,unit,dec)=>v==null?'—':`${v>=0?'+':''}${v.toFixed(dec)}${unit}`;
 // Contribution bar: one clickable segment per axis, width = |frac| share
 let barHtml='';
 if(attr){
  const segs=[['demand',attr.fD],['share',attr.fSh],['supply',attr.fSu]].filter(s=>Math.abs(s[1])>0.005);
  const totW=segs.reduce((a,s)=>a+Math.abs(s[1]),0)||1;
  const anyOff=segs.some(s=>s[1]<0);
  barHtml=`<div style="display:flex;align-items:baseline;gap:10px;margin-top:10px">
    <span style="font-size:20px;font-weight:600;color:${vd.pct<0?'var(--neg)':'var(--pos)'}">${fmtSigned(vd.pct,'%',1)}</span>
    <span style="font-size:12px;color:var(--muted)">전체 변화의 축별 기여</span></div>
   <div style="display:flex;height:30px;border-radius:9px;overflow:hidden;margin-top:6px">`+
   segs.map(([ax,f])=>{
    const w=Math.abs(f)/totW*100, off=f<0;
    return `<div onclick="toggleAxisList('${ax}')" title="${AXIS_KO[ax]} 축 요인 펼쳐보기" style="width:${w.toFixed(1)}%;background:${AXIS_COLOR[ax]}${off?'55':''};display:flex;align-items:center;justify-content:center;gap:4px;font-size:11px;color:#fff;font-weight:600;cursor:pointer;overflow:hidden;white-space:nowrap">${AXIS_KO[ax]} ${(f*100).toFixed(0)}%${off?' 상쇄':''}</div>`;
   }).join('')+`</div>
   <div style="font-size:11px;color:#9aa0a6;margin-top:5px">수요·점유 배분은 로그 분해 항등식(삼성 관심량=시장 전체×점유율)으로 계산한 정확한 회계 분해${attr.fSu>0?' · 공급은 CrUX 성능 회귀 크기 기반 휴리스틱':''}${anyOff?' · "상쇄"=전체 방향과 반대로 작용한 축':''} · 막대 클릭 시 해당 축 요인 목록으로 이동</div>`;
 } else if(vd && Math.abs(vd.pct)>=1){
  barHtml=`<div style="font-size:11px;color:#9aa0a6;margin-top:8px">축별 기여도 계산 불가 — 시장(경쟁사) 시계열이 두 기간을 모두 덮지 못합니다.</div>`;
 }
 document.getElementById('axisSummary').innerHTML=summary+barHtml;

 // Per-axis event lists: top 3 visible, rest expandable (deep-dive)
 const wOf=e=>Math.max(1,Math.min(5,+e.impact_strength||2))*(CONFW[e.confidence]||1);
 const evItem=(e)=>{
  const n=numByDate[e.date]||0;
  return `<div style="padding:7px 0;border-top:1px dashed var(--line);font-size:12px">
    <div style="display:flex;justify-content:space-between;gap:6px">
     <span style="cursor:pointer;font-weight:500" onclick="scrollToCard(${n})">${e.title}</span>
     <span style="color:var(--muted);white-space:nowrap">${e.date||''}</span></div>
    ${e.impact?`<div style="color:var(--muted);margin-top:2px">${e.impact}</div>`:''}
    <div style="margin-top:3px"><span class="cp-tag">영향강도 ${Math.max(1,Math.min(5,+e.impact_strength||2))}/5</span><span class="cp-tag">신뢰도 ${e.confidence||'-'}</span></div>
  </div>`;
 };
 const evList=(axis)=>{
  const items=byAxis[axis].slice().sort((a,b)=>wOf(b)-wOf(a));
  if(!items.length) return `<div style="font-size:12px;color:var(--muted);padding:6px 0">이 기간 ${AXIS_KO[axis]} 축 이벤트 없음</div>`;
  const top=items.slice(0,3), rest=items.slice(3);
  return top.map(evItem).join('')+
   `<div id="axis-full-${axis}" style="display:none">${rest.map(evItem).join('')}</div>`+
   (rest.length?`<div style="padding:6px 0;border-top:1px dashed var(--line)"><span style="font-size:11px;color:var(--blue);cursor:pointer;font-weight:500" onclick="toggleAxisList('${axis}')">외 ${rest.length}건 펼치기/접기</span></div>`:'');
 };
 const spark=(id)=>`<div style="height:56px;margin:8px 0"><canvas id="${id}"></canvas></div>`;
 // Big number per card: contribution share when attributable, raw metric otherwise
 const bigOf=(frac,fallback)=>attr?`기여 ${(frac*100).toFixed(0)}%${frac<0?' (상쇄)':''}`:fallback;
 // Supply quantitative signal: CrUX real-user CWV (weekly, 28-day rolling —
 // a slow regression detector, not a day-of incident detector)
 let supplyQuant;
 if(lcpSer.length>=3){
  const latest=lcpSer[lcpSer.length-1].p75;
  const prev=lcpSer.slice(-9,-1).map(p=>p.p75).sort((a,b)=>a-b);
  const med=prev.length?prev[Math.floor(prev.length/2)]:null;
  const dPctL=med?(latest-med)/med*100:null;
  // CWV thresholds: LCP good <=2.5s, poor >4s
  const lcpCol=latest<=2500?'var(--pos)':(latest>4000?'var(--neg)':'#8a6d1a');
  const worse=dPctL!=null&&dPctL>10;
  const chips=[inpSer.length?`INP ${Math.round(inpSer[inpSer.length-1].p75)}ms`:'',
               clsSer.length?`CLS ${clsSer[clsSer.length-1].p75.toFixed(2)}`:''].filter(Boolean).join(' · ');
  supplyQuant=`<div style="font-size:21px;font-weight:600;color:${AXIS_COLOR.supply}">${bigOf(attr?attr.fSu:0,`LCP ${(latest/1000).toFixed(2)}s`)}</div>
   <div style="font-size:11px;color:${worse?'var(--neg)':'var(--muted)'}">LCP ${(latest/1000).toFixed(2)}s <span style="color:${lcpCol}">●</span> 모바일 p75, 8주 중앙값 대비 ${dPctL==null?'—':(dPctL>=0?'+':'')+dPctL.toFixed(1)+'%'}${worse?' ⚠ 성능 회귀 의심':''}${chips?' · '+chips:''}</div>
   ${spark('axis-spark-supply')}`;
 } else {
  supplyQuant=`<div style="font-size:21px;font-weight:600;color:${attr?AXIS_COLOR.supply:'var(--muted)'}">${bigOf(attr?attr.fSu:0,byAxis.supply.length+'건')}</div>
   <div style="font-size:11px;color:var(--muted)">${attr?'CrUX 미연동 — 성능 신호 없이 0%로 처리':'이 기간 감지된 공급측 이벤트'}</div>
   <div style="height:56px;margin:8px 0;display:flex;align-items:center;font-size:11px;color:#9aa0a6">CrUX 미연동 — CRUX_API_KEY 등록 시 실사용자 성능(CWV) 시리즈가 표시됩니다</div>`;
 }
 document.getElementById('axisCards').innerHTML=
  `<div id="axis-card-demand" style="border:1px solid var(--line);border-left:3px solid ${AXIS_COLOR.demand};border-radius:10px;padding:12px 14px">
    <div style="font-size:12px;font-weight:600;color:${AXIS_COLOR.demand}">수요 — 시장 전체 관심</div>
    <div style="font-size:21px;font-weight:600;color:${AXIS_COLOR.demand}">${bigOf(attr?attr.fD:0,fmtSigned(dPct,'%',1))}</div>
    <div style="font-size:11px;color:var(--muted)">관심량 ${fmtSigned(dPct,'%',1)} (삼성+경쟁사 합, 비교 기간 대비)</div>
    ${spark('axis-spark-demand')}${evList('demand')}</div>`+
  `<div id="axis-card-share" style="border:1px solid var(--line);border-left:3px solid ${AXIS_COLOR.share};border-radius:10px;padding:12px 14px">
    <div style="font-size:12px;font-weight:600;color:${AXIS_COLOR.share}">점유 — 삼성이 가져가는 몫</div>
    <div style="font-size:21px;font-weight:600;color:${AXIS_COLOR.share}">${bigOf(attr?attr.fSh:0,fmtSigned(sPpt,'%p',2))}</div>
    <div style="font-size:11px;color:var(--muted)">몫 ${fmtSigned(sPpt,'%p',2)} (현재 ${sCur==null?'—':sCur.toFixed(1)+'%'} · 비교 ${sCmp==null?'—':sCmp.toFixed(1)+'%'})</div>
    ${spark('axis-spark-share')}${evList('share')}</div>`+
  `<div id="axis-card-supply" style="border:1px solid var(--line);border-left:3px solid ${AXIS_COLOR.supply};border-radius:10px;padding:12px 14px">
    <div style="font-size:12px;font-weight:600;color:${AXIS_COLOR.supply}">공급 — 사이트 성능·인덱싱 신호</div>
    ${supplyQuant}
    <div style="font-size:11px;color:var(--muted);margin-bottom:2px">공급측 이벤트 ${byAxis.supply.length}건 (Google Search Status 등)</div>
    ${evList('supply')}</div>`;
 // Sparklines for the two quantitative axes, current period only
 const mkSpark=(id,ser,unit)=>{
  const pts=ser.filter(p=>(!sd.value||p.date>=sd.value)&&(!ed.value||p.date<=ed.value));
  const el=document.getElementById(id);
  if(!el||pts.length<5){ if(el)el.parentNode.style.display='none'; return; }
  axisCharts.push(new Chart(el,{type:'line',
   data:{labels:pts.map(p=>p.date),datasets:[{data:pts.map(p=>p.views),
     borderColor:AXIS_COLOR[id.includes('demand')?'demand':'share'],borderWidth:1.5,pointRadius:0,tension:0.35,fill:false}]},
   options:{responsive:true,maintainAspectRatio:false,
    plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${c.parsed.y.toFixed(unit==='%'?1:0)}${unit==='%'?'%':'회'}`}}},
    scales:{x:{display:false},y:{display:false}}}}));
 };
 mkSpark('axis-spark-demand',mkt,'');
 mkSpark('axis-spark-share',shr,'%');
 // Supply sparkline: always the last 26 weeks regardless of the selected
 // period — CrUX's 28-day rolling window makes short-period slicing useless
 if(lcpSer.length>=3){
  const pts=lcpSer.slice(-26);
  const el=document.getElementById('axis-spark-supply');
  if(el) axisCharts.push(new Chart(el,{type:'line',
   data:{labels:pts.map(p=>p.date),datasets:[{data:pts.map(p=>p.p75),
     borderColor:AXIS_COLOR.supply,borderWidth:1.5,pointRadius:0,tension:0.35,fill:false}]},
   options:{responsive:true,maintainAspectRatio:false,
    plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`LCP p75 ${(c.parsed.y/1000).toFixed(2)}s`}}},
    scales:{x:{display:false},y:{display:false}}}}));
 }
 panel.style.display='block';
}

function render(){
 let r=rows();  // result after all active filters (region/country/division/KPI/period)
 // With a verdict: trend-direction factors first, others still shown by confidence (neutral last)
 const vd=trendVerdict();
 const vbox=document.getElementById('verdict');
 const confRank=e=>CONFW[e.confidence]||0;
 if(vd && vd.dir!=='neutral'){
  // Sort: (1) same direction as trend (2) confidence high->low (3) neutral last within a tier (4) newest
  const dirMatch=e=> e.impact_direction===vd.dir ? 0 : (e.impact_direction==='neutral'?2:1);
  r.sort((a,b)=>
    dirMatch(a)-dirMatch(b)
    || confRank(b)-confRank(a)
    || ((a.impact_direction==='neutral'?1:0)-(b.impact_direction==='neutral'?1:0))
    || (b.date||'').localeCompare(a.date||''));
  const vc=vd.dir==='-'?'#E24B4A':'#1D9E75';
  const arrow=vd.dir==='-'?'▼':'▲';
  const dirWord=vd.dir==='-'?'하락':'상승';
  const cv=compVerdict();
  let marketLabel;
  if(!cv){
    marketLabel=`${compLabel()} 비교 데이터 없음`;
  } else if(cv.dir==='neutral'){
    marketLabel=`${compLabel()} 변화 미미 → Samsung.com 단독 ${dirWord}`;
  } else if(cv.dir===vd.dir){
    marketLabel=`${compLabel()}도 동반 ${dirWord} → 시장 전체 ${dirWord}`;
  } else {
    marketLabel=`${compLabel()}는 반대 방향 → Samsung.com 단독 ${dirWord}`;
  }
  vbox.style.display='block'; vbox.style.background=vc+'14'; vbox.style.border='1px solid '+vc+'44';
  // Market number = competitor aggregate's own % change (cv.pct), separate
  // from marketLabel's qualitative same-direction/opposite-direction read.
  const cvArrow=cv?(cv.dir==='-'?'▼':(cv.dir==='+'?'▲':'―')):'';
  const cvColor=cv?(cv.dir==='-'?'#E24B4A':(cv.dir==='+'?'#1D9E75':'#9a9a96')):'';
  const marketNum=cv?` · <span style="color:${cvColor};font-weight:600">Market ${cvArrow} ${cv.pct.toFixed(1)}%</span>`:'';
  vbox.innerHTML=`<span style="color:${vc};font-weight:600">Samsung ${arrow} ${vd.pct.toFixed(1)}%</span>${marketNum} · <span style="color:var(--muted)">${marketLabel}</span>`;
 } else if(vd){
  // Negligible change: sort by confidence (neutral last)
  r.sort((a,b)=> confRank(b)-confRank(a) || ((a.impact_direction==='neutral'?1:0)-(b.impact_direction==='neutral'?1:0)) || (b.date||'').localeCompare(a.date||''));
  vbox.style.display='block'; vbox.style.background='var(--bg)'; vbox.style.border='1px solid var(--line)';
  vbox.innerHTML=`<span style="color:var(--muted)">Samsung 변화 미미(${vd.pct.toFixed(1)}%) — 신뢰도순 정렬</span>`;
 } else { vbox.style.display='none'; }

 const numByDate={}; r.forEach((e,i)=>{ if(!(e.date in numByDate)) numByDate[e.date]=i+1; });

 // ===== Cause analysis: change-point view + period-attribution view =====
 const anaBox=document.getElementById('analysis');
 const tbox=document.getElementById('topfactors');
 tbox.style.display='none';  // replaced by the analysis section
 const sam=samSeries();
 const samMap={}; sam.forEach(p=>samMap[p.date]=p.views);
 const samDates=sam.map(p=>p.date).sort();
 function postEventChange(dateStr){
  if(!dateStr || !samDates.length) return null;
  const idx=samDates.findIndex(d=>d>=dateStr);
  if(idx<0) return null;
  const before=[], after=[];
  for(let k=1;k<=3;k++){ const bi=idx-k; if(bi>=0) before.push(samMap[samDates[bi]]); }
  for(let k=0;k<3;k++){ const ai=idx+k; if(ai<samDates.length) after.push(samMap[samDates[ai]]); }
  if(!before.length || !after.length) return null;
  const bAvg=before.reduce((a,b)=>a+b,0)/before.length;
  const aAvg=after.reduce((a,b)=>a+b,0)/after.length;
  return bAvg? (aAvg-bAvg)/bAvg*100 : null;
 }
 const inCur=e=>(!sd.value||(e.date||'')>=sd.value)&&(!ed.value||(e.date||'')<=ed.value);
 const CONFNORM={high:1.0, med:0.66, low:0.33};
 const STRENGTH=e=>Math.max(1,Math.min(5,+e.impact_strength||2));

 // ---- Change-points (computed; folded into period attribution below) ----
 const cps=(window._changePoints)||[];
 // For an event, find a change-point within 7 days AFTER the event (same direction)
 function linkedChangePoint(e){
  const ed2=new Date(e.date);
  let best=null;
  cps.forEach(cp=>{
   if(cp.dir!==e.impact_direction) return;
   const gap=(new Date(cp.date)-ed2)/864e5;
   if(gap>=0 && gap<=7){ if(!best||gap<best.gap) best={cp,gap}; }
  });
  return best;
 }

 // ---- Period attribution: why current vs comparison, with clickable groups ----
 let perHtml='';
 if(vd && vd.dir!=='neutral'){
  const vc=vd.dir==='-'?'#D0392B':'#137a52';
  const dirWord=vd.dir==='-'?'감소':'증가';
  const active=r.filter(e=>e.impact_direction===vd.dir && inCur(e));
  const CATKO={competitor:'경쟁',company:'경쟁',economy:'경제',geopolitics:'지정학',
    social_issue:'사회',marketing:'마케팅',platform:'AI·플랫폼',ai:'AI·플랫폼',regulation:'규제',culture:'문화',other:'기타'};
  const groups={};
  active.forEach(e=>{
   const cat=CATKO[e.category]||'기타';
   const w=STRENGTH(e)*(CONFNORM[e.confidence]||0.5);
   groups[cat]=groups[cat]||{w:0,items:[]};
   groups[cat].w+=w; groups[cat].items.push(e);
  });
  const totalW=Object.values(groups).reduce((a,g)=>a+g.w,0)||1;
  const totalPct=Math.abs(vd.pct);
  const ranked=Object.entries(groups).map(([cat,g])=>({cat,...g,
    share:g.w/totalW, ppt:(g.w/totalW)*totalPct})).sort((a,b)=>b.w-a.w);
  const palette=['#E24B4A','#EF9F27','#534AB7','#185FA5','#1D9E75','#888780'];
  // change-point summary line (folded in)
  const cpNote = cps.length
    ? `이 기간 내 급변점 ${cps.length}곳 감지 — 아래 그룹을 펼치면 관련 요인에 연결 표시됩니다.`
    : `이 기간 내 뚜렷한 급변점(±8%)은 없습니다 — 완만한 누적 변화로 보입니다.`;
  if(ranked.length){
   const barSeg=ranked.map((g,i)=>`<div style="width:${(g.share*100).toFixed(1)}%;background:${palette[i%palette.length]};display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;font-weight:500;overflow:hidden;white-space:nowrap">${g.cat} ${vd.dir}${g.ppt.toFixed(1)}%p</div>`).join('');
   perHtml=`<div class="cp-card">
     <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:4px">
       <span style="font-size:22px;font-weight:600;color:${vc}">${(vd.pct>=0?'+':'')+vd.pct.toFixed(1)}%</span>
       <span style="font-size:14px;font-weight:500">현재 기간 트래픽, 비교 기간 대비 ${dirWord}</span></div>
     <div style="font-size:12px;color:var(--muted);margin-bottom:4px">현재 ${vd.curFrom}~${vd.curTo} · 비교 ${vd.baseFrom}~${vd.baseTo} · 주요 사유는 ${ranked[0].cat}</div>
     <div style="font-size:11px;color:var(--muted);margin-bottom:14px"><i class="ti ti-activity" style="vertical-align:-2px"></i> ${cpNote}</div>
     <div style="font-size:12px;color:var(--muted);margin-bottom:8px">요인별 기여도 (추정) · 그룹을 클릭하면 하위 요인이 펼쳐집니다</div>
     <div style="display:flex;height:28px;border-radius:9px;overflow:hidden;margin-bottom:6px">${barSeg}</div>
     <div style="font-size:11px;color:#9aa0a6;margin-bottom:16px">전체 ${vd.dir}${totalPct.toFixed(1)}%p를 활성 요인의 영향강도·신뢰도로 비례 배분한 추정</div>
     ${ranked.map((g,i)=>{
        const col=palette[i%palette.length];
        const sub=g.items.sort((a,b)=>STRENGTH(b)-STRENGTH(a)).map(e=>{
          const n=numByDate[e.date]||'';
          const link=linkedChangePoint(e);
          const cpTag=link?`<span class="cp-tag" style="color:${vc};background:${vc}14">${link.cp.date} 급변(${(link.cp.pct>=0?'+':'')+link.cp.pct.toFixed(0)}%)과 연결</span>`:'';
          return `<div style="padding:8px 0;border-top:1px solid var(--line)">
            <div style="display:flex;justify-content:space-between;gap:8px">
              <span style="font-size:13px;font-weight:600;cursor:pointer" onclick="scrollToCard(${n})">${e.title}</span>
              <span style="font-size:11px;color:var(--muted);white-space:nowrap">${e.date||''}</span></div>
            <div style="font-size:12px;color:var(--muted);margin:3px 0 5px">${e.impact||''}</div>
            <div><span class="cp-tag">영향강도 ${STRENGTH(e)}/5</span><span class="cp-tag">신뢰도 ${e.confidence||'-'}</span>${cpTag}</div>
          </div>`;}).join('');
        return `<div class="grp" style="border:1px solid var(--line);border-left:3px solid ${col};border-radius:0;margin-bottom:8px">
          <div class="grp-head" style="display:flex;justify-content:space-between;align-items:center;padding:11px 14px;cursor:pointer" onclick="this.parentNode.querySelector('.grp-body').style.display=this.parentNode.querySelector('.grp-body').style.display==='none'?'block':'none';this.querySelector('.grp-chev').style.transform=this.querySelector('.grp-chev').style.transform==='rotate(90deg)'?'':'rotate(90deg)'">
            <span style="font-size:13px;font-weight:600"><span class="grp-chev" style="display:inline-block;transition:transform .15s">▸</span> ${g.cat} (약 ${vd.dir}${g.ppt.toFixed(1)}%p)</span>
            <span style="font-size:11px;color:var(--muted)">활성 요인 ${g.items.length}건</span></div>
          <div class="grp-body" style="display:none;padding:0 14px 10px">${sub}</div>
        </div>`;}).join('')}
     <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--line);font-size:11px;color:var(--muted);line-height:1.6">기여도는 해당 기간 활성 요인의 영향강도·신뢰도로 비례 배분한 추정입니다. "급변과 연결"은 그 요인 발생 직후 7일 내 트래픽 급변점이 있었음을 뜻합니다. 인과 입증이 아니며, 위키 대리지표(또는 업로드 트래픽) 기준입니다.<br>영향강도: 이 요인이 samsung.com 트래픽에 주는 영향의 크기(1~5) · 신뢰도: 그 영향 판단이 맞다고 보는 확신 정도(high/med/low)</div>
   </div>`;
  } else {
   perHtml=`<div class="cp-card"><div style="font-size:13px;color:var(--muted)">비교 기간 대비 ${dirWord}했으나, 현재 기간 내 방향이 일치하는 외부 요인이 수집되지 않았습니다.</div></div>`;
  }
 } else if(vd){
  perHtml=`<div class="cp-card"><div style="font-size:13px;color:var(--muted)">비교 기간 대비 변화가 미미합니다(${vd.pct.toFixed(1)}%).</div></div>`;
 } else {
  perHtml=`<div class="cp-card"><div style="font-size:13px;color:var(--muted)">기간 비교를 위해 현재·비교 기간이 모두 필요합니다. 기간 선택기에서 비교 방식을 골라주세요.</div></div>`;
 }
 document.getElementById('ana-period').innerHTML=perHtml;
 anaBox.style.display='block';

 const evAsc=r.slice().sort((a,b)=>(a.date||'').localeCompare(b.date||''));
 drawTrend(evAsc, numByDate);
 renderAxisPanel(r, vd, numByDate);

 const neg=r.filter(x=>x.impact_direction==='-').length;
 const scopeLabel=country.value!=='ALL'?(COUNTRIES.find(c=>c[0]===country.value)||['','전체'])[1]:(region.value!=='ALL'?region.value:'전체');
 document.getElementById('cards').innerHTML=
  `<div class="card"><div class="lbl">전체 이벤트</div><div class="val">${r.length}</div></div>`+
  `<div class="card"><div class="lbl">negative</div><div class="val" style="color:var(--neg)">${neg}</div></div>`+
  `<div class="card"><div class="lbl">대상</div><div class="val" style="font-size:18px">${scopeLabel}</div></div>`;
 // Top 10 + "show more"
 const LIMIT=10;
 const shown=showAll?r:r.slice(0,LIMIT);
 const cardsHtml = r.length? shown.map((e,i)=>{
   const cls=DIRCLS[e.impact_direction]||'';const bc=DIRC[e.impact_direction]||'#9a9a96';
   const cc=CONFC[e.confidence]||'#9a9a96';
   const ax=axisOf(e);
   const meta=[`<span class="tag" style="background:${AXIS_COLOR[ax]}18;color:${AXIS_COLOR[ax]}">${AXIS_KO[ax]} 축</span>`]
     .concat(e.confidence?[`<span class="tag" style="background:${cc}22;color:${cc}">신뢰도: ${e.confidence}</span>`]:[]);
   const imp=e.impact?`<div class="imp" style="color:${bc};background:${bc}14">${e.impact}</div>`:'';
   const badge=`<span class="numbadge" style="background:${bc}">${i+1}</span>`;
   // Strip source/filter tags and legacy markers from the body text
   let desc=(e.description||'')
     .replace(/\s*\[출처:[^\]]*\]/g,'')
     .replace(/\s*\[filter:[^\]]*\]/g,'')
     .replace(/\s*\[source:[^\]]*\]/g,'')
     .replace(/1차 출처 업데이트[^—]*—\s*/g,'')
     .replace(/원문:\s*/g,'')
     .trim();
   const src=e.source||'';
   const llm=e.llm||'';
   const bottomLine=(src||llm)?
     `<div class="srcline">${llm?`<span class="llmtag">LLM: ${llm}</span>`:''}${src?`<span>source: ${src}</span>`:''}</div>`:'';
   return `<div class="evt ${cls}" id="evt-${i+1}"><div class="top"><span class="ttl">${badge}${e.title}</span><span class="meta">${e.date||''}</span></div>
     <div class="indent">${meta.join('')}</div>${imp?'<div class="indent">'+imp+'</div>':''}
     <div class="desc indent">${desc}</div>
     <div class="kline indent"><span class="klbl">영향 국가:</span><span class="metaval">${scopeLabelKo(e.scope)}</span></div>
     <div class="kline indent"><span class="klbl">영향 사업부:</span><span class="metaval">${divLabel(e.divisions)}</span></div>
     ${bottomLine}</div>`;}).join('') : '<div class="empty">해당 조건에 맞는 이벤트가 없습니다.</div>';
 const moreBtn = (r.length>LIMIT)? `<button id="morebtn" style="display:block;margin:4px auto 0;padding:9px 20px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--blue);font-size:13px;font-weight:500;cursor:pointer">${showAll?'접기':'더보기 ('+(r.length-LIMIT)+'개 더)'}</button>` : '';
 document.getElementById('list').innerHTML = cardsHtml + moreBtn;
 const mb=document.getElementById('morebtn');
 if(mb) mb.onclick=()=>{ showAll=!showAll; render(); };
}
function exportCSV(){const r=rows();
 const h=['date','scope','divisions','kpi','title','impact','description','impact_direction','confidence','llm','source','raw_title','raw_desc','raw_url'];
 const csv=[h.join(',')].concat(r.map(x=>h.map(k=>`"${(x[k]||'').toString().replace(/"/g,'""')}"`).join(','))).join('\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+csv,{type:'text/csv;charset=utf-8'}]));a.download='scom_external_factors.csv';a.click();}
document.getElementById('csvbtn').onclick=exportCSV;
region.onchange=()=>{showAll=false;syncCountries();render();};
country.onchange=onCountryChange;
[dv,sd,ed,csd,ced].forEach(el=>el.onchange=()=>{showAll=false;render();});
ptype.onchange=refreshPeriod; cmpBasis.onchange=()=>{applyPeriod();showAll=false;render();};
// Traffic CSV upload (in-memory only, never persisted)
const trafficFile=document.getElementById('trafficFile');
document.getElementById('uploadBtn').onclick=()=>trafficFile.click();
trafficFile.onchange=e=>{
 const f=e.target.files[0]; if(!f) return;
 const reader=new FileReader();
 reader.onload=ev=>{
  const parsed=parseTrafficCSV(ev.target.result);
  if(!parsed){ document.getElementById('csvStatus').textContent='CSV 형식을 읽지 못했습니다 (국가,날짜,트래픽 확인)'; return; }
  UPLOADED_TRAFFIC=parsed;
  const dates=parsed.raw.map(r=>r.date).sort();
  const days=new Set(dates).size;
  const from=dates[0], to=dates[dates.length-1];
  document.getElementById('csvStatus').innerHTML=`<span style="color:#137a52">● 실제 트래픽 사용 중</span> · ${parsed.countries.size}개국 · ${from}~${to} (${days}일, 저장 안 됨)`;
  showAll=false; render();
 };
 reader.readAsText(f,'utf-8');
 trafficFile.value='';  // allow re-upload of same file
};
document.getElementById('clearTrafficBtn').onclick=()=>{
 UPLOADED_TRAFFIC=null;
 document.getElementById('csvStatus').textContent='';
 showAll=false; render();
};
refreshPeriod();

// ===== Tab switching =====
document.querySelectorAll('.tab').forEach(t=>{
 t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.tabpane').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('tab-'+t.dataset.tab).classList.add('active');
  if(t.dataset.tab==='stats'){ ensureStatsInit(); }
 };
});

// ===== Country-statistics tab =====
let statsChart, statsReady=false;
const stCountry=document.getElementById('st_country'),
      stIndicator=document.getElementById('st_indicator');
function ensureStatsInit(){
 if(statsReady) return;
 statsReady=true;
 const countries=STATS.countries||{};
 const indicators=STATS.indicators||{};
 // Could restrict to countries with data; currently shows all
 const dataMap=STATS.data||{};
 const cList=Object.keys(countries);
 stCountry.innerHTML=cList.map((c,i)=>`<option value="${c}"${i===0?' selected':''}>${countries[c]}</option>`).join('');
 const iList=Object.keys(indicators);
 stIndicator.innerHTML=iList.map((code,i)=>`<option value="${code}"${i===0?' selected':''}>${indicators[code].label}</option>`).join('');
 stCountry.onchange=drawStats; stIndicator.onchange=drawStats;
 drawStats();
}
function fmtNum(v,unit){
 if(v==null) return '-';
 if(unit==='US$'){ if(v>=1e9)return (v/1e9).toFixed(1)+'B'; if(v>=1e6)return (v/1e6).toFixed(1)+'M'; return Math.round(v).toLocaleString(); }
 if(unit==='명'){ if(v>=1e6)return (v/1e6).toFixed(1)+'M'; return Math.round(v).toLocaleString(); }
 return (Math.round(v*10)/10)+(unit==='%'?'%':'');
}
function drawStats(){
 const c=stCountry.value, code=stIndicator.value;
 const ind=(STATS.indicators||{})[code]||{label:code,unit:''};
 const cname=(STATS.countries||{})[c]||c;
 const all=((STATS.data||{})[c]||{})[code]||[];
 // Recent window helper (kept for reference)
 const series=all.slice(-2).length>=1?all.slice(-Math.min(all.length, 2*1)):[];
 // Show the last several points so the trend is visible
 const show=all.slice(-6); // last up to 6 data points
 const labels=show.map(p=>p[0]);
 const vals=show.map(p=>p[1]);
 document.getElementById('st_title').textContent=`${cname} · ${ind.label}`;
 const last=vals[vals.length-1], prev=vals.length>1?vals[vals.length-2]:null;
 let metaTxt='';
 if(last!=null){
  metaTxt=`최신 ${fmtNum(last,ind.unit)}`;
  if(prev!=null){ const d=last-prev; const pct=prev?(d/prev*100):0;
    metaTxt+=` · 전년대비 ${d>=0?'▲':'▼'} ${Math.abs(pct).toFixed(1)}%`; }
 } else { metaTxt='데이터 없음 — 다음 통계 수집 후 표시됩니다'; }
 document.getElementById('st_meta').textContent=metaTxt;
 if(statsChart)statsChart.destroy();
 statsChart=new Chart(document.getElementById('st_chart'),{type:'line',
  data:{labels,datasets:[{label:ind.label,data:vals,borderColor:'#1428A0',
    backgroundColor:'#1428A018',tension:0.3,pointRadius:3,pointBackgroundColor:'#1428A0',
    borderWidth:2.5,fill:true,spanGaps:true}]},
  options:{responsive:true,maintainAspectRatio:false,
   plugins:{legend:{display:false},
     tooltip:{callbacks:{label:ctx=>ind.label+': '+fmtNum(ctx.parsed.y,ind.unit)}}},
   scales:{x:{ticks:{color:'#888780',font:{size:11}},grid:{display:false}},
     y:{ticks:{color:'#888780',font:{size:11},callback:v=>fmtNum(v,ind.unit)},
        grid:{color:'rgba(136,135,128,0.10)'}}}}});
}

</script></body></html>"""

LLM_LABELS={"ok":"정상 ✓","retired":"종료됨 — 모델 교체 필요","unknown":"키 없음",
            "error":"점검 실패 — 확인 필요"}
_LLM_DISPLAY=[("gemini","Gemini (1순위)"),("groq","Groq (2순위)"),("mistral","Mistral (3순위)")]
_checked=str(mstat.get("last_checked","n/a"))
def _badge(name, label):
    s=_mstat_of(name)
    status=s.get("status","unknown")
    note=str(s.get("note","")).replace('"',"'")
    model=str(s.get("model","unknown"))
    lbl=LLM_LABELS.get(status,"상태 미상")
    return (f'<div class="mbadge {status}" title="{note}"><span class="dot"></span>'
            f'<span>{label}: <strong>{model}</strong> — {lbl}</span></div>')
mbadges_html = "".join(_badge(n,l) for n,l in _LLM_DISPLAY) + \
    f'<div class="mbadge" style="opacity:.6">점검 {_checked}</div>'

HTML=(HTML.replace("__DATA__",json.dumps(events,ensure_ascii=False))
          .replace("__WIKI__",json.dumps(wiki,ensure_ascii=False))
          .replace("__STATS__",json.dumps(stats_series,ensure_ascii=False))
          .replace("__CRUX__",json.dumps(crux,ensure_ascii=False))
          .replace("__MBADGES__",mbadges_html)
          .replace("__DEF_CMP_FROM__",DEF_CMP_FROM)
          .replace("__DEF_CMP_TO__",DEF_CMP_TO)
          .replace("__DEF_CUR_FROM__",DEF_CUR_FROM)
          .replace("__DEF_CUR_TO__",DEF_CUR_TO)
          .replace("__UPDATED__",updated))
open(OUT,"w",encoding="utf-8").write(HTML)
print("built index.html with",len(events),"events, wiki series:",list(wiki.get("series",{}).keys()))
