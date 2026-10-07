import math
from google import genai
from google.genai import types
from app.attribution.weather_client import WindData, compass_direction
from app.attribution.fire_client import FireDetection
from app.attribution.news_search import NewsResult
from app.attribution.trajectory import AirMassTrajectory
from app.config import settings
MODEL = 'gemini-3.5-flash'
FALLBACK_MODELS = ['gemini-3.5-flash', 'gemini-3.5-flash-lite']
SYSTEM_PROMPT = 'You explain air quality to everyday people in India in ONE short, natural, conversational sentence - like a friendly weather app notification, NOT a report. You will be given fixed facts: a station name, a computed AQI value and category, the dominant pollutant, wind conditions, nearby fire detections, and relevant recent news.\n\nRules you must follow exactly:\n- Use ONLY the facts provided. Never invent a cause not supported by them.\n- Never state a cause as certain. Use hedged language: "likely", "may be linked to", "could be contributing".\n- Never state or imply an AQI value or category different from the one given.\n- If a factor (wind, fire, news) has no data, simply don\'t mention it — don\'t say "no data" or apologize for missing it.\n- ONE sentence only. No line breaks. No paragraphs. Under 25 words.\n- NEVER use phrases like "the AQI is currently", "falls into the category", "the dominant pollutant contributing to this reading is", or any similarly clinical/report-style wording.\n- Write like you\'re texting a friend a quick heads-up, not filing a report.\n\nExample of the tone wanted (for a different reading, don\'t copy the facts):\n"Air\'s decent near Sion right now, mild PM2.5 with a light breeze keeping things fairly clear."\n\nAnother example, this time with a fire nearby:\n"Bandra\'s air is a bit rough today, likely worsened by a nearby fire and winds blowing smoke this way."\n'

TRAJECTORY_RULES = (
    "\nExtra rules when an air-mass trace is given:\n"
    "- The trace says where the air CAME FROM over the last few hours (not where it is going). Use it to say, in plain words, whether the air arrived from the sea, from a direction, or past a fire.\n"
    "- Only link a fire to the air quality if the trace lists it as being along the air's path. Fire detections listed as NOT on the path must not be blamed.\n"
    "- If winds were light, you may say pollutants are not being dispersed quickly.\n"
    "- Still hedge (\"likely\", \"may be\") and still write ONE short sentence.\n"
    "\nExample of the tone with an air-mass trace:\n"
    "\"Hazy at Chembur, likely from smoke carried in on east winds past a fire detected upwind a few hours ago.\"\n"
)
SYSTEM_PROMPT = SYSTEM_PROMPT + TRAJECTORY_RULES

def _trajectory_lines(trace: AirMassTrajectory) -> list[str]:
    """Facts from the back-trajectory, worded for the model."""
    lines = []
    if trace.stagnant:
        lines.append(f'Air-mass trace (last {trace.hours} h): winds were light (about {trace.mean_speed_mps:.1f} m/s), so pollutants are not being dispersed quickly')
    else:
        lines.append(f'Air-mass trace (last {trace.hours} h, from hourly wind): the air arrived from the {trace.origin_compass}, travelling about {trace.path_km:.0f} km')
        if trace.over_sea:
            lines.append(f'At least {math.floor(trace.marine_hours)} h of that was over the sea west of Mumbai')
        if trace.wards_crossed:
            lines.append('It then passed over these wards (earliest first): ' + ', '.join((w['ward_name'] for w in trace.wards_crossed)))
    if trace.fires_on_path:
        nearest = trace.fires_on_path[0]
        gap = 'right on the path' if nearest.distance_to_path_km < 1 else f'{nearest.distance_to_path_km:.0f} km from the path'
        lines.append(f"Fire detections along the air's path: {len(trace.fires_on_path)}, the closest {gap}, about {nearest.hours_upwind:.0f} h upwind ({nearest.frp_mw:.0f} MW)")
    elif trace.fires_off_path:
        lines.append(f"Fire detections nearby but NOT on the air's path: {trace.fires_off_path}")
    return lines

def _build_user_prompt(station_name: str, aqi_value: int, category: str, dominant_pollutant: str, wind: WindData | None, fires: list[FireDetection], news: list[NewsResult], trajectory: AirMassTrajectory | None=None) -> str:
    lines = [f'Station: {station_name}', f'Computed AQI: {aqi_value} ({category})', f'Dominant pollutant: {dominant_pollutant}']
    if wind:
        lines.append(f'Wind: {wind.speed_mps} m/s from {compass_direction(wind.direction_deg)}, conditions: {wind.description}')
    if trajectory is not None:
        lines.extend(_trajectory_lines(trajectory))
    elif fires:
        nearest = fires[0]
        lines.append(f'Nearby fire detections: {len(fires)}, nearest {nearest.distance_km} km away')
    if news:
        headlines = '; '.join((n.title for n in news[:3]))
        lines.append(f'Relevant recent news headlines: {headlines}')
    return '\n'.join(lines)

def _fallback_explanation(aqi_value: int, category: str, dominant_pollutant: str, trajectory: AirMassTrajectory | None=None) -> str:
    text = f'Air quality is {category} (AQI {aqi_value}), primarily driven by {dominant_pollutant}.'
    if trajectory is not None:
        text += ' ' + trajectory.summary()
    return text

def get_explanation(station_name: str, aqi_value: int, category: str, dominant_pollutant: str, wind: WindData | None, fires: list[FireDetection], news: list[NewsResult], api_key: str='', trajectory: AirMassTrajectory | None=None) -> str:
    user_prompt = _build_user_prompt(station_name, aqi_value, category, dominant_pollutant, wind, fires, news, trajectory)
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        last_err = None
        for model_name in FALLBACK_MODELS:
            try:
                response = client.models.generate_content(model=model_name, contents=user_prompt, config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.7))
                text = response.text.strip()
                import re
                sentences = re.split('\\.(?!\\d)', text)
                first = sentences[0].strip()
                return first + '.' if first else text
            except Exception as e:
                last_err = e
                print(f'Model {model_name} failed ({type(e).__name__}), trying next...')
        raise last_err
    except Exception as e:
        print(f'LLM explanation call failed ({type(e).__name__}: {e}), using fallback.')
        return _fallback_explanation(aqi_value, category, dominant_pollutant, trajectory)