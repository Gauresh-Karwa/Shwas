"""
Action Reasoner: generates authoritative, scientifically rigorous municipal engineering
reasoning ('Why this action') using Gemini (LLM) with thread-safe caching and robust fallbacks.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"
FALLBACK_MODELS = ["gemini-2.5-flash"]

_quota_exhausted_until: float = 0.0


SYSTEM_PROMPT = """You are a senior environmental engineer and municipal air quality specialist for Brihanmumbai Municipal Corporation (BMC / MCGM).
Your role is to write the authoritative, technical 'Why this action' reasoning for municipal field officers and ward executive engineers.

Rules:
1. Explain the causal mechanism thoroughly: how atmospheric physics, topography, and local emission sources combined to produce this specific condition in this specific ward.
2. Structure the reasoning into 3 clearly titled sections (use bold titles):
   **Atmospheric Dispersion Dynamics**: Analyze wind patterns, air stagnation, inversion layers, or plume transport specific to the ward facts.
   **Emission Source Attribution and Population Exposure**: Quantify the health risk, highlighting the ward's exposed population, primary pollutants (PM2.5, PM10, NO2, CO), and vulnerable demographics (pedestrians, children, schools, hospitals).
   **Operational Mitigation Justification**: Scientifically explain why the designated intervention (e.g., targeted water misting, anti-smog guns, anti-idling sweeps, perimeter patrols) is effective when executed before the forecast peak, and why delay leads to worsening exposure.
3. Use formal, professional, engineering-grade English.
4. Do NOT use emojis.
5. Do NOT use double dashes (--) or em-dashes. Use clear punctuation, colons, or parentheses.
6. Keep the total reasoning substantive and around 150 to 220 words.
"""

_cache: dict[str, str] = {}
_cache_lock = threading.Lock()


def _cache_key(
    ward_id: str,
    signal: str,
    aqi: float,
    evidence: list[str],
) -> str:
    raw = f"{ward_id}:{signal}:{round(aqi, -1)}:{':'.join(evidence[:2])}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _build_fallback_reasoning(
    ward_name: str,
    ward_id: str,
    population: int,
    aqi: float,
    category: str,
    signal: str,
    action_title: str,
    evidence: list[str],
    time_window: str,
    baseline_rationale: str,
) -> str:
    lead_evidence = evidence[0] if evidence else "local sensor readings indicate elevated pollutant accumulation"
    pop_str = f"{population:,}" if population else "ward"

    if signal == "stagnation":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Ward {ward_id} ({ward_name}) is experiencing calm atmospheric conditions where horizontal wind advection has dropped below 1.5 m/s. "
            f"Without sufficient wind speed to ventilate the urban canopy, surface emissions cannot disperse and accumulate near the ground. "
            f"The numerical forecast projects a continued rise in ambient concentration over the next 6 to 12 hours.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Fugitive road dust resuspension, construction activities, and vehicular exhaust are trapped within the shallow surface layer. "
            f"With {pop_str} residents exposed to {category} air quality (AQI {round(aqi)}), prolonged stagnation significantly elevates inhalation doses of fine PM2.5 and PM10 particles, creating acute risks for children, elderly residents, and asthma patients.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} is scientifically required during the calm window ({time_window}). "
            f"Mechanical wet sweeping and construction sealing prevent additional particulate mass from entering the stagnant air shed before the peak accumulation hour occurs."
        )

    if signal == "waste_burning":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Thermal satellite sensors and localized detections identify active open combustion upwind of Ward {ward_id} ({ward_name}). "
            f"Combustion plumes from uncontained municipal solid waste emit dense, buoyant plumes of fine carbonaceous aerosols that travel 3 to 8 km downwind along prevailing breeze corridors.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Open refuse combustion produces high concentrations of toxic PM2.5, black carbon, and volatile organic compounds. "
            f"For {pop_str} residents living in the plume path, exposure to unrefined combustion smoke induces acute respiratory tract inflammation and triggers rapid AQI degradation.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} provides immediate point-source suppression. "
            f"Deploying municipal flying squads and fire tenders within {time_window} extinguishes combustion at the perimeter before diurnal wind shifts spread smoke across broader residential settlements."
        )

    if signal == "forecast_crossing":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Predictive spatio-temporal modeling indicates a categorical worsening of air quality in Ward {ward_id} ({ward_name}) within the next 6 hours. "
            f"Diurnal boundary layer compression combined with incoming regional transport is expected to drive AQI beyond current levels.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"As ambient concentrations transition to a higher severity category, the cumulative particulate burden on {pop_str} residents escalates sharply. "
            f"Pre-emptive intervention targets the primary local contributors (road dust, heavy transport, unpaved surfaces) to flatten the morning or evening peak.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} executed during the pre-peak window ({time_window}) prevents baseline emissions from compounding with the incoming regional surge. "
            f"Proactive dust suppression and health advisories deliver measurable exposure reductions compared to reactive post-peak responses."
        )

    if signal == "traffic":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Corridor monitoring stations in Ward {ward_id} ({ward_name}) show localized spikes in NO2 and CO exceeding typical baseline values during peak commuting hours. "
            f"Traffic-induced street canyon trapping prevents rapid lateral dilution of tailpipe emissions along dense arterial roads.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Stop-and-go heavy vehicles, idling commercial transit, and high traffic density generate toxic nitrogen dioxide and ultrafine particles. "
            f"Pedestrians, commuters, and residents along key corridors ({pop_str} total ward population) face direct exposure to acute vehicular exhaust.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} addresses vehicular congestion directly during {time_window}. "
            f"Optimizing traffic signal green waves and enforcing strict anti-idling limits cuts corridor emissions by 10% to 20% during peak transit hours."
        )

    if signal == "dust":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Low ambient humidity, dry road surfaces, and coarse-dominated particulate ratios (PM10 exceeding PM2.5) confirm mechanical dust resuspension across Ward {ward_id} ({ward_name}). "
            f"Vehicular shear stress and wind turbulence continuously loft dry surface particles into the breathing zone.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Construction excavation, unpaved shoulders, and aggregate transport account for high PM10 loadings impacting {pop_str} residents. "
            f"Coarse particles cause upper respiratory irritation, corneal distress, and reduced ambient visibility.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} executed during daylight hours ({time_window}) agglomerates surface particles via moisture binding. "
            f"Water spraying and mandatory stockpile netting eliminate the fugitive dust source before wind speeds increase."
        )

    if signal == "inflow":
        details_txt = ""
        if len(evidence) >= 2:
            details_txt = f" Specifically, {evidence[0].lower()}, with {evidence[1].lower()}."
        elif evidence:
            details_txt = f" Specifically, {evidence[0].lower()}."
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Atmospheric back-trajectory analysis traces incoming air parcels arriving at Ward {ward_id} ({ward_name}) across regional fire hotspots located upwind.{details_txt} "
            f"Regional advection transports smoke plumes across ward boundaries regardless of local industrial or traffic compliance.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Aged combustion aerosols entering the ward consist primarily of fine PM2.5 and carbonaceous particulate matter. "
            f"Even without local emission violations, {pop_str} residents face increased background haze and respiratory irritation.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} provides critical public health risk mitigation during {time_window}. "
            f"Alerting sensitive groups, schools, and healthcare facilities enables timely indoor sheltering and exposure avoidance while the regional plume passes."
        )


    return (
        f"**Atmospheric Dispersion Dynamics**\n"
        f"Localized air quality monitoring for Ward {ward_id} ({ward_name}) identifies an active anomaly ({lead_evidence}). "
        f"Current micro-meteorological conditions limit rapid natural dispersion, maintaining localized pollutant concentration.\n\n"
        f"**Emission Source Attribution and Population Exposure**\n"
        f"Ambient AQI is currently {round(aqi)} ({category}), directly affecting {pop_str} residents. "
        f"{baseline_rationale}\n\n"
        f"**Operational Mitigation Justification**\n"
        f"{action_title} is the recommended BMC municipal intervention for {time_window}. "
        f"Prompt field deployment prevents further air quality degradation and protects public health."
    )


def generate_action_reasoning(
    ward_name: str,
    ward_id: str,
    population: int,
    aqi: float,
    category: str,
    signal: str,
    action_title: str,
    evidence: list[str],
    time_window: str,
    baseline_rationale: str,
) -> str:
    """Generate thorough, scientifically grounded 'Why this action' reasoning using Gemini,
    with thread-safe caching and robust fallback templates."""
    key = _cache_key(ward_id, signal, aqi, evidence)
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    fallback = _build_fallback_reasoning(
        ward_name=ward_name,
        ward_id=ward_id,
        population=population,
        aqi=aqi,
        category=category,
        signal=signal,
        action_title=action_title,
        evidence=evidence,
        time_window=time_window,
        baseline_rationale=baseline_rationale,
    )

    global _quota_exhausted_until
    import os
    if os.getenv("PYTEST_CURRENT_TEST") or not settings.GEMINI_API_KEY or time.time() < _quota_exhausted_until:
        with _cache_lock:
            _cache[key] = fallback
        return fallback

    user_prompt = (
        f"Ward: {ward_name} (Ward {ward_id})\n"
        f"Population: {population:,} residents\n"
        f"Current AQI: {round(aqi)} ({category})\n"
        f"Detected Signal: {signal}\n"
        f"Evidence: {'; '.join(evidence) if evidence else 'Elevated sensor reading'}\n"
        f"Action Title: {action_title}\n"
        f"Operational Time Window: {time_window}\n"
        f"Scientific Context: {baseline_rationale}\n"
    )

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        text: str | None = None
        for model in FALLBACK_MODELS:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.3,
                    ),
                )
                if response.text and response.text.strip():
                    text = response.text.strip()
                    # Clean out any accidental double dashes
                    text = text.replace("--", ": ").replace("\u2014", ": ").replace("\u2013", "-")
                    break
            except Exception as e:
                err_str = str(e)
                logger.warning("Gemini model %s failed for action reasoning: %s", model, e)
                if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                    _quota_exhausted_until = time.time() + 600.0
                continue

        if text:
            with _cache_lock:
                _cache[key] = text
            return text
    except Exception as exc:
        err_str = str(exc)
        logger.warning("LLM reasoning call failed: %s; using domain fallback", exc)
        if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
            _quota_exhausted_until = time.time() + 600.0

    with _cache_lock:
        _cache[key] = fallback
    return fallback
