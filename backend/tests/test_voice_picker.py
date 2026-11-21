import json
import re
from collections import Counter
from pathlib import Path
from app.voice_config import load_voice_profiles, dropdown_profiles, get_voice_profile


def test_picker_retains_indian_voices_and_limits_international_choices(monkeypatch):
    monkeypatch.delenv('GUARDIAN_VOICE_PROFILES_JSON', raising=False)
    profiles, selected = load_voice_profiles()
    visible = dropdown_profiles(profiles, selected)
    ids = {p.id for p in visible}
    catalog = json.loads((Path(__file__).parents[1] / 'app/murf_voices.json').read_text(encoding='utf-8'))
    native = {voice['voiceId']: voice['locale'] for voice in catalog}
    for profile in profiles.values():
        if profile.tts_locale.endswith('-IN') and not profile.tts_locale.startswith('en-') and native.get(profile.tts_voice_id) == profile.tts_locale:
            assert profile.id in ids
    english = [p for p in visible if p.tts_locale.startswith('en-') and p.id != 'auto']
    assert len(english) == 6
    groups = Counter()
    for p in visible:
        if p.id.startswith('murf-') and not p.tts_locale.endswith('-IN') and not p.tts_locale.startswith('en-'):
            gender = re.search(r'\(([MF])\)', p.label)[1]
            groups[(p.tts_locale.split('-')[0], gender)] += 1
    assert groups and all(n == 1 for n in groups.values())
    catalog = json.loads((Path(__file__).parents[1] / 'app/murf_voices.json').read_text(encoding='utf-8'))
    for voice in catalog:
        gender = re.search(r'\(([MF])\)', voice['displayName'])[1]
        for locale in {voice['locale'], *voice['supportedLocales']}:
            if not locale.endswith('-IN') and not locale.startswith('en-'):
                assert (locale.split('-')[0], gender) in groups
    hidden = next(p for p in profiles.values() if p.id not in ids)
    assert get_voice_profile(hidden.id) == hidden
