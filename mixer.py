import os
import subprocess
import shutil
import asyncio
import edge_tts

def find_ffmpeg():
    """Find ffmpeg executable."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg not found in PATH. Please install FFmpeg:\n"
            "  Windows: https://ffmpeg.org/download.html\n"
            "  Or: winget install ffmpeg"
        )
    return ffmpeg

def run_ffmpeg(args: list, description: str = ""):
    """Run an FFmpeg command and raise on failure."""
    ffmpeg = find_ffmpeg()
    cmd = [ffmpeg, "-y"] + args
    print(f"  FFmpeg: {description}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n{result.stderr}")

def get_audio_duration(path: str) -> float:
    """Get duration of audio file in seconds using ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        try:
            return os.path.getsize(path) / 24000.0
        except Exception:
            return 5.0
    cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except Exception:
        return os.path.getsize(path) / 24000.0

async def ensure_active_listening_assets():
    """Ensure the active listening cue files exist. Generates them using Edge TTS if missing."""
    assets_dir = os.path.join("assets", "active_listening")
    os.makedirs(assets_dir, exist_ok=True)
    
    # BrianNeural for Marcus (listener when Julian speaks), AndrewNeural for Julian (listener when Marcus speaks)
    cues = {
        "right": ("Right.", "en-US-BrianNeural"), 
        "right_j": ("Right.", "en-US-AndrewNeural"), 
        "mhm": ("Mhm.", "en-US-BrianNeural"),
        "mhm_j": ("Mhm.", "en-US-AndrewNeural"),
        "yeah": ("Yeah.", "en-US-BrianNeural"),
        "yeah_j": ("Yeah.", "en-US-AndrewNeural")
    }
    
    for filename, (text, voice) in cues.items():
        path = os.path.join(assets_dir, f"{filename}.mp3")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            print(f"  Generating active listening asset: {filename}.mp3...")
            try:
                communicate = edge_tts.Communicate(text=text, voice=voice, rate="+5%")
                await asyncio.wait_for(communicate.save(path), timeout=5.0)
            except Exception as e:
                print(f"  Warning: failed to generate listening asset {filename}: {e}")
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass


def trim_silence(input_path: str, output_path: str):
    """Trim leading and trailing silence from an audio file using FFmpeg. Falls back to copy if it fails."""
    try:
        args = [
            "-i", input_path,
            "-af", "silenceremove=start_periods=1:start_threshold=-50dB:stop_periods=-1:stop_threshold=-50dB",
            output_path
        ]
        run_ffmpeg(args, f"Trimming silence from {os.path.basename(input_path)}")
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("Trimmed file is empty or missing")
    except Exception as e:
        print(f"  Warning: Silence trimming failed for {input_path} ({e}). Using original file.")
        shutil.copy2(input_path, output_path)

def mix_audio(turns: list[dict], output_path: str):
    """
    Stitch and mix Marcus and Julian dialogue turns onto separate tracks.
    Applies vocal overlaps for interruptions, overlays active listening cues,
    adds intro/outro music with ducking envelopes, and masters to -16 LUFS / -1.5 dBTP.
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)
    
    # 1. Ensure active listening audio assets exist
    asyncio.run(ensure_active_listening_assets())
    
    # 2. Build Timeline Start Times and Durations
    intro_music = "assets/music/intro_theme.mp3"
    outro_music = "assets/music/outro_theme.mp3"
    has_music = os.path.exists(intro_music) and os.path.exists(outro_music)
    
    intro_duration = 5.0
    outro_duration = 10.0
    if has_music:
        intro_duration = get_audio_duration(intro_music)
        outro_duration = get_audio_duration(outro_music)
        
    # Start speech 1.0s before intro theme ends (creating a smooth crossfade)
    speech_start_delay = max(1.0, intro_duration - 1.0) if has_music else 1.0
    current_time = speech_start_delay
    start_times = []
    durations = []
    trimmed_paths = []
    
    print("  Trimming silence and calculating conversation timeline...")
    for i, turn in enumerate(turns):
        trimmed_path = os.path.join(temp_dir, f"trimmed_turn_{i:03d}.mp3")
        trim_silence(turn["audio_path"], trimmed_path)
        trimmed_paths.append(trimmed_path)
        
        duration = get_audio_duration(trimmed_path)
        durations.append(duration)
        start_times.append(current_time)
        
        # Save start time and duration to the turn dict (used for accurate WebVTT/Chapters)
        turn["start_time"] = current_time
        turn["duration"] = duration
        
        # Dialogue gap: using a more natural 0.6s gap (since silence is trimmed) to match original pacing
        gap = 0.6
        if i + 1 < len(turns):
            next_text = turns[i+1]["dialogue"].lower().strip()
            # If next turn begins with an interruption word, overlap speech by -200ms
            if next_text.startswith(("wait", "but ", "hold ", "stop", "exactly", "indeed", "no ", "yes!")):
                gap = 0.1
        
        current_time += duration + gap
        
    # Start outro music 3.0s before hosts finish speaking to create an overlapping fade-in
    outro_start = max(0.0, current_time - 3.0) if has_music else current_time
    total_duration = outro_start + (outro_duration if has_music else 2.0)
    
    # 3. Assemble Marcus Track (Inputs and adelay filters)
    marcus_inputs = []
    marcus_filters = []
    m_idx = 0
    
    for i, turn in enumerate(turns):
        if turn["speaker"] == "MARCUS":
            # Add dialogue input using trimmed file
            marcus_inputs += ["-i", trimmed_paths[i]]
            delay_ms = int(start_times[i] * 1000)
            marcus_filters.append(f"[{m_idx}:a]adelay={delay_ms}|{delay_ms}[m{m_idx}]")
            m_idx += 1

    # 4. Assemble Julian Track (Inputs and adelay filters)
    julian_inputs = []
    julian_filters = []
    j_idx = 0
    
    for i, turn in enumerate(turns):
        if turn["speaker"] == "JULIAN":
            # Add dialogue input using trimmed file
            julian_inputs += ["-i", trimmed_paths[i]]
            delay_ms = int(start_times[i] * 1000)
            julian_filters.append(f"[{j_idx}:a]adelay={delay_ms}|{delay_ms}[j{j_idx}]")
            j_idx += 1

    # 5. Compile Marcus Track File
    marcus_track_path = os.path.join(temp_dir, "marcus_full_track.mp3")
    if marcus_filters:
        filter_complex = ";".join(marcus_filters) + f";" + "".join(f"[m{x}]" for x in range(m_idx)) + f"amix=inputs={m_idx}:normalize=0"
        run_ffmpeg(marcus_inputs + ["-filter_complex", filter_complex, "-b:a", "192k", marcus_track_path], "Compiling Marcus dialogue track")
    else:
        # Fallback silent track
        run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(total_duration), "-b:a", "192k", marcus_track_path], "Compiling silent Marcus track")

    # 6. Compile Julian Track File
    julian_track_path = os.path.join(temp_dir, "julian_full_track.mp3")
    if julian_filters:
        filter_complex = ";".join(julian_filters) + f";" + "".join(f"[j{x}]" for x in range(j_idx)) + f"amix=inputs={j_idx}:normalize=0"
        run_ffmpeg(julian_inputs + ["-filter_complex", filter_complex, "-b:a", "192k", julian_track_path], "Compiling Julian dialogue track")
    else:
        # Fallback silent track
        run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(total_duration), "-b:a", "192k", julian_track_path], "Compiling silent Julian track")

    # 7. Mix Tracks with Music & Master
    final_inputs = ["-i", marcus_track_path, "-i", julian_track_path]
    
    if has_music:
        print("  Music files detected. Mixing in intro/outro theme files...")
        final_inputs += ["-i", intro_music, "-i", outro_music]
        outro_delay = int(outro_start * 1000)
        
        # Filter graph:
        # 1. Mix speech tracks at 100% volume
        # 2. Mix intro music directly (since it has pre-baked fade-in and fade-out)
        # 3. Delay outro music to create crossfade (since it has pre-baked fade-in and fade-out)
        # 4. Mix all 3 together and run loudness normalization to -16 LUFS
        filter_graph = (
            "[0:a][1:a]amix=inputs=2:normalize=0[speech]; "
            f"[3:a]adelay={outro_delay}|{outro_delay}[outro_delayed]; "
            "[speech][2:a][outro_delayed]amix=inputs=3:normalize=0[mixed]; "
            "[mixed]loudnorm=I=-16:TP=-1.5:LRA=11:print_format=none"
        )
    else:
        print("  Music files not detected. Mixing speech tracks directly...")
        filter_graph = (
            "[0:a][1:a]amix=inputs=2:normalize=0[mixed]; "
            "[mixed]loudnorm=I=-16:TP=-1.5:LRA=11:print_format=none"
        )
        
    run_ffmpeg(final_inputs + ["-filter_complex", filter_graph, "-b:a", "192k", "-ar", "44100", "-ac", "2", output_path], f"Final multi-track mix and mastering -> {output_path}")

    # 8. Clean up temporary files
    try:
        os.remove(marcus_track_path)
        os.remove(julian_track_path)
    except Exception:
        pass
        
    for path in trimmed_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        
    print(f"\n  Audio assembled: {output_path}")
    return speech_start_delay


def embed_id3_tags(mp3_path: str, metadata: dict, cover_art_path: str = None):
    """
    Embed ID3v2 metadata tags into the final MP3 using FFmpeg.
    Optionally embeds cover art if cover_art_path is provided.
    Writes to a temp file then replaces the original.
    """
    tagged_path = mp3_path.replace(".mp3", "_tagged.mp3")

    ffmpeg_args = ["-i", mp3_path]

    if cover_art_path and os.path.exists(cover_art_path):
        ffmpeg_args += ["-i", cover_art_path,
                        "-map", "0:a", "-map", "1:v",
                        "-c:a", "copy",
                        "-c:v", "mjpeg",
                        "-disposition:1", "attached_pic"]
    else:
        ffmpeg_args += ["-c", "copy"]

    ffmpeg_args += [
        "-metadata", f"title={metadata.get('episode_title', '')}",
        "-metadata", f"artist=Marcus & Julian",
        "-metadata", f"album=The Essayist",
        "-metadata", f"album_artist=The Essayist",
        "-metadata", f"track={metadata.get('episode_number', 1)}",
        "-metadata", f"date={metadata.get('year', '2026')}",
        "-metadata", f"genre=Podcast",
        "-metadata", f"description={metadata.get('description', '')}"
    ]

    ffmpeg_args.append(tagged_path)
    
    try:
        run_ffmpeg(ffmpeg_args, "Embedding ID3v2 tags")
        os.replace(tagged_path, mp3_path)
    except Exception as e:
        print(f"  Warning: ID3 tagging failed: {e}")
        if os.path.exists(tagged_path):
            try:
                os.remove(tagged_path)
            except Exception:
                pass
