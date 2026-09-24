"""Create the standalone Strong Index dashboard from accumulated CSV files."""


from __future__ import annotations


import csv
import json
from pathlib import Path




OUTPUT_DIR = Path("output")
CSV_PATH = OUTPUT_DIR / "stong_index.csv"
INDEX_PATH = OUTPUT_DIR / "index_snapshots.csv"
DASHBOARD_PATH = OUTPUT_DIR / "strong_index_dashboard.html"




def number(value: str) -> float:
    try:
        return float(value.replace(",", ""))
    except (AttributeError, ValueError):
        return 0.0




def load_rows() -> list[dict[str, object]]:
    if not CSV_PATH.exists():
        return []
    rows: list[dict[str, object]] = []
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as file:
        for raw in csv.DictReader(file):
            rows.append({
                "date": raw.get("run_date", ""),
                "code": raw.get("code", ""),
                "name": raw.get("name", ""),
                "marketCap": number(raw.get("market_cap_억원", "0")),
                "rs": number(raw.get("rs_index", "0")),
                "ma20Gap": number(raw.get("ma20_gap_pct", "0")),
                "volatilityContraction": raw.get("volatility_contraction", "X"),
                "priceChange5d": number(raw.get("price_change_5d_pct", "0")),
                "industry": raw.get("industry", ""),
                "theme": raw.get("core_theme", ""),
                "etfGood": raw.get("etf_trend_good", ""),
                "etfNames": raw.get("etf_names", ""),
            })
    return rows




def load_indices() -> list[dict[str, object]]:
    if not INDEX_PATH.exists():
        return []
    indices: list[dict[str, object]] = []
    with INDEX_PATH.open(encoding="utf-8-sig", newline="") as file:
        for raw in csv.DictReader(file):
            indices.append({
                "date": raw.get("run_date", ""),
                "name": raw.get("index_name", ""),
                "close": number(raw.get("close", "0")),
                "ma20Gap": number(raw.get("ma20_gap_pct", "0")),
            })
    return indices




def render(rows: list[dict[str, object]], indices: list[dict[str, object]]) -> str:
    page = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strong Index Dashboard</title><style>
:root{--green:#03c75a;--ink:#18202a;--muted:#697585;--line:#e5ebf1;--paper:#fff;--bg:#f4f6f8;--up:#e24b55;--down:#2879e8}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Pretendard,"Malgun Gothic",Arial,sans-serif}.top{background:#fff;border-bottom:1px solid var(--line)}.topin,main{max-width:1440px;margin:auto;padding-left:28px;padding-right:28px}.topin{min-height:70px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}.brand{color:var(--green);font-weight:900;font-size:20px}.divider{width:1px;height:20px;background:#dbe1e8}.subtitle{font-size:13px;color:var(--muted);font-weight:700}.indexboard{margin-left:auto;display:flex;gap:8px}.indexpill{min-width:150px;padding:9px 12px;border:1px solid #dce8e1;border-radius:9px;background:#f8fcf9}.indexname{display:block;font-size:11px;font-weight:900;color:#536170}.indexvalue{font-size:15px}.indexgap{margin-left:6px;font-size:12px;font-weight:800}main{padding-top:34px;padding-bottom:56px}.headline{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:22px}h1{margin:0 0 7px;font-size:28px}.note{margin:0;color:var(--muted);font-size:14px}select{min-width:160px;padding:11px;border:1px solid #d9dfe7;border-radius:8px;background:#fff;font:inherit}.criteria{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}.criterion,.calendar,.panel{background:var(--paper);border:1px solid var(--line);border-radius:12px}.criterion{padding:18px 20px}.criterion h2{margin:0 0 10px;font-size:14px}.criterion ul{margin:0;padding:0;list-style:none}.criterion li{position:relative;padding:3px 0 3px 10px;color:#4e5a68;font-size:12px;line-height:1.45}.criterion li:before{content:"";position:absolute;left:0;top:9px;width:4px;height:4px;border-radius:50%;background:var(--green)}.calendar{overflow:hidden;margin-bottom:24px}.calendarhead,.panelhead{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;border-bottom:1px solid var(--line)}.monthnav{display:flex;align-items:center;gap:12px}.monthnav strong{min-width:102px;text-align:center}.navbtn{width:30px;height:30px;border:1px solid #dce2e9;border-radius:7px;background:#fff;font-size:18px;cursor:pointer}.hint,.updated{color:var(--muted);font-size:12px}.weekdays,.days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}.weekdays div{padding:10px;text-align:right;background:#fafbfc;color:#748090;font-size:12px;font-weight:800}.weekdays div:first-child{color:var(--up)}.weekdays div:last-child{color:var(--down)}.day{min-height:125px;padding:8px;border:0;border-right:1px solid #edf0f4;border-bottom:1px solid #edf0f4;background:#fff;text-align:left;font:inherit}.day:nth-child(7n){border-right:0}.day.blank{background:#fafbfc}.day.hasdata{cursor:pointer}.day.selected,.day.hasdata:hover{background:#f4fcf7}.day.selected{outline:2px solid var(--green);outline-offset:-2px}.date{display:block;text-align:right;color:#6e7885;font-size:12px;font-weight:800}.countchip{display:block;margin-top:7px;color:#46525f;font-size:12px;font-weight:900}.prioritytitle{display:block;margin-top:7px;color:#4b5966;font-size:10px;font-weight:900}.stockchip{display:block;margin:3px 0;padding:3px 5px;border-radius:4px;background:#eaf8ef;color:#087d40;font-size:11px;font-weight:800}.streak{margin-left:4px;color:#2670c9;font-size:10px;font-weight:900}.scroll{overflow:auto}table{width:100%;min-width:980px;border-collapse:collapse;font-size:14px}th{padding:13px 16px;background:#fafbfc;border-bottom:1px solid var(--line);text-align:left;color:#687484;font-size:12px}th button{border:0;background:transparent;color:inherit;font:inherit;font-weight:900;cursor:pointer}td{padding:16px;border-bottom:1px solid #edf0f4;vertical-align:top}.rank,.code{color:#84909d}.name{font-weight:900;font-size:15px}.code{display:block;margin-top:4px;font-size:12px}.positive{color:var(--up);font-weight:800}.negative{color:var(--down);font-weight:800}.neutral{color:#576270;font-weight:800}.pill{display:inline-block;border-radius:99px;padding:5px 8px;font-size:12px;font-weight:900}.pass{background:#e9f9ef;color:#078440}.fail{background:#f1f3f5;color:#707984}.change{margin-top:5px;font-size:12px;font-weight:800}.theme,.etf{margin-top:4px;color:#596574;font-size:13px;line-height:1.5}.empty{padding:50px;text-align:center;color:var(--muted)}@media(max-width:1050px){.criteria{grid-template-columns:repeat(2,1fr)}}@media(max-width:820px){.topin,main{padding-left:16px;padding-right:16px}.headline{align-items:flex-start;flex-direction:column}.indexboard{width:100%;margin:0}.indexpill{flex:1}.day{min-height:100px;padding:5px}.stockchip{font-size:10px}}@media(max-width:540px){.subtitle,.hint{display:none}.criteria{grid-template-columns:1fr}.day{min-height:80px;padding:3px}.stockchip{font-size:9px;padding:2px}.prioritytitle{font-size:8px}.countchip{font-size:10px}}
</style></head><body><header class="top"><div class="topin"><span class="brand">STRONG INDEX</span><span class="divider"></span><span class="subtitle">장 마감 후 수집한 코스피 강세 종목 데이터</span><div class="indexboard"><div class="indexpill"><span class="indexname">KOSPI</span><strong class="indexvalue" id="kospiClose">-</strong><span class="indexgap" id="kospiGap">-</span></div><div class="indexpill"><span class="indexname">KOSDAQ</span><strong class="indexvalue" id="kosdaqClose">-</strong><span class="indexgap" id="kosdaqGap">-</span></div></div></div></header><main><section class="headline"><div><h1>Strong Index</h1><p class="note">장 마감 후 수집한 코스피 대비 강세 종목 · 투자 참고용 데이터</p></div><select id="dateSelect" aria-label="조회 날짜"></select></section><section class="criteria"><article class="criterion"><h2>대상 · 규모</h2><ul><li>코스피와 코스닥 전체 종목</li><li>시가총액 5,000억 원 이상</li></ul></article><article class="criterion"><h2>상대강도 · 추세</h2><ul><li>120거래일 기준 RS 지수 80 초과</li><li>종가가 120일 이동평균선 위</li><li>20일선 괴리율 ±10% 이내</li></ul></article><article class="criterion"><h2>변동성 수축 O 표기</h2><ul><li>5거래일 주가 변화율 ±5% 이내</li><li>총 60거래일 중 직전 55일 평균 거래량이 최근 5일 평균의 2배 이상</li></ul></article><article class="criterion"><h2>ETF 추세양호 표기</h2><ul><li>공개 편입 비중 순위 5위 이내</li><li>ETF 20일선 괴리율 ±10% 이내</li><li>시가총액 상위 ETF 3개까지 표시</li></ul></article></section><section class="calendar"><div class="calendarhead"><div class="monthnav"><button class="navbtn" id="prevMonth">‹</button><strong id="monthTitle"></strong><button class="navbtn" id="nextMonth">›</button></div><span class="hint">날짜를 선택하면 아래 상세 분석을 확인할 수 있습니다.</span></div><div class="weekdays"><div>일</div><div>월</div><div>화</div><div>수</div><div>목</div><div>금</div><div>토</div></div><div class="days" id="calendarDays"></div></section><section class="panel"><div class="panelhead"><strong>종목 분석</strong><span class="updated" id="updated"></span></div><div class="scroll"><table><thead><tr><th>순위</th><th><button data-sort="name">종목 ↕</button></th><th><button data-sort="marketCap">시가총액 ↕</button></th><th><button data-sort="rs">RS 지수 ↕</button></th><th><button data-sort="ma20Gap">20일선 괴리 ↕</button></th><th><button data-sort="volatilityContraction">변동성 수축 ↕</button></th><th><button data-sort="industry">산업군 ↕</button></th><th><button data-sort="theme">테마 ↕</button></th><th><button data-sort="etfGood">ETF 추세양호 · ETF명 ↕</button></th></tr></thead><tbody id="tbody"></tbody></table></div><div class="empty" id="empty" hidden>선택한 날짜의 데이터가 없습니다.</div></section></main><script>
const rows=__ROWS__;const indexRows=__INDICES__;const PASS='통과';const select=document.getElementById('dateSelect');const dates=[...new Set([...rows.map(r=>r.date),...indexRows.map(r=>r.date)])].sort().reverse();const byDate={};dates.forEach(d=>byDate[d]=rows.filter(r=>r.date===d));let selectedDate=dates[0]||'';let shownMonth=selectedDate?new Date(selectedDate+'T12:00:00'):new Date();let sortKey='rs';let sortDirection=-1;
function esc(value){return String(value||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}function signed(value){return (value>0?'+':'')+Number(value).toFixed(2)+'%';}function tone(value){return value>0?'positive':value<0?'negative':'neutral';}function marketCap(value){if(!value)return '-';return Number((value/10000).toFixed(1)).toLocaleString()+'조';}function iso(y,m,d){return y+'-'+String(m+1).padStart(2,'0')+'-'+String(d).padStart(2,'0');}
function streakDays(date,name){const cursor=new Date(date+'T12:00:00'),monday=new Date(cursor);monday.setDate(cursor.getDate()-((cursor.getDay()+6)%7));if(cursor.getDay()===1)return 1;let count=0;while(cursor>=monday){const weekday=cursor.getDay();if(weekday===0||weekday===6){cursor.setDate(cursor.getDate()-1);continue;}const items=byDate[iso(cursor.getFullYear(),cursor.getMonth(),cursor.getDate())]||[];if(!items.length){cursor.setDate(cursor.getDate()-1);continue;}if(!items.some(item=>item.name===name))break;count++;cursor.setDate(cursor.getDate()-1);}return count;}
function renderIndices(date){const found={};indexRows.filter(i=>i.date===date).forEach(i=>found[i.name]=i);[['KOSPI','kospi'],['KOSDAQ','kosdaq']].forEach(pair=>{const item=found[pair[0]];document.getElementById(pair[1]+'Close').textContent=item?Number(item.close).toLocaleString(undefined,{maximumFractionDigits:2}):'-';const gap=document.getElementById(pair[1]+'Gap');gap.textContent=item?signed(item.ma20Gap):'-';gap.className='indexgap '+(item?tone(item.ma20Gap):'neutral');});}
function render(date){selectedDate=date;const data=(byDate[date]||[]).slice();data.sort((a,b)=>{const av=a[sortKey],bv=b[sortKey];const cmp=typeof av==='number'?av-bv:String(av||'').localeCompare(String(bv||''),'ko');return cmp*sortDirection;});document.getElementById('updated').textContent=date?date+' 장 마감 기준':'';renderIndices(date);const body=document.getElementById('tbody');body.innerHTML=data.map((r,i)=>'<tr><td class="rank">'+(i+1)+'</td><td><span class="name">'+esc(r.name)+'</span><span class="code">'+esc(r.code)+'</span></td><td>'+marketCap(r.marketCap)+'</td><td class="positive">'+Number(r.rs).toFixed(2)+'</td><td class="'+tone(r.ma20Gap)+'">'+signed(r.ma20Gap)+'</td><td><span class="pill '+(r.volatilityContraction==='O'?'pass':'fail')+'">'+esc(r.volatilityContraction)+'</span><div class="change '+tone(r.priceChange5d)+'">'+signed(r.priceChange5d)+'</div></td><td><strong>'+esc(r.industry)+'</strong></td><td><div class="theme">'+esc(r.theme)+'</div></td><td><span class="pill '+(r.etfGood===PASS?'pass':'fail')+'">'+esc(r.etfGood||'-')+'</span><div class="etf">'+esc(r.etfNames||'-')+'</div></td></tr>').join('');document.getElementById('empty').hidden=data.length>0;renderCalendar();}
function renderCalendar(){const y=shownMonth.getFullYear(),m=shownMonth.getMonth(),first=new Date(y,m,1).getDay(),last=new Date(y,m+1,0).getDate(),cells=[];document.getElementById('monthTitle').textContent=y+'년 '+(m+1)+'월';for(let i=0;i<first;i++)cells.push('<div class="day blank"></div>');for(let day=1;day<=last;day++){const date=iso(y,m,day),data=byDate[date]||[],priority=data.filter(r=>r.volatilityContraction==='O');let inside='<span class="date">'+day+'</span>';if(data.length){inside+='<span class="countchip">'+data.length+'종목</span>';if(priority.length){inside+='<span class="prioritytitle">우선확인종목</span>'+priority.map(r=>{const streak=streakDays(date,r.name);return '<span class="stockchip">'+esc(r.name)+(streak>=2?'<span class="streak">연속'+streak+'일</span>':'')+'</span>';}).join('');}}const week=(first+day-1)%7;cells.push('<button class="day '+(data.length?'hasdata ':'')+(date===selectedDate?'selected ':'')+(week===0?'sunday':week===6?'saturday':'')+'" '+(data.length?'data-date="'+date+'"':'disabled')+'>'+inside+'</button>');}while(cells.length%7)cells.push('<div class="day blank"></div>');document.getElementById('calendarDays').innerHTML=cells.join('');}
dates.forEach(d=>select.add(new Option(d,d)));select.addEventListener('change',e=>render(e.target.value));document.getElementById('calendarDays').addEventListener('click',e=>{const button=e.target.closest('[data-date]');if(button){select.value=button.dataset.date;render(button.dataset.date);}});document.querySelectorAll('[data-sort]').forEach(button=>button.addEventListener('click',()=>{const key=button.dataset.sort;sortDirection=key===sortKey?-sortDirection:-1;sortKey=key;render(selectedDate);}));document.getElementById('prevMonth').addEventListener('click',()=>{shownMonth=new Date(shownMonth.getFullYear(),shownMonth.getMonth()-1,1);renderCalendar();});document.getElementById('nextMonth').addEventListener('click',()=>{shownMonth=new Date(shownMonth.getFullYear(),shownMonth.getMonth()+1,1);renderCalendar();});if(dates.length){select.value=dates[0];render(dates[0]);}else{renderCalendar();}
</script></body></html>'''
    page = page.replace(
        ".indexvalue{font-size:15px}.indexgap{margin-left:6px;font-size:12px;font-weight:800}",
        ".indexvalue{display:block;font-size:15px}.indexgaplabel{font-size:11px;color:#697585;font-weight:700}.indexgap{margin-left:4px;font-size:12px;font-weight:800}",
    ).replace(
        '<strong class="indexvalue" id="kospiClose">-</strong><span class="indexgap" id="kospiGap">-</span>',
        '<strong class="indexvalue" id="kospiClose">-</strong><span class="indexgaplabel">20이평선 대비</span><span class="indexgap" id="kospiGap">-</span>',
    ).replace(
        '<strong class="indexvalue" id="kosdaqClose">-</strong><span class="indexgap" id="kosdaqGap">-</span>',
        '<strong class="indexvalue" id="kosdaqClose">-</strong><span class="indexgaplabel">20이평선 대비</span><span class="indexgap" id="kosdaqGap">-</span>',
    ).replace(
        ".theme,.etf{margin-top:4px;color:#596574;font-size:13px;line-height:1.5}",
        ".theme,.etf{margin-top:4px;color:#596574;font-size:13px;line-height:1.65}.tag-list{display:flex;flex-direction:column;align-items:flex-start;gap:6px}.data-tag{display:block;max-width:100%;padding:5px 9px;border-radius:999px;font-size:12px;font-weight:800;line-height:1.35}.theme-tag{background:#f2efff;color:#6254a3}.etf-tag{background:#e9f9ef;color:#087d40}.help-target{border-bottom:1px dashed #9ba7b4;cursor:help}.header-tip{position:fixed;z-index:10;max-width:280px;padding:10px 12px;border:1px solid #cfd9e3;border-radius:8px;background:#fff;box-shadow:0 6px 18px rgba(24,32,42,.14);color:#3f4b59;font-size:12px;font-weight:500;line-height:1.5;pointer-events:none}",
    ).replace(
        "<li>공개 편입 비중 순위 5위 이내</li><li>ETF 20일선 괴리율 ±10% 이내</li><li>시가총액 상위 ETF 3개까지 표시</li>",
        "<li>종목 편입 ETF 중 시가총액 상위 3개</li><li>편입비중 10위 이내는 편입상위로 표기</li><li>각 ETF의 20일선 괴리율 ±10% 이내 여부 집계</li>",
    ).replace(
        "function esc(value){",
        "function initHeaderTips(){const tip=document.getElementById('headerTip');let timer;const hide=()=>{clearTimeout(timer);tip.hidden=true;};document.querySelectorAll('[data-help]').forEach(target=>{target.addEventListener('mouseenter',()=>{timer=setTimeout(()=>{tip.textContent=target.dataset.help;const rect=target.getBoundingClientRect();tip.style.left=Math.min(rect.left,window.innerWidth-300)+'px';tip.style.top=(rect.bottom+8)+'px';tip.hidden=false;},1000);});target.addEventListener('mouseleave',hide);});}function labelItems(value){return String(value||'').split(/\\n|\\s*\\/\\s*/).map(item=>item.trim()).filter(Boolean);}function tagLines(value,kind){const items=labelItems(value);return items.length?'<div class=\"tag-list\">'+items.map(item=>'<span class=\"data-tag '+kind+'\">'+esc(item)+'</span>').join('')+'</div>':'-';}function themePills(value){return tagLines(value,'theme-tag');}function etfPills(value){return tagLines(value,'etf-tag');}function etfPassLabel(row){if(/^\\d+개통과$/.test(String(row.etfGood||'')))return row.etfGood;if(row.etfGood===PASS){const count=Math.min(labelItems(row.etfNames).length,3);return count?count+'개통과':'0개통과';}return row.etfGood||'-';}function esc(value){",
    ).replace(
        "<td><span class=\"pill '+(r.etfGood===PASS?'pass':'fail')+'\">'+esc(r.etfGood||'-')+'</span><div class=\"etf\">'+esc(r.etfNames||'-')+'</div></td>",
        "<td><span class=\"pill '+(etfPassLabel(r)==='0개통과'?'fail':'pass')+'\">'+esc(etfPassLabel(r))+'</span><div class=\"etf\">'+etfPills(r.etfNames)+'</div></td>",
    ).replace(
        "<td><div class=\"theme\">'+esc(r.theme)+'</div></td>",
        "<td><div class=\"theme\">'+themePills(r.theme)+'</div></td>",
    ).replace(
        "</main><script>",
        '<div class="header-tip" id="headerTip" role="tooltip" hidden></div></main><script>',
    ).replace(
        '<th>순위</th><th><button data-sort="name">종목 ↕</button></th><th><button data-sort="marketCap">시가총액 ↕</button></th><th><button data-sort="rs">RS 지수 ↕</button></th><th><button data-sort="ma20Gap">20일선 괴리 ↕</button></th><th><button data-sort="volatilityContraction">변동성 수축 ↕</button></th><th><button data-sort="industry">산업군 ↕</button></th><th><button data-sort="theme">테마 ↕</button></th><th><button data-sort="etfGood">ETF 추세양호 · ETF명 ↕</button></th>',
        '<th><span class="help-target" data-help="현재 선택된 정렬 기준의 순위입니다. 기본 정렬은 RS 지수 내림차순입니다.">순위</span></th><th><button data-sort="name"><span class="help-target" data-help="종목명과 종목 코드입니다.">종목</span> ↕</button></th><th><button data-sort="marketCap"><span class="help-target" data-help="종가 기준 시가총액입니다. 표에서는 조 단위로 표시합니다.">시가총액</span> ↕</button></th><th><button data-sort="rs"><span class="help-target" data-help="같은 기간 코스피 대비 종목의 상대강도 지수입니다. 100보다 크면 코스피보다 강했다는 뜻입니다.">RS 지수</span> ↕</button></th><th><button data-sort="ma20Gap"><span class="help-target" data-help="종가가 20일 이동평균선에서 얼마나 떨어져 있는지 나타낸 비율입니다.">20일선 괴리</span> ↕</button></th><th><button data-sort="volatilityContraction"><span class="help-target" data-help="변동성 수축 기준 충족 여부입니다. 충족하면 O, 아니면 X로 표시합니다.">변동성 수축</span> ↕</button></th><th><button data-sort="industry"><span class="help-target" data-help="종목의 산업군 분류입니다.">산업군</span> ↕</button></th><th><button data-sort="theme"><span class="help-target" data-help="종목과 연관된 주요 테마입니다.">테마</span> ↕</button></th><th><button data-sort="etfGood"><span class="help-target" data-help="규모 상위 3개 편입 ETF 중 20일선 괴리율이 ±10% 이내인 ETF의 개수입니다.">ETF 추세양호</span> · <span class="help-target" data-help="해당 종목이 편입된 규모 상위 3개 ETF입니다. 편입비중 10위 이내면 편입상위로 표시합니다.">ETF명</span> ↕</button></th>',
    ).replace(
        "if(dates.length){select.value=dates[0];render(dates[0]);}",
        "initHeaderTips();if(dates.length){select.value=dates[0];render(dates[0]);}",
    ).replace("코스피와 코스닥 전체 종목", "코스피 전체 종목")
    return page.replace("__ROWS__", json.dumps(rows, ensure_ascii=True)).replace(
        "__INDICES__", json.dumps(indices, ensure_ascii=True)
    )




def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    DASHBOARD_PATH.write_text(render(load_rows(), load_indices()), encoding="utf-8")
    print(f"Dashboard saved: {DASHBOARD_PATH}")




if __name__ == "__main__":
    main()

