import os
import asyncio
import re
import json
import hashlib
import edge_tts

HOST_VOICE = os.getenv("HOST_VOICE", "en-US-BrianNeural")
NARRATOR_VOICE = os.getenv("NARRATOR_VOICE", "en-US-AndrewNeural")

def parse_script(script: str) -> list[dict]:
    """
    Parse the script. 
    If script is a valid JSON array, loads and returns it.
    Otherwise, parses plain text script and returns dialogue turn objects.
    """
    try:
        data = json.loads(script)
        if isinstance(data, list):
            turns = []
            for item in data:
                if isinstance(item, dict) and "speaker" in item and "dialogue" in item:
                    turns.append({
                        "speaker": item["speaker"].upper(),
                        "dialogue": item["dialogue"],
                        "intent": item.get("intent", "default"),
                        "active_listening_cue": item.get("active_listening_cue", None)
                    })
            return turns
    except Exception:
        pass
        
    # Fallback to legacy parsing if script is plain text
    from script_generator import text_to_json_turns
    return text_to_json_turns(script)

PRONUNCIATION_MAP = {
    # German Philosophers - Simplified to avoid pauses
    r"Schopenhauer": "Showpenhower",
    r"Nietzsche": "Kneeche",
    r"Heidegger": "Hideger",
    r"Wittgenstein": "Vitgenstine",
    r"Goethe": "Gerteh",
}

def apply_pronunciation_fixes(text: str) -> str:
    """Apply phonetic replacements for difficult names."""
    fixed_text = text
    for pattern, replacement in PRONUNCIATION_MAP.items():
        fixed_text = re.sub(rf'\b{pattern}\b', replacement, fixed_text, flags=re.IGNORECASE)
    return fixed_text

def calculate_turn_hash(speaker: str, text: str, voice: str, intent: str) -> str:
    """Calculate MD5 hash of dialogue parameters for caching."""
    payload = f"{speaker}|{text}|{voice}|{intent}"
    return hashlib.md5(payload.encode('utf-8')).hexdigest()

async def text_to_wav(text: str, voice: str, output_path: str, intent: str = "default"):
    """Convert text to WAV using Edge TTS with dynamic rate and pitch based on intent."""
    fixed_text = apply_pronunciation_fixes(text)
    
    # Base rate adjustments based on intent and voice
    rate_val = 0
    if intent == "excited":
        rate_val = 8
    elif intent == "reflective":
        rate_val = -3
    elif intent == "serious":
        rate_val = -1
        
    # Slight speed boost for Marcus / Julian baselines
    if "Andrew" in voice or "Brian" in voice:
        rate_val += 3
        
    rate_sign = "+" if rate_val >= 0 else ""
    rate = f"{rate_sign}{rate_val}%"
    pitch = "+0Hz"
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            communicate = edge_tts.Communicate(text=fixed_text, voice=voice, rate=rate, pitch=pitch)
            await asyncio.wait_for(communicate.save(output_path), timeout=20.0)
            return # Success
        except Exception as e:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Edge TTS failed after {max_retries} attempts: {e}")
            print(f"    TTS failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in 2s...")
            await asyncio.sleep(2)

async def generate_turns_async(turns: list[dict], temp_dir: str) -> list[dict]:
    """Generates audio files for all turns concurrently, utilizing an MD5 cache."""
    semaphore = asyncio.Semaphore(5)  # Limit concurrent Edge TTS requests to 5 to avoid connection errors
    
    async def sem_text_to_wav(text: str, voice: str, path: str, intent: str):
        async with semaphore:
            await text_to_wav(text, voice, path, intent)

    tasks = []
    updated_turns = []
    
    for i, turn in enumerate(turns):
        speaker = turn["speaker"]
        text = turn["dialogue"]
        intent = turn["intent"]
        voice = HOST_VOICE if speaker == 'MARCUS' else NARRATOR_VOICE
        
        # Calculate MD5 hash and cache file path
        turn_hash = calculate_turn_hash(speaker, text, voice, intent)
        filename = f"turn_{i:03d}_{speaker.lower()}_{turn_hash}.mp3"
        path = os.path.join(temp_dir, filename)
        
        turn_copy = dict(turn)
        turn_copy["audio_path"] = path
        turn_copy["hash"] = turn_hash
        updated_turns.append(turn_copy)
        
        # If cache file exists, skip calling TTS
        if os.path.exists(path) and os.path.getsize(path) > 0:
            continue
            
        # Clean up any outdated files for this turn index
        for old_file in os.listdir(temp_dir):
            if old_file.startswith(f"turn_{i:03d}_") and old_file != filename:
                try:
                    os.remove(os.path.join(temp_dir, old_file))
                except Exception:
                    pass
                    
        tasks.append(sem_text_to_wav(text, voice, path, intent))
        
    if tasks:
        print(f"    Rendering {len(tasks)} new speech segments concurrently (concurrency limit: 5)...")
        await asyncio.gather(*tasks)
    else:
        print("    All speech segments found in cache. Skipping TTS generation.")
        
    return updated_turns

def generate_audio_segments(script: str, temp_dir: str = "temp") -> list[dict]:
    """
    Generate MP3 files for each dialogue turn concurrently.
    Returns a list of turn dicts containing paths.
    """
    os.makedirs(temp_dir, exist_ok=True)
    turns = parse_script(script)
    
    print(f"  Generating audio for {len(turns)} dialogue turns...")
    updated_turns = asyncio.run(generate_turns_async(turns, temp_dir))
            
    return updated_turns

def count_words(script: str) -> dict:
    """Count words per speaker."""
    turns = parse_script(script)
    word_counts = {'MARCUS': 0, 'JULIAN': 0}
    for turn in turns:
        speaker = turn["speaker"]
        text = turn["dialogue"]
        word_counts[speaker] = word_counts.get(speaker, 0) + len(text.split())
    return word_counts
