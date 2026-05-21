import asyncio
import os
from audio_generator import apply_pronunciation_fixes, text_to_wav, HOST_VOICE

async def test_pronunciation():
    test_text = "Welcome to the podcast. Today we discuss Arthur Schopenhauer. Schopenhauer was a pessimistic philosopher."
    
    print(f"Original Text: {test_text}")
    
    # 1. Test the text replacement
    fixed_text = apply_pronunciation_fixes(test_text)
    print(f"Fixed Text:    {fixed_text}")
    
    if "Showpenhower" in fixed_text:
        print("[SUCCESS] Text replacement successful!")
    else:
        print("[FAILURE] Text replacement failed!")
        return

    # 2. Test audio generation (dry run/small snippet)
    output_file = "temp/test_pronunciation.mp3"
    os.makedirs("temp", exist_ok=True)
    
    print(f"Generating test audio with voice: {HOST_VOICE}...")
    try:
        await text_to_wav(test_text, HOST_VOICE, output_file)
        print(f"[SUCCESS] Audio generated successfully at {output_file}")
        print("Please listen to this file to verify the pronunciation.")
    except Exception as e:
        print(f"[FAILURE] Audio generation failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_pronunciation())
