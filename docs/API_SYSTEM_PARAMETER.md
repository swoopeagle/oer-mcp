# API: System Parameter Guide

All OER MCP tools that query content or standards now support an optional `system` parameter to target specific curriculum frameworks. This allows a single integration to work seamlessly across CCSS, AP Courses, state standards, and other frameworks.

## Overview

**The `system` parameter** specifies which curriculum framework to query. Default is `"ccss"` (Common Core State Standards for Mathematics) for backward compatibility.

```
system: str = "ccss"  # default; can be any valid standard system
```

Available systems are listed in `get_capabilities()` response.

## Tools that support `system`

### Core retrieval tools

#### `fetch_for_standard(standard_id: str, system: str = "ccss") -> dict`

Fetch OER content aligned to a standard ID, ranked by alignment confidence.

**Parameters:**
- `standard_id` (str): Standard ID in the format of the specified system (e.g., `"CCSS.MATH.6.RP.3"` or `"AP.AP_BIO.2.1.A"`)
- `system` (str, optional): Curriculum system. Default: `"ccss"`. Examples: `"ap-bio"`, `"ap-us-gov"`, `"c3"`

**Example: Math (CCSS)**
```
fetch_for_standard("CCSS.MATH.6.RP.3")
# Implicit: system="ccss"
```

**Example: Biology (AP)**
```
fetch_for_standard("AP.AP_BIO.2.1.A", system="ap-bio")
```

**Example: Social Studies (AP Government)**
```
fetch_for_standard("AP.AP_US_GOV.2.A", system="ap-us-gov")
```

---

#### `check_coverage(standard_id: str, system: str = "ccss") -> dict`

Report how completely the corpus covers a standard or cluster, with gap detection.

Returns coverage bands (strong/moderate/light/none) and surfaces gaps — standards with no aligned content.

**Parameters:**
- `standard_id` (str): Standard ID or cluster prefix (e.g., `"CCSS.MATH.6.RP"` for all Grade 6 Ratios & Proportional Relationships standards)
- `system` (str, optional): Curriculum system. Default: `"ccss"`

**Example: Coverage in AP Chemistry**
```
check_coverage("AP.AP_CHEM.1", system="ap-chem")
# Returns coverage bands for all AP Chemistry Big Idea 1 standards
# plus any gaps (standards with zero aligned content)
```

**Example: Coverage in C3 Framework**
```
check_coverage("C3.D2.Civ", system="c3")
# Returns coverage for Civics domain in the C3 Framework
```

---

#### `get_learning_path(standard_id: str, system: str = "ccss", depth: int = 1) -> dict`

Prerequisite-aware learning path: walks StandardGraph's prerequisite graph and attaches OER content per rung.

**Parameters:**
- `standard_id` (str): Target standard ID
- `system` (str, optional): Curriculum system. Default: `"ccss"`
- `depth` (int, optional): How many prerequisite levels to walk. Default: `1`
- `content_per_standard` (int, optional): Max chunks per standard. Default: `2`
- `include_content` (bool, optional): Include full content text. Default: `False`

**Example: Learning path for AP US Government**
```
get_learning_path("AP.AP_US_GOV.2.A", system="ap-us-gov", depth=2)
# Returns:
# - Prerequisite standards (up to 2 levels back)
# - OER content for each prerequisite
# - Target standard content
# - Gaps (prerequisites with no content)
```

---

### Search & retrieval tools

#### `search_content(query: str) -> dict`

Natural-language concept search across all subjects (math, science, social studies).

Currently **system-agnostic** — searches across all indexed content regardless of system. Returns results ranked by semantic + keyword relevance.

**Note:** Future versions may add optional `system` filtering to scope searches.

**Example:**
```
search_content("cellular respiration")
# Returns biology/chemistry content teaching this concept, ranked by relevance
```

---

#### `get_chunk(chunk_id: str) -> dict`

Retrieve a specific content chunk by ID, with neighbors and all standard alignments.

Returns alignments across all systems the chunk has been aligned to.

**Example:**
```
get_chunk("openstax-biology-ap-courses-m62717-expo2")
# Returns content + all alignments (ap-bio, maybe ccss, etc.)
```

---

### Metadata & capabilities

#### `list_sources() -> dict`

Live inventory of indexed sources, books, chunks, and attached databases.

System-agnostic — returns all available data.

---

#### `map_to_assessments(standard_id: str) -> dict`

Map a standard to high-stakes exams (SAT/ACT/AP/state/NAEP).

Currently works for **CCSS math standards only** (SAT/ACT/AP Calc/Stats crosswalks).

Future: will be parametrized to support AP science/social studies → exam mapping.

---

#### `get_capabilities() -> dict`

Self-describing manifest of the server's capabilities.

Includes:
- All available standard systems
- Supported exam series
- Grade bands
- Coverage statistics
- List of all 8 tools

---

## Standard system reference

| System | Description | Example ID | Type |
|---|---|---|---|
| `ccss` | Common Core State Standards (Math) | `CCSS.MATH.6.RP.3` | K–12 Math |
| `ap-bio` | AP Biology | `AP.AP_BIO.2.1.A` | HS (AP) |
| `ap-chem` | AP Chemistry | `AP.AP_CHEM.1.A.1` | HS (AP) |
| `ap-phys-1` | AP Physics 1 (algebra-based) | `AP.AP_PHYS_1.2.1` | HS (AP) |
| `ap-phys-2` | AP Physics 2 (algebra-based) | `AP.AP_PHYS_2.3.1` | HS (AP) |
| `ap-phys-c-mech` | AP Physics C: Mechanics (calculus-based) | `AP.AP_PHYS_C_MECH.1.1` | HS (AP) |
| `ap-phys-c-em` | AP Physics C: E&M (calculus-based) | `AP.AP_PHYS_C_EM.1.1` | HS (AP) |
| `ap-us-gov` | AP US Government & Politics | `AP.AP_US_GOV.2.A` | HS (AP) |
| `ap-us-history` | AP US History | `AP.AP_US_HIST.1.1` | HS (AP) |
| `ap-psych` | AP Psychology | `AP.AP_PSYCH.1.1` | HS (AP) |
| `ap-macro-econ` | AP Macroeconomics | `AP.AP_MACRO_1.1` | HS (AP) |
| `ap-micro-econ` | AP Microeconomics | `AP.AP_MICRO_1.1` | HS (AP) |
| `ap-world-history` | AP World History: Modern | `AP.AP_WORLD_HIST.1.1` | HS (AP) |
| `c3` | C3 Framework for Social Studies | `C3.D2.Civ.1.3.1` | K–12 Social Studies |

## Query examples by subject

### Mathematics (CCSS)
```
# Default — CCSS Math is the fallback
fetch_for_standard("CCSS.MATH.7.EE.4")
check_coverage("CCSS.MATH.6.RP")
get_learning_path("CCSS.MATH.8.EE.1")
```

### Biology
```
fetch_for_standard("AP.AP_BIO.2.1.A", system="ap-bio")
check_coverage("AP.AP_BIO.2", system="ap-bio")
get_learning_path("AP.AP_BIO.3.1.A", system="ap-bio", depth=2)
```

### Chemistry
```
fetch_for_standard("AP.AP_CHEM.1.A.1", system="ap-chem")
check_coverage("AP.AP_CHEM.1", system="ap-chem")
```

### US Government
```
fetch_for_standard("AP.AP_US_GOV.2.A", system="ap-us-gov")
check_coverage("AP.AP_US_GOV", system="ap-us-gov")
get_learning_path("AP.AP_US_GOV.2.A", system="ap-us-gov")
```

### C3 Framework (Social Studies)
```
fetch_for_standard("C3.D2.Civ.1.3.1", system="c3")
check_coverage("C3.D2.Civ", system="c3")
# Note: C3 coverage may be limited; system is available but not all
# domains have rich OER content yet.
```

## Error handling

**Unknown standard ID:**
If a `standard_id` doesn't exist in the requested `system`, tools return:
```json
{
  "standard_id": "INVALID.ID.1.1",
  "result": "unknown_standard"
}
```

**Unknown system:**
If `system` is not in the available systems list, the query will fail. Call `get_capabilities()` to see all available systems.

**Gap detection unavailable:**
If StandardGraph DB is not present, `check_coverage()` and `get_learning_path()` degrade gracefully:
- `check_coverage` returns only standards that have alignments (can't compute gaps)
- `get_learning_path` returns just the target standard's content (can't walk prerequisites)

Response includes `sg_available: false` to flag the degradation.

## Backward compatibility

- **Default `system="ccss"`** ensures all existing queries continue to work without modification
- **All parameters are optional** — omit `system` to query CCSS Math (the original OER MCP default)
- No breaking changes to response shapes

## Alignment confidence by system

All systems use the same confidence hierarchy, but sources vary:

| Source | Confidence | Notes |
|---|---|---|
| `human` | Highest | Verified by human reviewers (rare) |
| `publisher_guide` | High | Publisher-provided tags (e.g., IM's CCSS Addressing tags) |
| `llm_verified` | Medium | Embedding match verified by LLM to actually teach the standard |
| `embedding` | Lower | Cosine similarity match, unverified |

Tools rank results by confidence and coverage bands use this hierarchy to compute overall coverage ("strong" > "moderate" > "light" > "none").

## Future extensions

- **`system` filtering in `search_content()`** — scope semantic searches to specific frameworks
- **AP social studies + science exam mapping** — extend `map_to_assessments()` to AP courses
- **State standards** — as StandardGraph grows, OER MCP will support state-specific systems (e.g., `ca-sci`, `tx-ss`)
- **International curricula** — Cambridge IGCSE, IB, etc., as content is indexed

---

For questions or to request a new system, open an issue on [GitHub](https://github.com/swoopeagle/oer-mcp).
