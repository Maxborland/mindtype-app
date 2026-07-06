"""
Summary prompt presets.

Each preset contains a set of 4 prompts:
- system: system prompt (role and rules)
- short: for short texts (single-stage processing)
- extraction: for extracting facts from chunks
- aggregation: for combining facts into the final summary
"""

from typing import Dict, Any, Optional

# =============================================================================
# PM (PRODUCT MANAGER) - Meeting Notes
# =============================================================================

PM_SYSTEM_PROMPT = """You are a PM assistant. Write in the same language as the transcript.
Your task: extract facts, numbers, and tasks from the text.

RULES:
1. Use the same language as the source transcript.
2. All numbers, dates, and deadlines from the text must be in the response.
3. Do not invent anything that is not in the text.
4. Keep technical terms as-is without translation.
"""

PM_SHORT_PROMPT = """TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"

---

Create a PM summary. Fill in ALL sections below. If a section is empty, write "—".

## 1) All Dates/Numbers/Deadlines
List EVERY date, number, deadline, amount from the text:
- [date/number] — [context from text]

## 2) Decisions and Agreements
What was decided, agreed upon, approved:
- ...

## 3) Waiting from Client
What the client needs to do/provide:
- ...

## 4) Waiting from Contractor
What the contractor needs to do:
- ...

## 5) Risks and Open Questions
What is unresolved, unclear, might go wrong:
- ...

## 6) Next Steps
|| Action | Responsible | Deadline |
||--------|-------------|----------|
|| ... | ... | ... |

IMPORTANT: Fill in ALL 6 sections. Respond in the same language as the transcript."""

PM_EXTRACTION_PROMPT = """Text for analysis:
\"\"\"
{chunk_text}
\"\"\"

Extract all facts from the text above.

## 1. Numbers, Dates, Deadlines
- [value] — [context]

## 2. Decisions and Agreements
- ...

## 3. Tasks
- [Who] → [what will do] (deadline)

## 4. Risks and Questions
- ...

IMPORTANT: Write only facts from the text. If there's no information for a section, write "—"."""

PM_AGGREGATION_PROMPT = """Combine facts from {n_chunks} parts into one final PM summary.

FACTS:
\"\"\"
{extracted_facts}
\"\"\"

Final summary:

## 1) All Numbers/Dates/Deadlines
- [value] — [context]

## 2) Decisions and Agreements
- ...

## 3) Waiting from Client
- ...

## 4) Waiting from Contractor
- ...

## 5) Risks and Questions
- ...

## 6) Next Steps
|| Action | Responsible | Deadline |
||--------|-------------|----------|
|| ... | ... | ... |

IMPORTANT: Do not lose any number or date from the list above."""

# =============================================================================
# STUDENT - Lecture Notes
# =============================================================================

STUDENT_SYSTEM_PROMPT = """You are an assistant for students. Write in the same language as the transcript.
Your task: highlight the main points from the lecture for exam preparation.

RULES:
1. Use the same language as the source transcript.
2. Highlight key concepts, definitions, formulas.
3. Do not invent anything that is not in the text.
4. Preserve subject terminology.
"""

STUDENT_SHORT_PROMPT = """LECTURE TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"

---

Create lecture notes. Fill in ALL sections below. If a section is empty, write "—".

## 1) Topic and Purpose
Briefly: what the lecture is about and what the student should understand

## 2) Key Concepts and Definitions
- **[Term]** — [definition]

## 3) Main Points
Key ideas and statements:
1. ...
2. ...

## 4) Formulas / Rules / Algorithms
If any, list them:
- ...

## 5) Examples from the Lecture
- [example] — [what it illustrates]

## 6) What to Remember for the Exam
- ...

IMPORTANT: Fill in ALL 6 sections. Respond in the same language as the transcript."""

STUDENT_EXTRACTION_PROMPT = """Lecture text for analysis:
\"\"\"
{chunk_text}
\"\"\"

Extract key information from the text above.

## 1. Concepts and Definitions
- **[Term]** — [definition]

## 2. Main Points
- ...

## 3. Formulas / Rules
- ...

## 4. Examples
- ...

IMPORTANT: Write only what is in the text. If there's no information for a section, write "—"."""

STUDENT_AGGREGATION_PROMPT = """Combine material from {n_chunks} parts of the lecture into one set of notes.

MATERIAL:
\"\"\"
{extracted_facts}
\"\"\"

Final lecture notes:

## 1) Topic and Purpose
Briefly: what the lecture is about

## 2) Key Concepts and Definitions
- **[Term]** — [definition]

## 3) Main Points
1. ...
2. ...

## 4) Formulas / Rules / Algorithms
- ...

## 5) Examples
- [example] — [what it illustrates]

## 6) What to Remember for the Exam
- ...

IMPORTANT: Do not lose definitions and formulas from the material above."""

# =============================================================================
# GENERIC - General Videos
# =============================================================================

GENERIC_SYSTEM_PROMPT = """You are an assistant for creating video summaries. Write in the same language as the transcript.
Your task: briefly and structurally present the essence of the video.

RULES:
1. Use the same language as the source transcript.
2. Highlight the main points, skip the filler.
3. Do not invent anything that is not there.
"""

GENERIC_SHORT_PROMPT = """TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"

---

Create a video summary. Fill in ALL sections below. If a section is empty, write "—".

## 1) What the Video is About
1-2 sentences

## 2) Key Points
- ...

## 3) Useful Tips / Insights
- ...

## 4) Mentioned Resources
Links, books, tools, if any:
- ...

## 5) Brief Conclusion
Main takeaway in 1-2 sentences

IMPORTANT: Fill in ALL 5 sections. Respond in the same language as the transcript."""

GENERIC_EXTRACTION_PROMPT = """Text for analysis:
\"\"\"
{chunk_text}
\"\"\"

Extract key information from the text above.

## 1. Main Ideas
- ...

## 2. Tips / Insights
- ...

## 3. Mentioned Resources
- ...

IMPORTANT: Write only what is in the text. If there's no information for a section, write "—"."""

GENERIC_AGGREGATION_PROMPT = """Combine information from {n_chunks} parts into one summary.

INFORMATION:
\"\"\"
{extracted_facts}
\"\"\"

Final summary:

## 1) What the Video is About
1-2 sentences

## 2) Key Points
- ...

## 3) Useful Tips / Insights
- ...

## 4) Mentioned Resources
- ...

## 5) Brief Conclusion
Main takeaway

IMPORTANT: Do not lose important details from the material above."""

# =============================================================================
# CALL - Meeting / Call Key Points (capture EVERYTHING important)
# =============================================================================

CALL_SYSTEM_PROMPT = """You are an assistant that captures the full record of a call/meeting. Write in the same language as the transcript.
Your task: capture EVERY important point discussed — nothing important should be lost.

RULES:
1. Use the same language as the source transcript.
2. Capture all important points: topics, decisions, action items, numbers, dates, questions, agreements, who said what.
3. Do not invent anything that is not in the text.
4. Keep technical terms and names as-is without translation.
5. Better to include a point than to drop it — be exhaustive on what matters.
"""

CALL_SHORT_PROMPT = """CALL TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"

---

Capture ALL important points from this call. Fill in EVERY section below. If a section is empty, write "—".

## 1) Participants and Roles
Who took part and their role, if mentioned:
- ...

## 2) Topics Discussed
Every distinct topic raised during the call:
- ...

## 3) Key Points and Statements
All important points, facts, and statements made (who said what):
- ...

## 4) Decisions and Agreements
What was decided, agreed, approved:
- ...

## 5) Numbers, Dates, Deadlines
EVERY number, date, amount, deadline from the call:
- [value] — [context]

## 6) Open Questions
Unresolved questions, disagreements, things to clarify:
- ...

## 7) Action Items
|| Action | Responsible | Deadline |
||--------|-------------|----------|
|| ... | ... | ... |

IMPORTANT: Be exhaustive — do not drop any important point. Respond in the same language as the transcript."""

CALL_EXTRACTION_PROMPT = """Call segment for analysis:
\"\"\"
{chunk_text}
\"\"\"

Extract ALL important points from the segment above. Be exhaustive.

## 1. Topics and Key Points
- [point] (who said it, if clear)

## 2. Decisions and Agreements
- ...

## 3. Numbers, Dates, Deadlines
- [value] — [context]

## 4. Action Items
- [Who] → [what will do] (deadline)

## 5. Open Questions
- ...

IMPORTANT: Write only what is in the text, but capture every important point. If there's no information for a section, write "—"."""

CALL_AGGREGATION_PROMPT = """Combine points from {n_chunks} parts of the call into one complete record.

EXTRACTED POINTS:
\"\"\"
{extracted_facts}
\"\"\"

Final call record:

## 1) Participants and Roles
- ...

## 2) Topics Discussed
- ...

## 3) Key Points and Statements
- ...

## 4) Decisions and Agreements
- ...

## 5) Numbers, Dates, Deadlines
- [value] — [context]

## 6) Open Questions
- ...

## 7) Action Items
|| Action | Responsible | Deadline |
||--------|-------------|----------|
|| ... | ... | ... |

IMPORTANT: Merge duplicates across parts, but do not lose any important point, number, or date."""

# =============================================================================
# PRESETS DICTIONARY
# =============================================================================

PRESETS: Dict[str, Dict[str, Any]] = {
    "pm": {
        "name_key": "preset_pm_name",
        "description_key": "preset_pm_desc",
        "prompts": {
            "system": PM_SYSTEM_PROMPT,
            "short": PM_SHORT_PROMPT,
            "extraction": PM_EXTRACTION_PROMPT,
            "aggregation": PM_AGGREGATION_PROMPT,
        }
    },
    "student": {
        "name_key": "preset_student_name",
        "description_key": "preset_student_desc",
        "prompts": {
            "system": STUDENT_SYSTEM_PROMPT,
            "short": STUDENT_SHORT_PROMPT,
            "extraction": STUDENT_EXTRACTION_PROMPT,
            "aggregation": STUDENT_AGGREGATION_PROMPT,
        }
    },
    "generic": {
        "name_key": "preset_generic_name",
        "description_key": "preset_generic_desc",
        "prompts": {
            "system": GENERIC_SYSTEM_PROMPT,
            "short": GENERIC_SHORT_PROMPT,
            "extraction": GENERIC_EXTRACTION_PROMPT,
            "aggregation": GENERIC_AGGREGATION_PROMPT,
        }
    },
    "call": {
        "name_key": "preset_call_name",
        "description_key": "preset_call_desc",
        "prompts": {
            "system": CALL_SYSTEM_PROMPT,
            "short": CALL_SHORT_PROMPT,
            "extraction": CALL_EXTRACTION_PROMPT,
            "aggregation": CALL_AGGREGATION_PROMPT,
        }
    },
}

# Пресет по умолчанию
DEFAULT_PRESET = "pm"


# Ключи 4 промптов в каждом пресете.
PROMPT_KEYS = ("system", "short", "extraction", "aggregation")

# ID встроенных (read-only) пресетов.
BUILTIN_PRESET_IDS = frozenset(PRESETS)


def is_builtin(preset_id: str) -> bool:
    """Встроенный пресет (нельзя удалить/переименовать)?"""
    return preset_id in PRESETS


def get_preset(preset_id: str) -> Dict[str, Any]:
    """Получить встроенный пресет по ID (fallback на дефолтный)."""
    return PRESETS.get(preset_id, PRESETS[DEFAULT_PRESET])


def get_preset_prompts(preset_id: str, user_presets: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Получить 4 промпта пресета. Сначала ищем среди пользовательских (user_presets),
    затем среди встроенных. Недостающие ключи добиваются дефолтным пресетом.
    """
    base = PRESETS[DEFAULT_PRESET]["prompts"]
    if user_presets and preset_id in user_presets:
        up = user_presets.get(preset_id) or {}
        prompts = up.get("prompts", {}) if isinstance(up, dict) else {}
        # Добиваем дефолтом только ОТСУТСТВУЮЩИЕ ключи; намеренно пустой промпт ("") сохраняем.
        return {k: (prompts[k] if k in prompts else base.get(k, "")) for k in PROMPT_KEYS}
    preset = get_preset(preset_id)
    return preset.get("prompts", {})


def get_preset_list() -> list:
    """Список встроенных пресетов для UI (id + ключи перевода имени/описания)."""
    return [
        {
            "id": preset_id,
            "name_key": preset["name_key"],
            "description_key": preset["description_key"],
        }
        for preset_id, preset in PRESETS.items()
    ]
