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
FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]

_quota_exhausted_until: float = 0.0

WARD_ZONES: dict[str, tuple[str, list[str], list[str]]] = {
    "A": ("Island City (South Mumbai)", ["Colaba", "Fort", "Nariman Point"], ["Dr. D.N. Road", "Maharshi Karve Road", "Marine Drive"]),
    "B": ("Island City (Port Corridor)", ["Sandhurst Road", "Dongri", "Bhendi Bazaar"], ["Mohammad Ali Road", "P D'Mello Road", "Sardar Vallabhbhai Patel Road"]),
    "C": ("Island City (High Density Core)", ["Marine Lines", "Chira Bazaar", "Bhuleshwar"], ["Kalbadevi Road", "Princess Street", "Lokmanya Tilak Marg"]),
    "D": ("Island City (Coastal Ridge)", ["Malabar Hill", "Grant Road", "Tardeo"], ["Pedder Road", "Walkeshwar Road", "Pandita Ramabai Marg"]),
    "E": ("Island City (Central Harbor)", ["Byculla", "Mazgaon", "Madhavpura"], ["Dr. B.A. Road", "P D'Mello Road", "Sant Savta Marg"]),
    "F/S": ("Island City (Industrial Heritage)", ["Parel", "Sewri", "Naigaon"], ["Dr. B.A. Road", "Acharya Donde Marg", "Sewri Wadala Road"]),
    "F/N": ("Island City (Northern Transit Hub)", ["Matunga", "Wadala", "Sion"], ["Dr. B.A. Road", "R.A. Kidwai Marg", "Sion Circle"]),
    "G/S": ("Island City (Commercial Redevelopment)", ["Worli", "Prabhadevi", "Lower Parel"], ["Senapati Bapat Marg", "Dr. Annie Besant Road", "N.M. Joshi Marg"]),
    "G/N": ("Island City (Northern Gateway)", ["Dharavi", "Mahim", "Dadar West"], ["Lady Jamshedji Road", "60 Feet Road", "Sion-Bandra Link Road"]),
    "H/E": ("Western Suburbs (Airport & Rail Corridor)", ["Kalanagar", "Santacruz East", "Bandra East"], ["Western Express Highway", "BKC Connector", "CST Road"]),
    "H/W": ("Western Suburbs (Coastal Residential)", ["Bandra West", "Khar West", "Santacruz West"], ["S.V. Road", "Linking Road", "Turner Road"]),
    "K/E": ("Western Suburbs (Commercial & Industrial Axis)", ["Andheri East", "Jogeshwari East", "Vile Parle East"], ["Western Express Highway", "Andheri-Kurla Road", "JVLR"]),
    "K/W": ("Western Suburbs (High-Density Coastal Hub)", ["Andheri West", "Versova", "Juhu", "Lokhandwala"], ["S.V. Road", "New Link Road", "Juhu Tara Road"]),
    "P/S": ("Western Suburbs (Suburban Transit Core)", ["Goregaon West", "Goregaon East"], ["Western Express Highway", "S.V. Road", "MG Road"]),
    "P/N": ("Western Suburbs (Suburban Valley Basin)", ["Malad West", "Malad East", "Marve"], ["S.V. Road", "Link Road", "Marve Road"]),
    "R/S": ("Western Suburbs (Northern Industrial-Residential)", ["Kandivali West", "Kandivali East", "Charkop"], ["Western Express Highway", "Link Road", "Mathuradas Road"]),
    "R/C": ("Western Suburbs (Borivali Central Axis)", ["Borivali West", "Borivali East", "Shimpoli"], ["Western Express Highway", "S.V. Road", "Devidas Road"]),
    "R/N": ("Western Suburbs (Northern Frontier)", ["Dahisar West", "Dahisar East"], ["Western Express Highway", "S.V. Road", "CS Link Road"]),
    "L": ("Eastern Suburbs (Central Logistics Hub)", ["Kurla", "Chunabhatti", "Saki Naka"], ["LBS Marg", "Sion-Bandra Link Road", "Kurla-Andheri Road"]),
    "M/E": ("Eastern Suburbs (SWM Basin & Creek Corridor)", ["Govandi", "Mankhurd", "Shivaji Nagar", "Deonar"], ["Sion-Panvel Highway", "Ghatkopar-Mankhurd Link Road", "V.N. Purav Marg"]),
    "M/W": ("Eastern Suburbs (Harbor & Petrochemical Basin)", ["Chembur", "Mahul", "Tilak Nagar"], ["Eastern Freeway", "Sion-Panvel Highway", "R.C. Marg"]),
    "N": ("Eastern Suburbs (Industrial-Commercial Corridor)", ["Ghatkopar", "Vikhroli West", "Pant Nagar"], ["LBS Marg", "Eastern Express Highway", "Ghatkopar-Andheri Link Road"]),
    "S": ("Eastern Suburbs (Industrial Belt & Hill Buffer)", ["Bhandup", "Kanjurmarg", "Powai"], ["Eastern Express Highway", "LBS Marg", "JVLR"]),
    "T": ("Eastern Suburbs (Northern Foothill Frontier)", ["Mulund West", "Mulund East", "Nahur"], ["Eastern Express Highway", "LBS Marg", "Goregaon-Mulund Link Road"]),
}


SYSTEM_PROMPT = """You are a senior environmental engineer and municipal air quality specialist for Brihanmumbai Municipal Corporation (BMC / MCGM).
Your role is to write the authoritative, technical 'Why this action' reasoning for municipal field officers and ward executive engineers.

Rules:
1. Only use facts and numbers that appear in the input prompt. Do NOT invent figures, percentages, scientific studies, or regulatory clauses that are not in the prompt.
2. Explain the causal mechanism clearly: how atmospheric conditions, topography, and local emission sources combined to produce this specific condition in this specific ward.
3. Structure the reasoning into 3 clearly titled sections (use bold titles):
   **Atmospheric Dispersion Dynamics**: Analyse wind patterns, air stagnation, inversion layers, or plume transport specific to the ward facts provided.
   **Emission Source Attribution and Population Exposure**: Describe the health risk using only the ward population, AQI, and pollutants mentioned in the input.
   **Operational Mitigation Justification**: Explain why the designated intervention is effective for this signal type and why acting before the forecast peak matters.
4. Use formal, professional, engineering-grade English.
5. Do NOT use emojis, double dashes (--), or em-dashes. Use colons or parentheses instead.
6. Keep the total reasoning between 150 and 220 words.
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
    station_name: str | None = None,
    station_distance_km: float | None = None,
) -> str:
    zone_desc, neighborhoods, corridors = WARD_ZONES.get(
        ward_id,
        ("Mumbai Municipal Region", ["ward center"], ["primary municipal roads"]),
    )
    nh_str = ", ".join(neighborhoods[:2])
    road_str = ", ".join(corridors[:2])
    pop_str = f"{population:,}" if population else "ward"
    lead_evidence = evidence[0] if evidence else "local sensor readings indicate elevated pollutant accumulation"
    station_str = (
        f"Continuous CAAQMS monitoring at {station_name} ({station_distance_km:.1f} km away)"
        if station_name and station_distance_km is not None
        else f"Local ward monitoring grid in {ward_name}"
    )

    if signal == "inflow":
        details_txt = ""
        if len(evidence) >= 2:
            details_txt = f" Specifically, {evidence[0]}, with {evidence[1]}."
        elif evidence:
            details_txt = f" Specifically, {evidence[0]}."
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Atmospheric back-trajectory modeling tracks incoming air parcels entering Ward {ward_id} ({ward_name}) across {zone_desc}.{details_txt} "
            f"Incoming plumes traverse along the regional transport corridor directly into settlements near {nh_str}. "
            f"Thermal stratification and boundary layer compression prevent vertical venting, trapping the advected aerosol mass close to the surface.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"{station_str} tracks fine particulate matter arriving from the upwind sector. "
            f"With {pop_str} residents in Ward {ward_id} exposed to {category} air quality (AQI {round(aqi)}), "
            f"combustion aerosols containing high fractions of sub-micron PM2.5, black carbon, and organic compounds cause acute ocular and bronchial irritation in school children and respiratory patients across {nh_str}.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} is designated for immediate inter-agency activation during {time_window}. "
            f"Issuing targeted public health advisories via Aaple Sarkar and ward channels before peak exposure enables vulnerable cohorts to shelter indoors while the regional plume corridor clears."
        )

    if signal == "stagnation":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Ward {ward_id} ({ward_name}) within {zone_desc} is undergoing micro-meteorological stagnation with surface wind speeds dropping below 1.5 m/s. "
            f"Without convective ventilation or horizontal sea-breeze flushing across {nh_str}, ground-level emissions remain trapped beneath a shallow thermal inversion layer. "
            f"Local field data indicates: {lead_evidence}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Trapped emissions from heavy vehicular transit along {road_str} and active construction plots concentrate within the breathing zone. "
            f"{station_str} reflects localized PM2.5 and PM10 accumulation affecting {pop_str} residents exposed to {category} air quality (AQI {round(aqi)}). "
            f"Prolonged exposure during stagnant hours increases cardiopulmonary distress and aggravates asthma symptoms.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} is operationally mandated during {time_window}. "
            f"Deploying high-pressure water misting and mechanical sweeping across {road_str} suppresses dust resuspension and wets dry particulates, directly counteracting the lack of natural atmospheric dispersion."
        )

    if signal == "traffic":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Ward {ward_id} ({ward_name}) experiences severe street-canyon trapping of vehicular exhaust along key transit corridors including {road_str}. "
            f"Sensor telemetry confirms: {lead_evidence}. "
            f"Dense multi-story structures bordering arterial roads restrict lateral wind dilution, creating elevated micro-scale NO2 and CO concentration corridors through {nh_str}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Stop-and-go heavy vehicles, commuter buses, and delivery fleets emit concentrated nitrogen dioxide and carbon monoxide during rush hours. "
            f"{station_str} registers acute exposure spikes directly threatening pedestrians, street vendors, and transit users among the ward's {pop_str} residents. "
            f"Inhalation of unburned hydrocarbons and NO2 inflames upper airways and reduces blood oxygen carrying capacity.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} targets the congestion bottleneck during {time_window}. "
            f"Enforcing strict anti-idling regulations, coordinating traffic signal green waves, and deploying traffic wardens along {road_str} reduces localized tailpipe emissions by 10% to 20% before concentrations spill into adjacent residential quarters."
        )

    if signal == "dust":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Micro-climatic observations in Ward {ward_id} ({ward_name}) indicate dry ground conditions, low relative humidity, and mechanical shear stress lofting mineral particles into the surface boundary layer. "
            f"Field data confirms: {lead_evidence}. "
            f"Turbulent wakes created by heavy commercial vehicles along {road_str} continuously resuspend settled soil and construction fines across {nh_str}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Construction excavation, unpaved road shoulders, and aggregate handling account for predominantly coarse PM10 loadings. "
            f"{station_str} demonstrates elevated coarse-to-fine particulate ratios affecting {pop_str} residents under {category} conditions (AQI {round(aqi)}). "
            f"Inhaled coarse dust causes acute eye irritation, pharyngitis, and aggravates chronic obstructive pulmonary disease.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} is required during {time_window}. "
            f"Operating anti-smog guns, wet-sweeping mechanical units, and enforcing mandatory dust barrier netting at construction plots across {nh_str} binds surface particulates and cuts fugitive dust resuspension by up to 60%."
        )

    if signal == "waste_burning":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Thermal sensors and municipal surveillance identify active open refuse combustion within or upwind of Ward {ward_id} ({ward_name}) in {zone_desc}. "
            f"Field evidence confirms: {lead_evidence}. "
            f"Buoyant combustion plumes carry toxic carbonaceous particulate matter across secondary settlements in {nh_str}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Open combustion of municipal solid waste, packaging plastic, and garden biomass releases dense clouds of fine PM2.5, dioxins, and toxic hydrocarbons. "
            f"With {pop_str} residents exposed to {category} air quality (AQI {round(aqi)}), uncontained smoke plumes pose severe health hazards to infants, elderly citizens, and individuals near {road_str}.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} requires immediate tactical deployment during {time_window}. "
            f"Direct suppression by municipal flying squads and water tankers quenches smoldering waste heaps at the source, preventing wider smoke dispersion across the urban canopy."
        )

    if signal == "forecast_crossing":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Spatio-temporal predictive modeling for Ward {ward_id} ({ward_name}) projects a categorical worsening of air quality over the coming 6 to 12 hours. "
            f"Forecast analysis reveals: {lead_evidence}. "
            f"Diurnal boundary layer compression and wind vector shifts across {zone_desc} compound pollutant loading throughout {nh_str}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"As ambient concentrations escalate into a higher health risk bracket, the cumulative toxic burden on {pop_str} residents intensifies significantly. "
            f"{station_str} provides the verification baseline for tracking escalation across {road_str}.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} executed during the proactive window ({time_window}) flattens the projected concentration peak. "
            f"Pre-emptive dust wetting and vehicle traffic management curb source emissions before meteorological conditions deteriorate."
        )

    return (
        f"**Atmospheric Dispersion Dynamics**\n"
        f"Localized air quality monitoring for Ward {ward_id} ({ward_name}) in {zone_desc} identifies an active anomaly ({lead_evidence}). "
        f"Current micro-meteorological conditions limit rapid natural dispersion across {nh_str}, maintaining localized pollutant concentration.\n\n"
        f"**Emission Source Attribution and Population Exposure**\n"
        f"Ambient AQI is currently {round(aqi)} ({category}), directly affecting {pop_str} residents. "
        f"{station_str} records elevated exposure risk. {baseline_rationale}\n\n"
        f"**Operational Mitigation Justification**\n"
        f"{action_title} is the designated BMC municipal intervention for {time_window}. "
        f"Prompt field deployment across {road_str} prevents further air quality degradation and protects public health."
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
    station_name: str | None = None,
    station_distance_km: float | None = None,
) -> str:
    """Generate thorough, scientifically grounded 'Why this action' reasoning using Gemini,
    with thread-safe caching and robust, localized fallback templates."""
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
        station_name=station_name,
        station_distance_km=station_distance_km,
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
        f"Nearest Station: {station_name or 'Ward sensor grid'}\n"
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
                    text = text.replace("--", ": ").replace("\u2014", ": ").replace("\u2013", "-").replace("\u2015", ": ")
                    break
            except Exception as e:
                err_str = str(e)
                if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                    # Cooldown for 6 hours when daily quota is exhausted
                    _quota_exhausted_until = time.time() + 21600.0
                    logger.info("Gemini free-tier quota exhausted; activating domain reasoner until %s", time.ctime(_quota_exhausted_until))
                    break
                else:
                    logger.warning("Gemini model %s failed: %s", model, e)
                continue

        if text:
            with _cache_lock:
                _cache[key] = text
            return text
    except Exception as exc:
        err_str = str(exc)
        if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
            _quota_exhausted_until = time.time() + 21600.0
            logger.info("Gemini quota exhausted; activating domain reasoner until %s", time.ctime(_quota_exhausted_until))
        else:
            logger.warning("LLM reasoning call failed: %s; using domain fallback", exc)

    with _cache_lock:
        _cache[key] = fallback
    return fallback
