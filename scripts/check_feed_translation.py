# events.json에서 피드 이벤트 번역 실패 여부를 점검하는 진단 스크립트
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "data/events.json"
ev = json.load(open(path, encoding="utf-8"))

def has_korean(s):
    return any('\uac00' <= c <= '\ud7a3' for c in (s or ""))

feeds = [e for e in ev if e.get("event_id","").startswith("FP")]
print(f"피드 이벤트(FP): {len(feeds)}건")
if not feeds:
    print("→ 피드 이벤트가 없음. GitHub 배포본의 events.json을 받아서 이 스크립트로 검사하세요.")
    sys.exit()

eng_desc = [e for e in feeds if not has_korean(e.get("description",""))]
same_as_raw = [e for e in feeds if e.get("description","") == e.get("raw_desc","") and e.get("raw_desc")]

print(f"  description이 영어(번역 실패 의심): {len(eng_desc)}건")
print(f"  description == raw_desc(번역 전혀 안 됨): {len(same_as_raw)}건")
print()
if eng_desc:
    print("=== 번역 실패 의심 항목 (최대 5건) ===")
    for e in eng_desc[:5]:
        print(f"  {e['event_id']} | {e.get('title','')[:50]}")
        print(f"    desc: {e.get('description','')[:80]}")
    rate = len(eng_desc)/len(feeds)*100
    print()
    print(f"→ 피드 {len(feeds)}건 중 {len(eng_desc)}건({rate:.0f}%)이 영어 = LLM 체인(Gemini→Groq→Mistral)이 전부 실패했거나 GROQ_API_KEY/MISTRAL_API_KEY 미설정")
else:
    print("✓ 모든 피드 이벤트가 한국어 — 번역 정상")
