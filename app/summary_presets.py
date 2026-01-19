"""
Summary prompt presets.

Each preset contains a set of 4 prompts:
- system: system prompt (role and rules)
- short: for short texts (single-stage processing)
- extraction: for extracting facts from chunks
- aggregation: for combining facts into the final summary
"""

from typing import Dict, Any

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
}

# Пресет по умолчанию
DEFAULT_PRESET = "pm"


def get_preset(preset_id: str) -> Dict[str, Any]:
    """Получить пресет по ID."""
    return PRESETS.get(preset_id, PRESETS[DEFAULT_PRESET])


def get_preset_prompts(preset_id: str) -> Dict[str, str]:
    """Получить только промпты из пресета."""
    preset = get_preset(preset_id)
    return preset.get("prompts", {})


def get_preset_list() -> list:
    """Получить список пресетов для UI (id, name, description)."""
    return [
        {
            "id": preset_id,
            "name": preset["name"],
            "description": preset["description"],
        }
        for preset_id, preset in PRESETS.items()
    ]
