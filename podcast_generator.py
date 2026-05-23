import os
import sys
import re
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load .env file relative to script location
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

HOST_1_NAME = os.getenv("HOST_1_NAME", "Host 1").upper()
HOST_2_NAME = os.getenv("HOST_2_NAME", "Host 2").upper()
PODCAST_NAME = os.getenv("PODCAST_NAME", "The Podcast")

from script_generator import generate_script, generate_metadata_text
from audio_generator import generate_audio_segments, count_words
from mixer import mix_audio, embed_id3_tags
from metadata_generator import build_metadata_package
from usage_tracker import print_session_summary, save_to_log
from extractor import fetch_historical_context

OUTPUT_DIR = "podcast_output"
TEMP_DIR = "temp"


def safe_filename(text: str, max_len: int = 30) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '_', text)[:max_len]


def run_podcast_generation(essay_path: str, title: str = None, author: str = "Unknown Author", episode_num: int = 1):
    # ── Load essay ─────────────────────────────────────────────────────────
    if not os.path.exists(essay_path):
        print(f"Error: File not found - {essay_path}")
        sys.exit(1)

    with open(essay_path, "r", encoding="utf-8") as f:
        essay_text = f.read().strip()

    if not essay_text:
        print("Error: Essay file is empty.")
        sys.exit(1)

    essay_title = title or os.path.splitext(os.path.basename(essay_path))[0].replace("_", " ").title()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    safe_name = safe_filename(essay_title)
    subfolder_name = f"{safe_name}_{timestamp}"
    episode_dir = os.path.join(OUTPUT_DIR, subfolder_name)
    os.makedirs(episode_dir, exist_ok=True)
    
    output_base_name = safe_name # Keep filenames simple inside the folder

    print(f"\n{'='*50}")
    print(f"  {PODCAST_NAME} - Podcast Generator")
    print(f"{'='*50}")
    print(f"  Essay : {essay_title}")
    print(f"  Author: {author}")
    print(f"  File  : {essay_path}")
    print(f"  Output: {episode_dir}")
    print(f"{'='*50}\n")

    usage_log = {
        "essay": essay_title,
        "author": author,
        "provider_stats": {
            "openrouter": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
            "groq": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        }
    }

    # ── Step 0: Fetch Historical Context ────────────────────────────────────
    print("[0/5] Fetching historical context payload (Wikipedia)...")
    historical_context = fetch_historical_context(author, essay_title)
    if historical_context:
        print(f"  Successfully retrieved context payload ({len(historical_context.split())} words).")
    else:
        print("  No context payload found or retrieved.")

    # ── Step 1: Generate Script ─────────────────────────────────────────────
    print("\n[1/5] Generating podcast script via LLM...")
    script, model_used = generate_script(
        essay_text=essay_text,
        essay_title=essay_title,
        author=author,
        usage_log=usage_log,
        episode_num=episode_num,
        historical_context=historical_context
    )

    script_path = os.path.join(episode_dir, f"{output_base_name}_script.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    print(f"  Script saved: {script_path}")

    word_counts = count_words(script)
    total_words = sum(word_counts.values())
    est_minutes = round(total_words / 140, 1)
    print(f"  Word counts: {HOST_1_NAME.title()}={word_counts.get(HOST_1_NAME,0)}, "
          f"{HOST_2_NAME.title()}={word_counts.get(HOST_2_NAME,0)} "
          f"| Total ~{est_minutes} min")

    # ── Step 2: Generate Audio Segments ────────────────────────────────────
    print("\n[2/5] Generating audio segments (Edge TTS)...")
    turns = generate_audio_segments(script, temp_dir=TEMP_DIR)

    # ── Step 3: Mix & Normalize ─────────────────────────────────────────────
    print("\n[3/5] Mixing and normalizing audio (FFmpeg)...")
    mp3_output = os.path.join(episode_dir, f"{output_base_name}.mp3")
    speech_start_delay = mix_audio(turns, mp3_output)

    # ── Step 4: Generate Metadata ───────────────────────────────────────────
    print("\n[4/5] Generating metadata package (LLM + local)...")
    llm_meta = generate_metadata_text(essay_title, author, essay_text[:800], usage_log)

    meta_package = build_metadata_package(
        essay_title=essay_title,
        author=author,
        script_text=script,
        audio_segments=[t["audio_path"] for t in turns],
        llm_metadata=llm_meta,
        output_dir=episode_dir,
        episode_number=episode_num,
        safe_name=output_base_name,
        speech_start_delay=speech_start_delay,
        turns=turns,
    )

    # ── Step 5: Embed ID3 Tags ──────────────────────────────────────────────
    print("\n[5/5] Embedding ID3v2 tags...")
    embed_id3_tags(mp3_output, {**meta_package["metadata"], "year": datetime.now().strftime("%Y")})
    usage_log["output_file"] = mp3_output

    # ── Done ────────────────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"  Episode complete!")
    print(f"  MP3         : {mp3_output}")
    print(f"  Script      : {script_path}")
    print(f"  VTT         : {meta_package['vtt_transcript']}")
    print(f"  Chapters    : {meta_package['chapters']}")
    print(f"  Show Notes  : {meta_package['show_notes']}")
    print(f"  Metadata    : {meta_package['metadata_json']}")
    print(f"{'='*50}")

    print_session_summary(usage_log)
    save_to_log(usage_log)


def main():
    parser = argparse.ArgumentParser(
        description="The Essayist - Podcast Generator",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("essay_file", help="Path to the extracted essay .txt file")
    parser.add_argument("--title", help="Essay title (optional, guessed from filename if not provided)")
    parser.add_argument("--author", help="Essay author (optional)", default="Unknown Author")
    parser.add_argument("--episode", type=int, default=1, help="Episode number (default: 1)")
    args = parser.parse_args()

    run_podcast_generation(
        essay_path=args.essay_file,
        title=args.title,
        author=args.author,
        episode_num=args.episode
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
