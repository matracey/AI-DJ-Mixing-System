# generate_mixing_plan.py

"""
DJ Mixing Plan Generator (Ready for Mixing Engine)

- Reads basic_setlist.json + structure_data.json
- Uses harmonic mixing (Camelot Wheel) for key compatibility
- Dynamic overlap duration based on energy difference
- Chorus Beatmatch for normal tracks
- Outputs mixing_plan.json with exact timings for fade-in/out
"""

import os
import json
from datetime import datetime, timedelta
import librosa

SONGS_DIR = "./songs"

# ================= GENRE-SPECIFIC TRANSITION RULES =================
GENRE_TRANSITION_RULES = {
    "afrobeats": {
        "preferred_type": "verse_end",
        "avoid": ["mid_chorus"],
        "energy_preference": "smooth"
    },
    "r&b": {
        "preferred_type": "breakdown_start",
        "avoid": ["mid_vocal_phrase"],
        "energy_preference": "smooth"
    },
    "pop": {
        "preferred_type": "chorus_end",
        "avoid": [],
        "energy_preference": "energetic"
    },
    "edm": {
        "preferred_type": "pre_drop",
        "avoid": ["mid_buildup"],
        "energy_preference": "energetic"
    },
    "hip hop": {
        "preferred_type": "verse_end",
        "avoid": ["mid_hook"],
        "energy_preference": "smooth"
    },
    "dancehall": {
        "preferred_type": "chorus_end",
        "avoid": [],
        "energy_preference": "energetic"
    }
}

# ================= CAMELOT WHEEL (HARMONIC MIXING) =================
# Musical key compatibility for smooth DJ transitions
CAMELOT_WHEEL = {
    # Major keys
    "C": {"compatible": ["G", "F", "Am"], "energy_boost": ["G"], "energy_drop": ["Am"]},
    "C#": {"compatible": ["G#", "F#", "A#m"], "energy_boost": ["G#"], "energy_drop": ["A#m"]},
    "D": {"compatible": ["A", "G", "Bm"], "energy_boost": ["A"], "energy_drop": ["Bm"]},
    "D#": {"compatible": ["A#", "G#", "Cm"], "energy_boost": ["A#"], "energy_drop": ["Cm"]},
    "E": {"compatible": ["B", "A", "C#m"], "energy_boost": ["B"], "energy_drop": ["C#m"]},
    "F": {"compatible": ["C", "A#", "Dm"], "energy_boost": ["C"], "energy_drop": ["Dm"]},
    "F#": {"compatible": ["C#", "B", "D#m"], "energy_boost": ["C#"], "energy_drop": ["D#m"]},
    "G": {"compatible": ["D", "C", "Em"], "energy_boost": ["D"], "energy_drop": ["Em"]},
    "G#": {"compatible": ["D#", "C#", "Fm"], "energy_boost": ["D#"], "energy_drop": ["Fm"]},
    "A": {"compatible": ["E", "D", "F#m"], "energy_boost": ["E"], "energy_drop": ["F#m"]},
    "A#": {"compatible": ["F", "D#", "Gm"], "energy_boost": ["F"], "energy_drop": ["Gm"]},
    "B": {"compatible": ["F#", "E", "G#m"], "energy_boost": ["F#"], "energy_drop": ["G#m"]},
    
    # Minor keys
    "Am": {"compatible": ["Em", "Dm", "C"], "energy_boost": ["C"], "energy_drop": ["Dm"]},
    "A#m": {"compatible": ["Fm", "D#m", "C#"], "energy_boost": ["C#"], "energy_drop": ["D#m"]},
    "Bm": {"compatible": ["F#m", "Em", "D"], "energy_boost": ["D"], "energy_drop": ["Em"]},
    "Cm": {"compatible": ["Gm", "Fm", "D#"], "energy_boost": ["D#"], "energy_drop": ["Fm"]},
    "C#m": {"compatible": ["G#m", "F#m", "E"], "energy_boost": ["E"], "energy_drop": ["F#m"]},
    "Dm": {"compatible": ["Am", "Gm", "F"], "energy_boost": ["F"], "energy_drop": ["Gm"]},
    "D#m": {"compatible": ["A#m", "G#m", "F#"], "energy_boost": ["F#"], "energy_drop": ["G#m"]},
    "Em": {"compatible": ["Bm", "Am", "G"], "energy_boost": ["G"], "energy_drop": ["Am"]},
    "Fm": {"compatible": ["Cm", "A#m", "G#"], "energy_boost": ["G#"], "energy_drop": ["A#m"]},
    "F#m": {"compatible": ["C#m", "Bm", "A"], "energy_boost": ["A"], "energy_drop": ["Bm"]},
    "Gm": {"compatible": ["Dm", "Cm", "A#"], "energy_boost": ["A#"], "energy_drop": ["Cm"]},
    "G#m": {"compatible": ["D#m", "C#m", "B"], "energy_boost": ["B"], "energy_drop": ["C#m"]},
}

def calculate_key_compatibility(key1: str, key2: str) -> float:
    """
    Calculate harmonic compatibility score between two musical keys.
    Returns: 1.0 (perfect), 0.5 (acceptable), -1.0 (clash)
    """
    if not key1 or not key2 or key1 not in CAMELOT_WHEEL:
        return 0.5  # Unknown, assume neutral
    
    if key1 == key2:
        return 1.0  # Same key = perfect
    
    compatible_keys = CAMELOT_WHEEL[key1].get("compatible", [])
    if key2 in compatible_keys:
        return 1.0  # Harmonically compatible
    
    # Check if relative minor/major
    if key1.endswith("m") and key2 == key1[:-1]:  # Am -> A
        return 0.8
    if not key1.endswith("m") and key2 == key1 + "m":  # A -> Am
        return 0.8
    
    return -1.0  # Key clash - will sound bad


ELECTRONIC_GENRES = (
    "edm", "electronic", "house", "techno", "trance", "progressive",
    "electro", "dance", "drum and bass", "dnb", "dubstep", "deep house",
    "tech house",
)


def is_electronic_genre(genre: str) -> bool:
    """True if the genre is an electronic/dance style suited to a long blend."""
    g = (genre or "").lower()
    return any(tag in g for tag in ELECTRONIC_GENRES)


def tempo_bridge(bpm_from: float, bpm_to: float):
    """Pick the half/double-time multiple of bpm_to closest to bpm_from.

    DJs treat a 64 BPM track as mixable with a 128 BPM track by playing it at
    double time. Returns (effective_to_bpm, stretch_ratio) where stretch_ratio
    is how much the incoming track must be stretched (applied to bpm_to's audio)
    to match bpm_from. A ratio of 1.0 means no change.
    """
    if not bpm_from or not bpm_to or bpm_from <= 0 or bpm_to <= 0:
        return (bpm_to, 1.0)

    best_eff, best_ratio, best_dist = bpm_to, 1.0, float("inf")
    for factor in (0.5, 1.0, 2.0):
        eff = bpm_to * factor
        ratio = bpm_from / eff  # stretch incoming so eff -> bpm_from
        dist = abs(eff - bpm_from)
        if dist < best_dist:
            best_eff, best_ratio, best_dist = eff, ratio, dist
    return (best_eff, best_ratio)


def is_mixable(from_track: dict, to_track: dict, max_stretch: float = 0.12):
    """True if two tracks can be beatmatched within max_stretch and aren't a key clash.

    Uses the half/double-time bridge so e.g. 64 vs 128 counts as mixable.
    """
    bpm_from = from_track.get("bpm", 0)
    bpm_to = to_track.get("bpm", 0)
    _, ratio = tempo_bridge(bpm_from, bpm_to)
    if abs(ratio - 1.0) > max_stretch:
        return False
    key_score = calculate_key_compatibility(from_track.get("key", ""), to_track.get("key", ""))
    return key_score >= 0



    """
    Find the END of the FIRST CHORUS - where to echo out.
    
    Simple approach: GPT identifies the first chorus and gives us chorus_end_time.
    
    Args:
        track: Track dictionary with structure data
    
    Returns: Time in seconds where first chorus ends (for echo transition)
    """
    # Check both locations: track["structure"] and track directly (backward compatibility)
    structure = track.get("structure", track)
    
    # NEW SIMPLE APPROACH: Use chorus_end_time directly from GPT
    chorus_end = structure.get("chorus_end_time")
    if chorus_end:
        print(f"    → First chorus ends at {chorus_end:.1f}s")
        last_line = structure.get("last_chorus_line", "")
        if last_line:
            print(f"    → Last line: \"{last_line[:50]}...\"" if len(last_line) > 50 else f"    → Last line: \"{last_line}\"")
        return float(chorus_end)
    
    # FALLBACK: Check transition_candidates for chorus_end type
    candidates = structure.get("transition_candidates", [])
    
    # Look for chorus_end type first
    for candidate in candidates:
        if candidate.get("type") == "chorus_end":
            print(f"    → Found chorus_end at {candidate['time']:.1f}s")
            return candidate["time"]
    
    # Look for any point with has_vocals_after=False
    for candidate in candidates:
        if candidate.get("has_vocals_after") == False:
            print(f"    → Found vocal-free point at {candidate['time']:.1f}s")
            return candidate["time"]
    
    # Fallback to recommended_transition
    recommended = structure.get("recommended_transition")
    if recommended:
        print(f"    → Using recommended transition: {recommended:.1f}s")
        return recommended
    
    # Final fallback: Use transition_point
    transition_pt = structure.get("transition_point")
    if transition_pt:
        print(f"    → Using transition_point: {transition_pt:.1f}s")
        return transition_pt
    
    # Last resort fallback
    print(f"    → No chorus end found, using default 60s")
    return 60.0


def score_transition_candidate(candidate, current_track, next_track):
    """
    Score a transition point candidate based on multiple factors.
    Returns score 0-100.
    """
    score = 50.0  # Base score
    
    # Get track metadata
    current_genre = current_track.get("genre", "").lower()
    current_key = current_track.get("key", "")
    current_bpm = current_track.get("bpm", 120)
    
    next_key = next_track.get("key", "")
    next_bpm = next_track.get("bpm", 120)
    
    # Check both locations for structure data (backward compatibility)
    next_structure = next_track.get("structure", next_track)
    next_intro_vocals = next_structure.get("has_vocals_in_first_8s", True)
    
    # FACTOR 1: Genre-specific preference (±15 points)
    genre_rules = GENRE_TRANSITION_RULES.get(current_genre, {})
    preferred_type = genre_rules.get("preferred_type")
    
    if preferred_type and candidate["type"] == preferred_type:
        score += 15
    elif candidate["type"] in genre_rules.get("avoid", []):
        score -= 15
    
    # FACTOR 2: Vocal overlap risk (±20 points)
    has_vocals_after = candidate.get("has_vocals_after", True)
    
    if has_vocals_after and next_intro_vocals:
        score -= 20  # Double vocals = muddy
    elif not has_vocals_after and not next_intro_vocals:
        score += 15  # Clean instrumental blend
    elif not has_vocals_after:
        score += 10  # Outgoing instrumental, any incoming works
    
    # FACTOR 3: Energy compatibility (±15 points)
    candidate_energy = candidate.get("energy", "medium")
    
    # Check both locations for energy analysis
    next_structure = next_track.get("structure", next_track)
    next_energy = next_structure.get("energy_analysis", {}).get("buildups", [])
    
    # Prefer transitions that maintain or build energy
    if candidate_energy == "high" and len(next_energy) > 0:
        score += 10  # High to buildup = great flow
    elif candidate_energy == "building":
        score += 15  # Building energy is ideal for transitions
    elif candidate_energy == "dropping":
        score -= 5   # Dropping energy can work but less ideal
    
    # FACTOR 4: Key compatibility (±10 points)
    key_score = calculate_key_compatibility(current_key, next_key)
    if key_score >= 1.0:
        score += 10
    elif key_score < 0:
        score -= 10
    
    # FACTOR 5: BPM difference (±5 points)
    bpm_diff = abs(current_bpm - next_bpm)
    if bpm_diff < 5:
        score += 5   # Very close BPMs = easy mix
    elif bpm_diff > 20:
        score -= 5   # Large difference needs more work
    
    # FACTOR 6: Transition type bonus
    type_scores = {
        "breakdown_start": 10,  # Best for beat-sync
        "pre_drop": 8,          # Great for energy
        "verse_end": 5,         # Safe choice
        "chorus_end": 3         # Can work but risky
    }
    score += type_scores.get(candidate["type"], 0)
    
    return max(0, min(100, score))  # Clamp 0-100


def select_best_transition_point(current_track, next_track):
    """
    Select the best transition point from all candidates.
    Uses intelligent scoring based on musical context.
    """
    # Check both locations: track["structure"] and track directly (for backward compatibility)
    structure = current_track.get("structure", current_track)
    candidates = structure.get("transition_candidates", [])
    
    if not candidates:
        # Fallback to recommended or transition_point (check both locations)
        recommended = structure.get("recommended_transition")
        if recommended:
            return recommended
        
        transition_pt = structure.get("transition_point")
        if transition_pt:
            return transition_pt
        
        # Final fallback
        return 70.0
    
    # Score each candidate
    scored_candidates = []
    for candidate in candidates:
        score = score_transition_candidate(candidate, current_track, next_track)
        scored_candidates.append({
            "time": candidate["time"],
            "type": candidate["type"],
            "score": score,
            "reasoning": candidate.get("reasoning", "")
        })
    
    # Sort by score (highest first)
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    
    # Return best candidate
    best = scored_candidates[0]
    print(f"    → Selected: {best['time']:.1f}s ({best['type']}, score: {best['score']:.0f}/100)")
    print(f"    → Reason: {best['reasoning'][:60]}..." if len(best['reasoning']) > 60 else f"    → Reason: {best['reasoning']}")
    
    return best["time"]


def calculate_dynamic_overlap(from_track: dict, to_track: dict) -> float:
    """
    Calculate optimal overlap duration based on musical characteristics.
    Real DJs vary overlap based on energy, genre, and key compatibility.
    """
    # Base overlap: 8 seconds
    base_overlap = 8.0
    
    # Get track properties
    from_bpm = from_track.get("bpm", 120)
    to_bpm = to_track.get("bpm", 120)
    from_key = from_track.get("key", "")
    to_key = to_track.get("key", "")
    from_genre = from_track.get("genre", "").lower()
    to_genre = to_track.get("genre", "").lower()
    
    # Factor 1: BPM difference (larger = longer transition)
    bpm_diff = abs(from_bpm - to_bpm)
    if bpm_diff > 20:
        base_overlap += 4.0  # Need more time to adjust
    elif bpm_diff > 10:
        base_overlap += 2.0
    
    # Factor 2: Key compatibility (bad match = shorter transition)
    key_score = calculate_key_compatibility(from_key, to_key)
    if key_score < 0:  # Key clash
        base_overlap -= 2.0  # Quick transition to minimize clash
        print(f"    ⚠️ Key clash: {from_key} → {to_key}, shorter transition")
    elif key_score >= 1.0:  # Perfect match
        base_overlap += 2.0  # Can blend longer
        print(f"    ✅ Perfect key match: {from_key} → {to_key}")
    
    # Factor 3: Genre-specific rules
    if "edm" in from_genre or "edm" in to_genre or "house" in from_genre or "house" in to_genre:
        base_overlap += 4.0  # Electronic music = longer blends
    elif "hip" in from_genre or "hip" in to_genre or "rap" in from_genre or "rap" in to_genre:
        base_overlap -= 2.0  # Hip-hop = quicker cuts
    
    # Clamp to reasonable range (4-16 seconds)
    return max(4.0, min(16.0, base_overlap))


def load_json(path: str):
    with open(path, "r") as f:
        return json.load(f)


def format_time(seconds: float) -> str:
    return (datetime.min + timedelta(seconds=seconds)).strftime("%H:%M:%S")


def get_chorus_duration(track: dict) -> float:
    return track.get("first_chorus_end", 90.0) - track.get("first_chorus_start", 60.0)


def select_tracks_in_order(basic_setlist: dict, structure_data: dict) -> list[dict]:
    """
    Merge basic setlist and analyzed structure data, then SORT BY BPM (lowest to highest).
    This creates a smooth energy progression for DJ mixing.
    """
    all_tracks = []
    analyzed_dict = {}
    for segment in structure_data.get("analyzed_setlist", []):
        for track in segment.get("analyzed_tracks", []):
            analyzed_dict[track["title"]] = track

    for segment in basic_setlist.get("setlist", []):
        for track in segment.get("tracks", []):
            title = track["title"]
            analyzed_track = analyzed_dict.get(title)
            if analyzed_track:
                track_copy = analyzed_track.copy()
                track_copy["original_segment_time"] = segment.get("time", "Unknown")
                all_tracks.append(track_copy)
            else:
                print(f"Warning: '{title}' not found in structure data; skipping.")

    # SORT BY BPM - lowest to highest for smooth energy progression
    all_tracks.sort(key=lambda t: t.get("bpm", 120))
    
    print(f"\n🎵 Song order (sorted by BPM):")
    for i, track in enumerate(all_tracks, 1):
        print(f"  {i}. {track['title']} - {track.get('bpm', 'N/A')} BPM")
    print()
    
    return all_tracks


def generate_mixing_plan(
    basic_setlist_path: str = "basic_setlist.json",
    structure_json_path: str = "structure_data.json",
    output_path: str = "mixing_plan.json",
    overlap_duration: float = 8.0,  # 8 seconds overlap at transition
    fade_duration: float = 1.0  # 1 second fade out
):
    try:
        basic_setlist = load_json(basic_setlist_path)
        structure_data = load_json(structure_json_path)

        all_tracks = select_tracks_in_order(basic_setlist, structure_data)

        mixing_plan = []
        last_start_sec = 0.0
        last_track = None
        last_duration_sec = 0.0

        for idx, track in enumerate(all_tracks):
            file_path = os.path.join(SONGS_DIR, track["file"])
            if not os.path.exists(file_path):
                print(f"Missing: {file_path}. Skipping.")
                continue

            try:
                duration_sec = librosa.get_duration(filename=file_path)
            except Exception as e:
                print(f"Error loading {track['file']}: {e}. Skipping.")
                continue

            if last_track is None:
                # First track - play from beginning
                start_sec = 0.0
                incoming_start_sec = 0.0
                transition_type = "Fade In"
                transition_point = None
                first_chorus_end = None
                incoming_intro = None
                bpm_change_point = None
                comment = f"Start with {track['title']} (BPM {track.get('bpm', 'N/A')})"
            else:
                print(f"  Analyzing transition: {last_track['title']} → {track['title']}")

                to_intro_duration = track.get("intro_duration", 8.0)
                from_key = last_track.get("key", "")
                to_key = track.get("key", "")
                key_score = calculate_key_compatibility(from_key, to_key)

                from_bpm = last_track.get("bpm", 120)
                to_bpm = track.get("bpm", 120)

                # Decide transition type: a true DJ "long blend" for electronic,
                # beatmatchable, harmonically-OK pairs; otherwise the echo cut.
                use_long_blend = (
                    is_electronic_genre(last_track.get("genre", ""))
                    and is_electronic_genre(track.get("genre", ""))
                    and is_mixable(last_track, track)
                )

                if use_long_blend:
                    # 32-bar overlap derived from the outgoing tempo (4 beats/bar),
                    # clamped to a musical 24-80s range.
                    bars = 32
                    overlap_duration = (bars * 4 * 60.0) / max(from_bpm, 1)
                    overlap_duration = max(24.0, min(80.0, overlap_duration))

                    # Outgoing plays solo until duration - overlap, then both
                    # tracks overlap for `overlap_duration`, then incoming continues.
                    mix_out_point = max(1.0, last_duration_sec - overlap_duration)
                    incoming_start_sec = last_start_sec + mix_out_point

                    eff_bpm, tempo_ratio = tempo_bridge(from_bpm, to_bpm)
                    bass_swap_offset = overlap_duration / 2.0  # midpoint of the overlap

                    transition_type = "long-blend"
                    transition_point = mix_out_point
                    first_chorus_end = mix_out_point
                    incoming_intro = to_intro_duration
                    bpm_change_point = incoming_start_sec
                    echo_for_plan = None

                    key_info = (f"✓ Keys match ({from_key}→{to_key})" if key_score >= 1.0
                                else (f"⚠ Key clash ({from_key}→{to_key})" if key_score < 0 else ""))
                    print(f"    → Long blend: {overlap_duration:.1f}s overlap, "
                          f"bass swap at +{bass_swap_offset:.1f}s, tempo x{tempo_ratio:.3f}")
                    comment = (
                        f"LONG BLEND: {last_track['title']} (BPM {from_bpm}) -> {track['title']} "
                        f"(BPM {to_bpm}). {overlap_duration:.0f}s (32-bar) overlap, bass swap at "
                        f"overlap midpoint. {key_info}."
                    )
                else:
                    # ECHO TRANSITION: play the outgoing track until near its END,
                    # then echo out into the incoming track.
                    echo_duration = 3.0  # 3 seconds echo
                    outro_lead = max(overlap_duration, echo_duration)
                    mix_out_point = max(1.0, last_duration_sec - outro_lead)
                    first_chorus_end = mix_out_point
                    print(f"    → Outgoing plays to {mix_out_point:.1f}s of {last_duration_sec:.1f}s, then echoes out")

                    incoming_start_sec = last_start_sec + first_chorus_end
                    bpm_change_point = incoming_start_sec
                    transition_type = "echo-transition"
                    transition_point = first_chorus_end
                    incoming_intro = to_intro_duration
                    tempo_ratio = 1.0
                    bass_swap_offset = None
                    echo_for_plan = 3.0

                    key_info = ""
                    if key_score >= 1.0:
                        key_info = f"✓ Keys match ({from_key}→{to_key})"
                    elif key_score < 0:
                        key_info = f"⚠ Key clash ({from_key}→{to_key})"
                    comment = (
                        f"ECHO TRANSITION: {last_track['title']} (BPM {from_bpm}) -> {track['title']} "
                        f"(BPM {to_bpm}). Echo at first chorus end ({first_chorus_end:.1f}s). "
                        f"{key_info}. 3s echo + incoming starts simultaneously."
                    )

            start_str = format_time(incoming_start_sec)

            mixing_plan.append(
                {
                    "from_track": last_track["title"] if last_track else None,
                    "to_track": track["title"],
                    "incoming_start_sec": incoming_start_sec,
                    "start_time": start_str,
                    "transition_point": transition_point,
                    "first_chorus_end_sec": first_chorus_end if last_track else None,
                    "echo_duration_sec": (echo_for_plan if last_track else None),
                    "incoming_intro_duration": incoming_intro,
                    "bpm_change_point_sec": bpm_change_point,
                    "overlap_duration": overlap_duration,
                    "fade_duration": fade_duration,
                    "transition_type": transition_type,
                    "tempo_ratio": (tempo_ratio if last_track else None),
                    "bass_swap_offset_sec": (bass_swap_offset if last_track else None),
                    "to_bpm": track.get("bpm", 120),
                    "from_bpm": last_track.get("bpm", 120) if last_track else None,
                    "comment": comment,
                }
            )

            last_start_sec = incoming_start_sec
            last_track = track
            last_duration_sec = duration_sec

        with open(output_path, "w") as f:
            json.dump({"mixing_plan": mixing_plan}, f, indent=2)

        print(f"Mixing plan saved to '{output_path}' with {len(mixing_plan)} tracks.")

    except Exception as e:
        print(f"Error generating mixing plan: {e}")
        raise


if __name__ == "__main__":
    generate_mixing_plan()
