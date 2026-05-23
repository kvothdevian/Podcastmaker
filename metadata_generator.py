import os
import json
import re
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

# Load .env file relative to script location
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

HOST_1_NAME = os.getenv("HOST_1_NAME", "Host 1")
HOST_2_NAME = os.getenv("HOST_2_NAME", "Host 2")
PODCAST_NAME = os.getenv("PODCAST_NAME", "The Podcast")


def generate_vtt_transcript(script_text: str, words_per_minute: int = 140, speech_start_delay: float = 0.0, turns: list[dict] = None) -> str:
    """
    Generate a WebVTT transcript from the podcast script text or turns list.
    If turns list is provided with start_time and duration keys (calculated during mixing),
    uses those exact timestamps. Otherwise, estimates timestamps based on word count.
    """
    if turns and all("start_time" in t and "duration" in t for t in turns):
        lines = ["WEBVTT", ""]
        for turn in turns:
            speaker = turn["speaker"].upper()
            dialogue = turn["dialogue"].strip()
            if not dialogue:
                continue
            start_time = turn["start_time"]
            duration = turn["duration"]
            start_ts = _seconds_to_vtt(start_time)
            end_ts = _seconds_to_vtt(start_time + duration)
            
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(f"<{speaker}>{dialogue}")
            lines.append("")
        return "\n".join(lines)

    # Fallback to estimating based on word counts
    parsed_turns = []
    try:
        data = json.loads(script_text)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "speaker" in item and "dialogue" in item:
                    parsed_turns.append((item["speaker"].upper(), item["dialogue"]))
    except Exception:
        pass

    if not parsed_turns:
        # Fallback to legacy parsing
        from audio_generator import parse_script
        parsed = parse_script(script_text)
        for turn in parsed:
            parsed_turns.append((turn["speaker"], turn["dialogue"]))

    lines = ["WEBVTT", ""]
    current_time = speech_start_delay
    words_per_second = words_per_minute / 60.0

    for speaker, dialogue in parsed_turns:
        dialogue = dialogue.strip()
        if not dialogue:
            continue
        word_count = len(dialogue.split())
        duration = word_count / words_per_second
        start_ts = _seconds_to_vtt(current_time)
        end_ts = _seconds_to_vtt(current_time + duration)
        
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(f"<{speaker}>{dialogue}")
        lines.append("")
        
        current_time += duration + 0.15 # Include turn gap

    return "\n".join(lines)


def _seconds_to_vtt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def generate_chapter_markers(script_text: str, audio_segments: list, speech_start_delay: float = 0.0, turns: list[dict] = None) -> str:
    """
    Generate Spotify-compatible chapter markers for a 15-minute dialogue.
    If turns list is provided with start_time and duration keys, uses actual audio duration.
    Otherwise, estimates timestamps based on total word count at 140 wpm.
    """
    if turns and all("start_time" in t and "duration" in t for t in turns):
        total_duration = (turns[-1]["start_time"] + turns[-1]["duration"]) - speech_start_delay
    else:
        turns_dialogue = []
        try:
            data = json.loads(script_text)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "speaker" in item and "dialogue" in item:
                        turns_dialogue.append(item["dialogue"])
        except Exception:
            pass

        if not turns_dialogue:
            # Fallback to legacy
            from audio_generator import parse_script
            parsed = parse_script(script_text)
            turns_dialogue = [t["dialogue"] for t in parsed]

        words_per_second = 140 / 60.0
        total_words = sum(len(t.split()) for t in turns_dialogue)
        total_duration = total_words / words_per_second

    def fmt(seconds):
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"({m:02d}:{s:02d})"

    chapters = [f"{fmt(0.0)} Introduction"] if speech_start_delay >= 2.0 else []
    base_start = speech_start_delay if speech_start_delay >= 2.0 else 0.0

    chapters.extend([
        f"{fmt(base_start)} Episode Start",
        f"{fmt(base_start + total_duration * 0.2)} Hook & Foundation",
        f"{fmt(base_start + total_duration * 0.4)} The Deep Dive",
        f"{fmt(base_start + total_duration * 0.7)} Modern Context",
        f"{fmt(base_start + total_duration * 0.9)} Final Reflections",
    ])
    return "\n".join(chapters)


def generate_show_notes(metadata: dict, essay_title: str, author: str) -> str:
    """Generate SEO-structured show notes in Markdown."""
    title = metadata.get("episode_title", f"{author}: {essay_title}")
    description = metadata.get("description", "")
    tags = metadata.get("tags", [])

    return f"""# {title}

{description}

---

## Episode Chapters

*(See below for timestamps - click to jump in the Spotify app)*

---

## Key Ideas in This Episode

- The central argument of *{essay_title}* by {author}
- How these ideas challenge our modern assumptions
- What this philosophy means for how we think and act today

---

## About {author}

{author} was one of history's most influential thinkers. *{essay_title}* remains one of the defining works of philosophical literature - a text that continues to provoke, challenge, and illuminate.

---

## Further Reading

- *Essays and Aphorisms* - {author}
- Project Gutenberg: [Free classical essays](https://www.gutenberg.org)

---

## Follow The Essayist

If you found this episode valuable, follow **The Essayist** on Spotify so you never miss an episode.

*The Essayist - where the ideas that shaped the world finally get the conversation they deserve.*

---

*Tags: {", ".join(tags)}*
"""


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


def build_metadata_package(
    essay_title: str,
    author: str,
    script_text: str,
    audio_segments: list[str],
    llm_metadata: dict,
    output_dir: str,
    episode_number: int = 1,
    safe_name: str = "episode",
    speech_start_delay: float = 0.0,
    turns: list[dict] = None,
) -> dict:
    """
    Build the full metadata package.
    """
    os.makedirs(output_dir, exist_ok=True)

    author_last = get_author_last_name(author)
    essay_title_clean = essay_title.title().strip()
    formatted_title = f"{author_last} - {essay_title_clean} -"

    metadata = {
        "podcast_name": PODCAST_NAME,
        "episode_title": formatted_title,
        "episode_number": episode_number,
        "season": 1,
        "author": author,
        "essay_title": essay_title,
        "hosts": [HOST_1_NAME.title(), HOST_2_NAME.title()],
        "description": llm_metadata.get("description", ""),
        "tags": llm_metadata.get("tags", ["philosophy", "classical essays"]),
        "category": "Society & Culture",
        "subcategory": "Philosophy",
        "language": "en",
        "explicit": False,
        "year": datetime.now().strftime("%Y"),
        "cover_art_spec": {
            "dimensions": "3000x3000px",
            "format": "PNG or JPEG",
            "color_space": "sRGB 24-bit",
            "max_file_size": "512KB",
            "notes": "Square. No borders. No embedded color profile metadata."
        }
    }

    # Write metadata JSON
    json_path = os.path.join(output_dir, f"{safe_name}_metadata.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"  Metadata JSON: {json_path}")

    # Write VTT transcript
    vtt_path = os.path.join(output_dir, f"{safe_name}_transcript.vtt")
    vtt = generate_vtt_transcript(script_text, speech_start_delay=speech_start_delay, turns=turns)
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write(vtt)
    print(f"  VTT Transcript: {vtt_path}")

    # Write chapter markers
    chapters_path = os.path.join(output_dir, f"{safe_name}_chapters.txt")
    chapters = generate_chapter_markers(script_text, audio_segments, speech_start_delay=speech_start_delay, turns=turns)
    with open(chapters_path, "w", encoding="utf-8") as f:
        f.write(chapters)
    print(f"  Chapter Markers: {chapters_path}")

    # Write show notes
    notes_path = os.path.join(output_dir, f"{safe_name}_show_notes.md")
    notes = generate_show_notes(metadata, essay_title, author)
    with open(notes_path, "w", encoding="utf-8") as f:
        f.write(notes)
    print(f"  Show Notes: {notes_path}")

    return {
        "metadata_json": json_path,
        "vtt_transcript": vtt_path,
        "chapters": chapters_path,
        "show_notes": notes_path,
        "metadata": metadata,
    }
