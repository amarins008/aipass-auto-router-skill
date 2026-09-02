# Auto-class Detection Rules

When the user types `aipass: <prompt>` without an explicit class, this heuristic picks one. Order matters — most specific class first.

## Rules (in order)

| # | Pattern (regex, case-insensitive) | Class |
|---|----------------------------------|-------|
| 1 | `วิดีโอ|คลิป|\bvideo\b|\bclip\b|animation|animated` | `video` |
| 2 | `เพลง|ดนตรี|\bmusic\b|\bsong\b|jingle|beat|melody` | `music` |
| 3 | `สร้าง.*รูป|วาด.*รูป|ภาพ|รูปภาพ|\bdraw\b|\bpaint\b|\bsketch\b|illustration|generate.*image|image.*of|\bdiffusion\b` | `image` |
| 4 | `พิสูจน์|ทฤษฎีบท|\bproof\b|\bprove\b|\btheorem\b|\baxiom\b|mathematical.*proof|formal.*logic|induction` | `deep-reasoning` |
| 5 | `เขียน.*(?:code|โค้ด|function|class|script|api|program)\|เขียน(?:โปรแกรม)?\|implement\|refactor\|debug\|\b(?:python\|javascript\|typescript\|java\|c\+\+\|rust\|go\|ruby\|php\|sql\|html\|css\|react\|vue\|angular\|node\.?js)\b\|recursion\|regex\|algorithm\|data structure\|\bapi\b\|\boop\b\|\bsql\b\|\borm\b\|docker\|kubernetes\|git\|linux.*command` | `code` |
| 6 | `สรุป.*(?:ยาว|ละเอียด|comprehensive)\|\bresearch\b\|วิเคราะห์.*เชิงลึก\|comprehensive.*analysis\|in.*depth\|survey.*of` | `research` |
| 7 | `แปล.*(?:ไทย|thai)\|translate.*thai\|ภาษาไทย\|เขียน.*(?:บทความ|ข่าว|เนื้อหา).*ไทย` | `thai-content` |
| 8 | (default — no match) | `fast` |

## Reference implementation (Python)

```python
import re

AUTO_CLASS_RULES = [
    (r"วิดีโอ|คลิป|\bvideo\b|\bclip\b|animation|animated", "video"),
    (r"เพลง|ดนตรี|\bmusic\b|\bsong\b|jingle|beat|melody", "music"),
    (r"สร้าง.*รูป|วาด.*รูป|ภาพ|รูปภาพ|\bdraw\b|\bpaint\b|\bsketch\b|illustration|generate.*image|image.*of|\bdiffusion\b", "image"),
    (r"พิสูจน์|ทฤษฎีบท|\bproof\b|\bprove\b|\btheorem\b|\baxiom\b|mathematical.*proof|formal.*logic|induction", "deep-reasoning"),
    (r"เขียน.*(?:code|โค้ด|function|class|script|api|program)|เขียน(?:โปรแกรม)?|implement|refactor|debug"
     r"|\b(?:python|javascript|typescript|java|c\+\+|rust|go|ruby|php|sql|html|css|react|vue|angular|node\.?js)\b"
     r"|recursion|regex|algorithm|data structure|\bapi\b|\boop\b|\bsql\b|\borm\b|docker|kubernetes|git|linux.*command",
     "code"),
    (r"สรุป.*(?:ยาว|ละเอียด|comprehensive)|\bresearch\b|วิเคราะห์.*เชิงลึก|comprehensive.*analysis|in.*depth|survey.*of", "research"),
    (r"แปล.*(?:ไทย|thai)|translate.*thai|ภาษาไทย|เขียน.*(?:บทความ|ข่าว|เนื้อหา).*ไทย", "thai-content"),
]

def auto_class(prompt: str) -> str:
    p = prompt.lower()
    for pattern, cls in AUTO_CLASS_RULES:
        if re.search(pattern, p, re.IGNORECASE):
            return cls
    return "fast"
```

## Test cases (16/16 expected)

| Input | Expected |
|-------|----------|
| `สวัสดีตอนเช้า` | `fast` |
| `เขียน Python function คำนวณ fibonacci` | `code` |
| `สร้างรูปแมวสีชมพู` | `image` |
| `พิสูจน์ว่า 2+2=4 แบบ Peano axioms` | `deep-reasoning` |
| `สรุป quantum computing แบบยาวๆ` | `research` |
| `อธิบาย recursion` | `code` |
| `แปล Hello เป็นไทย` | `thai-content` |
| `เพลงบรรเลง` | `music` |
| `วิดีโอแมวเล่นน้ำ` | `video` |
| `write a Python function` | `code` |
| `draw a cat` | `image` |
| `prove this theorem` | `deep-reasoning` |
| `refactor this javascript` | `code` |
| `explain docker` | `code` |
| `ทำ SQL query` | `code` |
| `อธิบาย transformer architecture แบบสั้น` | `fast` |

## Known limits

- "อธิบาย recursion" → `code` (correct) because `recursion` is in the code rule. But "อธิบาย async/await" also matches `code` — that's intentional.
- "อธิบาย transformer architecture แบบสั้น" → `fast` (correct) because no code/research keyword. If Boss wants deep-reasoning here, they can prefix `aipass: deep-reasoning — …`.
- Programming languages in `code` rule: python, javascript, typescript, java, c++, rust, go, ruby, php, sql, html, css, react, vue, angular, node.js.
- If a new class is needed (e.g. `audio`, `math`), insert at the correct specificity position — don't append at the end.
