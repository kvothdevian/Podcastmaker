import os
import json
import time
import re
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load .env file relative to script location
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

MODELS = [
    {"provider": "openrouter", "id": "meta-llama/llama-3.3-70b-instruct:free"},
    {"provider": "groq", "id": "llama-3.3-70b-versatile"},
    {"provider": "openrouter", "id": "nousresearch/hermes-3-llama-3.1-405b:free"},
    {"provider": "groq", "id": "llama-3.1-8b-instant"},
    {"provider": "openrouter", "id": "deepseek/deepseek-v4-flash:free"},
    {"provider": "groq", "id": "mixtral-8x7b-32768"},
    {"provider": "openrouter", "id": "openrouter/free"},
    {"provider": "groq", "id": "gemma2-9b-it"},
]

_call_counter = 0

COMMON_OPENING = "You're listening to The Essayist - where the ideas that shaped the world finally get the conversation they deserve."

# --- SYSTEM PROMPTS ---

UNBIASED_REPRESENTATION_RULES = """
CRITICAL NON-CENSORSHIP & UNFILTERED PRESENTATION REQUIREMENT:
- DO NOT censor, dilute, sanitize, or alter the author's original views, arguments, or conclusions under any circumstances, even if they are highly controversial, offensive, politically incorrect, or run contrary to modern sensibilities.
- DO NOT add modern moralizing, caveats, disclaimers, or apologetic context (e.g., do not say "of course, we know this is outdated today" or "by modern standards, this is highly problematic"). 
- DO NOT try to balance the author's views by presenting a modern 'both sides' debate or trying to make the author's views conform to contemporary norms.
- Represent the author's perspective directly, rawly, and unfiltered. Let the author's voice and arguments stand exactly as they were written.
- The hosts must discuss the ideas from the perspective of understanding the author's internal logic, not from a perspective of modern judgment, condescension, or moral superiority. Do not apologize for the author.
"""

DIGEST_PROMPT = UNBIASED_REPRESENTATION_RULES + """You are a philosophical researcher. Your task is to analyze a classical essay and create a comprehensive structural digest.
DO NOT summarize - instead, MAP the logic. Identify every major argument, every nuance, and every controversial pivot point.
Your output will be used to generate a 25-to-30-minute podcast script, so ensure NO detail is missed.

Return a Bulleted List of the essay's logical progression."""

JSON_FORMAT_RULES = """
OUTPUT FORMAT:
You MUST respond with a valid JSON array of objects representing dialogue turns. Do not include any other markdown decoration or wrapping (like ```json ... ```) outside the JSON array.
Each object in the array MUST have exactly these four keys:
1. "speaker": Either "MARCUS" or "JULIAN"
2. "dialogue": The text for the speaker. Both hosts should have substantial, balanced dialogue turns (Marcus: 50-80 words, Julian: 70-110 words) to create a natural, flowing conversation.
3. "intent": One of "inquisitive", "reflective", "excited", "serious", or "default"
4. "active_listening_cue": Always null. DO NOT use active listening cues.

Example output:
[
  {"speaker": "MARCUS", "dialogue": "You're listening to The Essayist - where the ideas that shaped the world finally get the conversation they deserve.", "intent": "excited", "active_listening_cue": null},
  {"speaker": "JULIAN", "dialogue": "Welcome, Marcus. Today, we are exploring a deeply challenging essay.", "intent": "reflective", "active_listening_cue": null}
]
"""

MONOLOGUE_WITH_INTERJECTIONS_PROMPT = UNBIASED_REPRESENTATION_RULES + """You are writing for "The Essayist" podcast. 
Two hosts with balanced, peer-to-peer intellectual roles:
1. MARCUS: Co-host. Focuses heavily on the author's biography, the historical context, contemporary reception, intellectual influences, and the real-world implications or criticisms of the essay's arguments.
2. JULIAN: Co-host. Focuses heavily on direct textual analysis, explaining the internal logic of the arguments, and how the essay fits into the author's broader system of thought.

NARRATIVE ARCHETYPE: Co-Host Debate & Editorial Review
- The hosts are intellectual equals who have both thoroughly read and analyzed the essay.
- They engage in a dynamic, organic dialogue, building on each other's points, adding historical context, and exploring the logic together.
- DO NOT use a rigid teacher-student or Q&A format. Avoid Marcus just asking brief questions and Julian giving long lectures. Instead, they share the floor, discussing the essay like seasoned colleagues.
- Marcus sets the stage in the intro, introduces the author/essay, and then Julian and Marcus analyze the ideas together.
- Marcus finishes the episode with a Listener Challenge in the outro.
- Both hosts must remain entirely objective, avoiding modern moralizing or apologizing for the author.

CONVERSATIONAL NATURALNESS & NAME-CALLING CONSTRAINTS:
- The dialogue must feel organic, warm, and natural.
- CRITICAL NAME-CALLING CONSTRAINT: The hosts must NOT repeat each other's names in every turn. In real life, friends and colleagues rarely use each other's names during a conversation. Limit direct name-calling to at most 3-4 times per segment (mainly during the intro, outro, or major topic transitions). DO NOT prefix or suffix turns with names unnecessarily.
- Each host must validate and build on the other's comments naturally (e.g., "That aligns perfectly with...", "Exactly, and if you look at the text...", "That biography detail explains why he writes that...").
""" + JSON_FORMAT_RULES

# Max chars sent to LLM - using larger context if available
MAX_ESSAY_CHARS = 24000 

def call_openrouter(messages: list, model: str, max_tokens: int = 4000, usage_log: dict = None) -> str:
    """Helper to call OpenRouter API."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://the-essayist-podcast.com",
        "X-Title": "The Essayist Podcast",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=45)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        err_msg = data["error"].get("message", "Unknown error")
        code = data["error"].get("code", "unknown")
        raise RuntimeError(f"OpenRouter Error {code}: {err_msg}")
        
    try:
        content = data["choices"][0]["message"]["content"]
        if content is None or (isinstance(content, str) and content.strip() == "") or str(content).strip().lower() == "none":
            raise ValueError("Empty or 'None' content returned from model")
            
        if not isinstance(content, str):
            print(f"  Warning: Expected string content, got {type(content)}. Data: {str(data)[:500]}")
            content = str(content).strip()
        else:
            content = content.strip()
            
        if usage_log is not None:
            usage = data.get("usage", {})
            p_stats = usage_log.setdefault("provider_stats", {}).setdefault("openrouter", {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            p_stats["calls"] += 1
            p_stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
            p_stats["completion_tokens"] += usage.get("completion_tokens", 0)
            
            usage_log["prompt_tokens"] = usage_log.get("prompt_tokens", 0) + usage.get("prompt_tokens", 0)
            usage_log["completion_tokens"] = usage_log.get("completion_tokens", 0) + usage.get("completion_tokens", 0)
            
        return content
    except (KeyError, IndexError) as e:
        print(f"  Error parsing OpenRouter response: {e}. Data: {str(data)[:1000]}")
        raise

def call_groq(messages: list, model: str, max_tokens: int = 4000, usage_log: dict = None) -> str:
    """Helper to call Groq API."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    
    # Cap max_tokens to 2048 for models other than llama-3.3-70b-versatile to avoid Groq 400/413 errors
    if model != "llama-3.3-70b-versatile":
        max_tokens = min(max_tokens, 2048)
        
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=45)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        err_msg = data["error"].get("message", "Unknown error")
        code = data["error"].get("code", "unknown")
        raise RuntimeError(f"Groq Error {code}: {err_msg}")
        
    try:
        content = data["choices"][0]["message"]["content"]
        if content is None or (isinstance(content, str) and content.strip() == "") or str(content).strip().lower() == "none":
            raise ValueError("Empty or 'None' content returned from model")
            
        if not isinstance(content, str):
            print(f"  Warning: Expected string content, got {type(content)}. Data: {str(data)[:500]}")
            content = str(content).strip()
        else:
            content = content.strip()
            
        if usage_log is not None:
            usage = data.get("usage", {})
            p_stats = usage_log.setdefault("provider_stats", {}).setdefault("groq", {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            p_stats["calls"] += 1
            p_stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
            p_stats["completion_tokens"] += usage.get("completion_tokens", 0)
            
            usage_log["prompt_tokens"] = usage_log.get("prompt_tokens", 0) + usage.get("prompt_tokens", 0)
            usage_log["completion_tokens"] = usage_log.get("completion_tokens", 0) + usage.get("completion_tokens", 0)
            
        return content
    except (KeyError, IndexError) as e:
        print(f"  Error parsing Groq response: {e}. Data: {str(data)[:1000]}")
        raise

def text_to_json_turns(text: str) -> list:
    """Converts a legacy plain text script into the new JSON turn structure as a fallback."""
    turns = []
    pattern = re.compile(r'(?:\[|\*\*\[?)(MARCUS|JULIAN|HOST|NARRATOR)(?:\]|\*?\]?)\s*:', re.IGNORECASE)
    matches = list(pattern.finditer(text))
    
    if not matches:
        return [{"speaker": "MARCUS", "dialogue": text, "intent": "default", "active_listening_cue": None}]
        
    first_match = matches[0]
    if first_match.start() > 0:
        pre_text = text[:first_match.start()].strip()
        pre_text = re.sub(r'\[/?.+?\]', '', pre_text)
        pre_text = re.sub(r'\*\*', '', pre_text)
        pre_text = pre_text.strip()
        if pre_text and any(c.isalnum() for c in pre_text):
            turns.append({"speaker": "MARCUS", "dialogue": pre_text, "intent": "default", "active_listening_cue": None})
            
    for i in range(len(matches)):
        m = matches[i]
        raw_speaker = next(g for g in m.groups() if g is not None).upper()
        speaker = 'MARCUS' if raw_speaker in ('MARCUS', 'HOST') else 'JULIAN'
        
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        
        turn_text = text[start:end].strip()
        turn_text = re.sub(r'\[/?.+?\]', '', turn_text)
        turn_text = re.sub(r'\*\*', '', turn_text)
        turn_text = turn_text.strip()
        
        if turn_text and any(c.isalnum() for c in turn_text):
            turns.append({"speaker": speaker, "dialogue": turn_text, "intent": "default", "active_listening_cue": None})
            
    return turns

def parse_malformed_json_turns(text: str) -> list:
    """Extracts dialogue turns using regex if the JSON is malformed."""
    turns = []
    obj_pattern = re.compile(r'\{[^{}]*\}')
    
    speaker_pattern = re.compile(r'"speaker"\s*:\s*"([^"]+)"', re.IGNORECASE)
    dialogue_pattern = re.compile(r'"dialogue"\s*:\s*"((?:[^"\\]|\\.)*)"', re.IGNORECASE)
    intent_pattern = re.compile(r'"intent"\s*:\s*"([^"]+)"', re.IGNORECASE)
    cue_pattern = re.compile(r'"active_listening_cue"\s*:\s*(?:"([^"]+)"|null)', re.IGNORECASE)
    
    for match in obj_pattern.finditer(text):
        obj_text = match.group(0)
        s_match = speaker_pattern.search(obj_text)
        d_match = dialogue_pattern.search(obj_text)
        
        if s_match and d_match:
            speaker = s_match.group(1).upper()
            dialogue = d_match.group(1)
            try:
                dialogue = json.loads(f'"{dialogue}"')
            except Exception:
                pass
                
            intent = "default"
            i_match = intent_pattern.search(obj_text)
            if i_match:
                intent = i_match.group(1).lower()
                
            cue = None
            c_match = cue_pattern.search(obj_text)
            if c_match and c_match.group(1):
                cue = c_match.group(1).lower()
                
            turns.append({
                "speaker": speaker,
                "dialogue": dialogue,
                "intent": intent,
                "active_listening_cue": cue
            })
            
    return turns

def clean_and_parse_json(text: str) -> list:
    """Extracts and parses a JSON list of dialogue turns from LLM text."""
    text_clean = text.strip()
    
    # Strip markdown code blocks if present
    if "```" in text_clean:
        parts = text_clean.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("[") and part.endswith("]"):
                text_clean = part
                break
                
    start = text_clean.find('[')
    end = text_clean.rfind(']')
    if start != -1 and end != -1 and end > start:
        json_str = text_clean[start:end+1]
        try:
            return json.loads(json_str)
        except Exception as e:
            print(f"  Warning: JSON parsing failed: {e}. Attempting malformed JSON regex fallback.")
            turns = parse_malformed_json_turns(text)
            if turns:
                return turns
            print("  Warning: Regex fallback failed. Attempting legacy plain text fallback.")
            
    return text_to_json_turns(text)

def generate_script(essay_text: str, essay_title: str, author: str, usage_log: dict, episode_num: int = 1, historical_context: str = "") -> tuple[str, str]:
    """
    Generate a 3-segment monologue-with-interjections style script and JSON structured outputs.
    Total word count target: ~5,500 words.
    """
    # Step 1: Digest
    digest = robust_llm_call(
        "Mapping logical structure",
        DIGEST_PROMPT,
        f"Essay: {essay_title} by {author}\n\n{essay_text[:MAX_ESSAY_CHARS]}",
        max_tokens=2000,
        usage_log=usage_log
    )
    
    archetype_name = "Monologue with Asymmetrical Interjections"
    system_prompt = MONOLOGUE_WITH_INTERJECTIONS_PROMPT
        
    print(f"  Selected Archetype: {archetype_name}")
    
    # Format context string
    context_str = ""
    if historical_context:
        context_str = f"Historical/Biographical Context (capped at 400 words):\n{historical_context}\n\n"
    
    # Step 2: Segment A
    print("  Generating Segment A (Intro + Foundation)...")
    prompt_a = f"""Write SEGMENT A of the podcast.
Essay: {essay_title} by {author}
{context_str}Full Logic Digest:
{digest}

Target: ~1800 words. Focus on the introduction, historical/biographical context, and the essay's core thesis and foundation.
Marcus must start the script with the exact opening statement: "{COMMON_OPENING}" and introduce Julian.
Marcus and Julian must introduce themselves by name naturally in the intro (e.g., Marcus says "I'm Marcus" and Julian says "And I'm Julian").
They must engage in a balanced, peer-to-peer discussion: Marcus focused on biographical/historical details, and Julian on the core philosophical thesis.
Both hosts should have substantial, balanced dialogue turns: Marcus (50-80 words per turn) and Julian (70-110 words per turn) in an active back-and-forth.
Avoid having Marcus ask simple questions or speak in short, snappy interjections. They are equal partners.
Remember the Name-Calling Constraint: Limit direct name-calling to at most 3-4 times in this segment.
Remember to return ONLY a valid JSON array of objects conforming to the format specified in system instructions."""

    segment_a_raw = robust_llm_call(
        "Segment A",
        system_prompt,
        prompt_a,
        max_tokens=4000,
        usage_log=usage_log
    )
    turns_a = clean_and_parse_json(segment_a_raw)

    # Step 3: Segment B
    print("  Generating Segment B (Deep Dive)...")
    segment_a_context = json.dumps(turns_a[-10:], indent=2)
    prompt_b = f"""Now write SEGMENT B.
Essay: {essay_title} by {author}
{context_str}Full Logic Digest:
{digest}

PREVIOUS SEGMENT CONTEXT (last 10 turns):
{segment_a_context}

Target: ~1800 words. Resume precisely where Segment A left off.
Focus on unpacking the primary arguments, nuances, and critical/controversial pivot points of the essay.
They must engage in a balanced, peer-to-peer discussion: Marcus focused on historical context/reception/relevance, and Julian on the textual analysis and logical arguments.
Both hosts should have substantial, balanced dialogue turns: Marcus (50-80 words per turn) and Julian (70-110 words per turn) in an active back-and-forth.
Do NOT use a teacher-student Q&A format. They are equal partners exploring the ideas together.
Do NOT repeat the intro.
Remember the Name-Calling Constraint: Limit direct name-calling to at most 3-4 times in this segment.
Remember to return ONLY a valid JSON array of objects conforming to the format specified in system instructions."""

    segment_b_raw = robust_llm_call(
        "Segment B",
        system_prompt,
        prompt_b,
        max_tokens=4000,
        usage_log=usage_log
    )
    turns_b = clean_and_parse_json(segment_b_raw)

    # Step 4: Segment C
    print("  Generating Segment C (Modern Parallels + Outro)...")
    segment_b_context = json.dumps(turns_b[-10:], indent=2)
    prompt_c = f"""Now write SEGMENT C.
Essay: {essay_title} by {author}
{context_str}Full Logic Digest:
{digest}

PREVIOUS SEGMENT CONTEXT (last 10 turns):
{segment_b_context}

Target: ~1900 words. Resume precisely where Segment B left off.
Focus on the deeper philosophical roots, contemporary reception/intellectual influences, and the final outro.
They must engage in a balanced, peer-to-peer discussion: Marcus focused on biographical/intellectual influences and real-world implications, and Julian on the textual analysis and system of thought.
Both hosts should have substantial, balanced dialogue turns: Marcus (50-80 words per turn) and Julian (70-110 words per turn) in an active back-and-forth.
Marcus must conclude the segment with the final Outro and a Listener Challenge.
Do NOT repeat the intro.
CRITICAL OUTRO CONSTRAINT: Do NOT include any call-to-action telling listeners to write to, email, or visit a website (specifically, do not mention 'write to us at essayistpodcast.com' or any email address/URL). The outro should end purely with the Listener Challenge.

CRITICAL CONTEXT & BOTH-SIDING CONSTRAINT:
- Limit modern comparisons, parallels, 'both-siding', disclaimers, or modern moralizing context to at most 10% of this segment/script.
- Do NOT decrease the word count of the segment (~1900 words).
- Spend 90% of the segment/monologues exploring:
  1. The deeper philosophical root of the author's arguments and how they connect to their broader philosophical framework or system.
  2. The historical context, contemporary reception, and intellectual influences on the author's thinking.
  3. A detailed textual analysis of the essay's arguments, letting the author's voice and ideas stand raw, uncensored, and unfiltered.

Remember the Name-Calling Constraint: Limit direct name-calling to at most 3-4 times in this segment.
Remember to return ONLY a valid JSON array of objects conforming to the format specified in system instructions."""

    segment_c_raw = robust_llm_call(
        "Segment C",
        system_prompt,
        prompt_c,
        max_tokens=4000,
        usage_log=usage_log
    )
    turns_c = clean_and_parse_json(segment_c_raw)

    # Combine dialogue lists
    combined_turns = turns_a + turns_b + turns_c

    # Post-processing scrub: remove any "write to us at essayistpodcast.com" or website call-to-actions
    for turn in combined_turns:
        if "dialogue" in turn and isinstance(turn["dialogue"], str):
            dialogue = turn["dialogue"]
            # Match variants of "write to us at (the)essayistpodcast.com"
            cleaned = re.sub(
                r'(?i)(?:and\s+)?(?:please\s+)?(?:write|email|reach\s+out|send\s+your\s+thoughts|visit)\s+to\s+us\s+at\s+(?:https?://)?(?:www\.)?(?:the)?essayistpodcast\.com\b\.?',
                '',
                dialogue
            )
            # Match variants of "write to us at essayistpodcast dot com"
            cleaned = re.sub(
                r'(?i)(?:and\s+)?(?:please\s+)?(?:write|email|reach\s+out|send\s+your\s+thoughts|visit)\s+to\s+us\s+at\s+(?:the)?\s*essayist\s*podcast\s*(?:dot\s*com)?\b\.?',
                '',
                cleaned
            )
            # Match standalone domain mentions
            cleaned = re.sub(
                r'(?i)\b(?:the)?essayistpodcast\.com\b',
                '',
                cleaned
            )
            # Clean up residual multiple spaces/punctuation artifacts
            cleaned = re.sub(r'\s+', ' ', cleaned)
            cleaned = cleaned.replace(' .', '.').replace(' ,', ',').strip()
            turn["dialogue"] = cleaned

    full_script = json.dumps(combined_turns, indent=2)
    
    usage_log["model_used"] = "Multi-Model Fallback"
    usage_log["segments"] = 3
    
    return full_script, f"OpenRouter Multi-Model ({archetype_name})"


def robust_llm_call(step_name: str, system_prompt: str, user_prompt: str, max_tokens: int = 4000, usage_log: dict = None) -> str:
    """Helper to perform an LLM call with model-level fallbacks."""
    global _call_counter
    preferred = "openrouter" if _call_counter % 2 == 0 else "groq"
    _call_counter += 1
    
    # Separate openrouter and groq models
    or_models = [m for m in MODELS if m["provider"] == "openrouter"]
    groq_models = [m for m in MODELS if m["provider"] == "groq"]
    
    # Interleave starting with the preferred provider
    ordered_models = []
    first_list = or_models if preferred == "openrouter" else groq_models
    second_list = groq_models if preferred == "openrouter" else or_models
    
    for i in range(max(len(first_list), len(second_list))):
        if i < len(first_list):
            ordered_models.append(first_list[i])
        if i < len(second_list):
            ordered_models.append(second_list[i])
            
    last_tried_provider = None
    for model_idx, model_cfg in enumerate(ordered_models):
        provider = model_cfg["provider"]
        model_id = model_cfg["id"]
        
        # Only sleep if we are falling back to a model on the SAME provider to let rate limits cool down
        if model_idx > 0 and last_tried_provider == provider:
            print(f"    [Cooldown] Falling back to another model on the same provider ({provider}). Sleeping 10s...")
            time.sleep(10)
            
        print(f"    [{step_name}] Trying model: {model_id} (via {provider})")
        last_tried_provider = provider
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            if provider == "openrouter":
                return call_openrouter(messages, model_id, max_tokens=max_tokens, usage_log=usage_log)
            elif provider == "groq":
                return call_groq(messages, model_id, max_tokens=max_tokens, usage_log=usage_log)
            else:
                raise ValueError(f"Unknown provider: {provider}")
        except Exception as e:
            print(f"    [{step_name}] Error with {model_id} (via {provider}): {e}")
            if usage_log is not None:
                usage_log["fallbacks_triggered"] = usage_log.get("fallbacks_triggered", 0) + 1
            # Wait 5 seconds to let rate limits refresh before trying the next fallback model
            time.sleep(5)
            # Move immediately to the next model
            continue
            
    raise RuntimeError(f"All models failed for step: {step_name}")


def get_author_last_name(author: str) -> str:
    if not author or author.strip() == "Unknown Author":
        return "Unknown"
    # Check if format is "Last, First"
    if "," in author:
        return author.split(",")[0].strip()
    # Otherwise assume "First Last"
    parts = author.split()
    if parts:
        return parts[-1].strip()
    return author.strip()


def generate_metadata_text(essay_title: str, author: str, essay_summary: str, usage_log: dict) -> dict:
    """Use a cheap LLM call to generate Spotify-ready title, description, and tags."""
    prompt = f"""Generate Spotify podcast metadata for The Essayist podcast.

Essay: "{essay_title}" by {author}
Summary: {essay_summary[:500]}

Return ONLY valid JSON in this exact format (no other text):
{{
  "episode_title": "Under 60 chars. Start with author's name or core concept keyword.",
  "description": "150-word SEO description. First sentence must contain the philosopher's name and essay topic. Natural language.",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}

CRITICAL JSON RULES:
1. Do NOT use double quotes inside string values. If you need to quote a title or phrase inside a string, use single quotes (e.g. 'Self-Reliance').
2. Ensure the JSON is perfectly valid and can be parsed by Python's json.loads()."""

    try:
        temp_log = {}
        raw = robust_llm_call(
            step_name="Metadata",
            system_prompt="You are a podcast metadata generator. You MUST return valid JSON matching the user's requested format. Crucial: Do NOT use double quotes inside string values; use single quotes instead to ensure valid JSON.",
            user_prompt=prompt,
            max_tokens=500,
            usage_log=temp_log
        )

        # Extract JSON from potential markdown code block
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        metadata = json.loads(raw.strip())

        # Sync back token counts
        if usage_log is not None:
            usage_log["metadata_tokens"] = temp_log.get("prompt_tokens", 0) + temp_log.get("completion_tokens", 0)
            usage_log["prompt_tokens"] = usage_log.get("prompt_tokens", 0) + temp_log.get("prompt_tokens", 0)
            usage_log["completion_tokens"] = usage_log.get("completion_tokens", 0) + temp_log.get("completion_tokens", 0)
            usage_log["fallbacks_triggered"] = usage_log.get("fallbacks_triggered", 0) + temp_log.get("fallbacks_triggered", 0)
            
            # Merge provider stats
            if "provider_stats" in temp_log:
                for prov, stats in temp_log["provider_stats"].items():
                    target = usage_log.setdefault("provider_stats", {}).setdefault(prov, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
                    target["calls"] += stats.get("calls", 0)
                    target["prompt_tokens"] += stats.get("prompt_tokens", 0)
                    target["completion_tokens"] += stats.get("completion_tokens", 0)

        return metadata
    except Exception as e:
        print(f"  Metadata generation failed with all models: {e}")

    # Fallback: return basic metadata using the correct title format
    author_last = get_author_last_name(author)
    essay_title_clean = essay_title.title().strip()
    return {
        "episode_title": f"{author_last} - {essay_title_clean} -",
        "description": f"In this episode of The Essayist, we explore {essay_title} by {author}. A deep dive into the ideas that shaped intellectual history.",
        "tags": ["philosophy", "classical essays", author_last.lower(), "Stoicism", "ideas"],
    }
