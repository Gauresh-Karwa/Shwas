from google import genai
from google.genai import types
from app.attribution.weather_client import WindData, compass_direction
from app.attribution.fire_client import FireDetection
from app.attribution.news_search import NewsResult
from app.config import settings
MODEL = 'gemini-3.5-flash'
FALLBACK_MODELS = ['gemini-3.5-flash', 'gemini-3.5-flash-lite']
SYSTEM_PROMPT = 'You explain air quality to everyday people in India in ONE short, natural, conversational sentence - like a friendly weather app notification, NOT a report. You will be given fixed facts: a station name, a computed AQI value and category, the dominant pollutant, wind conditions, nearby fire detections, and relevant recent news.\n\nRules you must follow exactly:\n- Use ONLY the facts provided. Never invent a cause not supported by them.\n- Never state a cause as certain. Use hedged language: "likely", "may be linked to", "could be contributing".\n- Never state or imply an AQI value or category different from the one given.\n- If a factor (wind, fire, news) has no data, simply don\'t mention it — don\'t say "no data" or apologize for missing it.\n- ONE sentence only. No line breaks. No paragraphs. Under 25 words.\n- NEVER use phrases like "the AQI is currently", "falls into the category", "the dominant pollutant contributing to this reading is", or any similarly clinical/report-style wording.\n- Write like you\'re texting a friend a quick heads-up, not filing a report.\n\nExample of the tone wanted (for a different reading, don\'t copy the facts):\n"Air\'s decent near Sion right now, mild PM2.5 with a light breeze keeping things fairly clear."\n\nAnother example, this time with a fire nearby:\n"Bandra\'s air is a bit rough today, likely worsened by a nearby fire and winds blowing smoke this way."\n'

def _build_user_prompt(station_name: str, aqi_value: int, category: str, dominant_pollutant: str, wind: WindData | None, fires: list[FireDetection], news: list[NewsResult]) -> str:
    lines = [f'Station: {station_name}', f'Computed AQI: {aqi_value} ({category})', f'Dominant pollutant: {dominant_pollutant}']
    if wind:
        lines.append(f'Wind: {wind.speed_mps} m/s from {compass_direction(wind.direction_deg)}, conditions: {wind.description}')
    if fires:
        nearest = fires[0]
        lines.append(f'Nearby fire detections: {len(fires)}, nearest {nearest.distance_km} km away')
    if news:
        headlines = '; '.join((n.title for n in news[:3]))
        lines.append(f'Relevant recent news headlines: {headlines}')
    return '\n'.join(lines)

def _fallback_explanation(aqi_value: int, category: str, dominant_pollutant: str) -> str:
    return f'Air quality is {category} (AQI {aqi_value}), primarily driven by {dominant_pollutant}.'

def get_explanation(station_name: str, aqi_value: int, category: str, dominant_pollutant: str, wind: WindData | None, fires: list[FireDetection], news: list[NewsResult], api_key: str='') -> str:
    user_prompt = _build_user_prompt(station_name, aqi_value, category, dominant_pollutant, wind, fires, news)
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
        return _fallback_explanation(aqi_value, category, dominant_pollutant)
