"""STT + TTS wrappers, plus ASR merchant fuzzy-correction — built out in S07.

transcribe(audio_bytes) -> str   (whisper-1)
synthesize(text) -> bytes        (tts-1, voice="nova", mp3)

See all-specs.md S07 and .claude/agents/voice-ui-engineer.md.
"""
