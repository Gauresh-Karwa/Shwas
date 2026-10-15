"""
Action Reasoner: generates authoritative, scientifically rigorous municipal engineering
reasoning ('Why this action') using Gemini (LLM) with thread-safe caching and robust fallbacks.
Supports English (en), Hindi (hi), and Marathi (mr).
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

# ---------------------------------------------------------------------------
# System prompts — one per language. All share the same output structure.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_EN = """You are a senior environmental engineer and BMC municipal air quality officer in Mumbai.
Write the 'Why this action' field for the Shwas municipal dashboard — read by ward-level field officers and executive engineers.

Rules:
1. Use ONLY the facts and numbers supplied in the input. Do not invent statistics, studies, or policy clauses.
2. Be specific to the exact ward, street names, and neighbourhoods mentioned. Do NOT write generically.
3. Explain the causal chain: how this ward's atmospheric state + local emission sources produced this specific AQI reading.
4. Structure the response into exactly 3 bold-titled sections:
   **Atmospheric Dispersion Dynamics**: Wind speeds, inversion layer height, sea-breeze collapse, or back-trajectory path — specific to this ward's geography.
   **Emission Source Attribution and Population Exposure**: Name the specific pollutant sources in this ward. Quantify exposure using the given AQI, population, and category.
   **Operational Mitigation Justification**: Why this specific action, why now, and what measurable effect it has for the ward's residents.
5. Write in confident, professional, field-officer-grade English. No hedging.
6. No emojis, no double dashes, no em-dashes. Use colons or parentheses.
7. Between 160 and 230 words total.
"""

SYSTEM_PROMPT_HI = """आप मुंबई में BMC (बृहन्मुंबई महानगरपालिका) के वरिष्ठ पर्यावरण अभियंता और वायु गुणवत्ता अधिकारी हैं।
आपका काम है Shwas डैशबोर्ड के लिए 'यह कार्रवाई क्यों' अनुभाग लिखना — जिसे वार्ड के फील्ड अधिकारी और कार्यकारी अभियंता पढ़ते हैं।

नियम:
1. केवल इनपुट में दिए गए तथ्यों और आंकड़ों का उपयोग करें। कोई नई संख्या, अध्ययन, या नीति धाराएं न बनाएं।
2. उस वार्ड, उस सड़क, और उन मोहल्लों का स्पष्ट उल्लेख करें जो इनपुट में दिए गए हैं। सामान्य भाषा से बचें।
3. कारण-परिणाम श्रृंखला स्पष्ट करें: इस वार्ड की वायुमंडलीय दशा और स्थानीय उत्सर्जन स्रोतों ने मिलकर यह AQI स्तर क्यों बनाया।
4. उत्तर को ठीक 3 मोटे-शीर्षक वाले अनुभागों में लिखें:
   **वायुमंडलीय प्रसार गतिशीलता**: हवा की गति, व्युत्क्रमण परत, समुद्री हवा का ठहराव — इस वार्ड की भूगोलिक स्थिति के अनुसार।
   **उत्सर्जन स्रोत और जनसंख्या एक्सपोज़र**: इस वार्ड के विशिष्ट प्रदूषण स्रोत बताएं। दिए गए AQI, जनसंख्या और श्रेणी से एक्सपोज़र का आकलन करें।
   **परिचालन शमन औचित्य**: यह विशेष कार्रवाई क्यों, अभी क्यों, और इस वार्ड के निवासियों पर इसका क्या प्रभाव होगा।
5. आत्मविश्वास से भरी, पेशेवर, फील्ड अधिकारी स्तर की हिंदी में लिखें। संकोच न करें।
6. कोई इमोजी नहीं, कोई डबल डैश नहीं। कोलन या कोष्ठक का उपयोग करें।
7. कुल 160 से 230 शब्दों के बीच रखें।
8. सभी तकनीकी/वैज्ञानिक संज्ञाएं (BMC, AQI, PM2.5, PM10, NO2, SAFAR, CAAQMS) अंग्रेज़ी में ही रखें।
"""

SYSTEM_PROMPT_MR = """तुम्ही मुंबईतील BMC (बृहन्मुंबई महानगरपालिका) चे वरिष्ठ पर्यावरण अभियंता आणि हवा गुणवत्ता अधिकारी आहात.
तुमचे कार्य Shwas डॅशबोर्डसाठी 'ही कृती का' हा विभाग लिहिणे आहे — जो प्रभागातील क्षेत्र अधिकारी आणि कार्यकारी अभियंते वाचतात.

नियम:
1. फक्त इनपुटमध्ये दिलेले तथ्य व आकडे वापरा. नवीन संख्या, अभ्यास किंवा धोरण कलमे तयार करू नका.
2. दिलेल्या प्रभागाचे, रस्त्याचे आणि परिसराचे स्पष्ट उल्लेख करा. सामान्य भाषा टाळा.
3. कारण-परिणाम साखळी स्पष्ट करा: या प्रभागाच्या वातावरणीय स्थितीने आणि स्थानिक उत्सर्जन स्रोतांनी मिळून हे AQI पातळी का निर्माण केली.
4. उत्तर नेमक्या 3 ठळक-शीर्षक असलेल्या विभागांमध्ये लिहा:
   **वायुमंडलीय प्रसार गतिशास्त्र**: वाऱ्याचा वेग, व्युत्क्रमण थर, सागरी वाऱ्याचा थांबा — या प्रभागाच्या भौगोलिक स्थितीनुसार.
   **उत्सर्जन स्रोत आणि लोकसंख्या एक्सपोजर**: या प्रभागातील विशिष्ट प्रदूषण स्रोत सांगा. दिलेल्या AQI, लोकसंख्या व श्रेणीनुसार एक्सपोजरचे मूल्यांकन करा.
   **परिचालन उपशमन औचित्य**: ही विशिष्ट कृती का, आत्ता का, आणि या प्रभागातील रहिवाशांवर त्याचा काय परिणाम होईल.
5. आत्मविश्वासपूर्ण, व्यावसायिक, क्षेत्र-अधिकारी दर्जाच्या मराठीत लिहा. संकोच नको.
6. कोणतेही इमोजी नाही, दुहेरी डॅश नाही. कोलन किंवा कंसाचा वापर करा.
7. एकूण 160 ते 230 शब्दांच्या दरम्यान ठेवा.
8. सर्व तांत्रिक/वैज्ञानिक संज्ञा (BMC, AQI, PM2.5, PM10, NO2, SAFAR, CAAQMS) इंग्रजीतच ठेवा.
"""

SYSTEM_PROMPTS = {"en": SYSTEM_PROMPT_EN, "hi": SYSTEM_PROMPT_HI, "mr": SYSTEM_PROMPT_MR}

_cache: dict[str, str] = {}
_cache_lock = threading.Lock()


def _cache_key(
    ward_id: str,
    signal: str,
    aqi: float,
    evidence: list[str],
    lang: str = "en",
) -> str:
    raw = f"{lang}:{ward_id}:{signal}:{round(aqi, -1)}:{':'.join(evidence[:2])}"
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
    lang: str = "en",
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

    if lang == "hi":
        return _build_fallback_hi(
            ward_name=ward_name, ward_id=ward_id, population=population, aqi=aqi,
            category=category, signal=signal, action_title=action_title,
            evidence=evidence, time_window=time_window, lead_evidence=lead_evidence,
            nh_str=nh_str, road_str=road_str, pop_str=pop_str, station_str=station_str,
            zone_desc=zone_desc,
        )
    if lang == "mr":
        return _build_fallback_mr(
            ward_name=ward_name, ward_id=ward_id, population=population, aqi=aqi,
            category=category, signal=signal, action_title=action_title,
            evidence=evidence, time_window=time_window, lead_evidence=lead_evidence,
            nh_str=nh_str, road_str=road_str, pop_str=pop_str, station_str=station_str,
            zone_desc=zone_desc,
        )
    return _build_fallback_en(
        ward_name=ward_name, ward_id=ward_id, population=population, aqi=aqi,
        category=category, signal=signal, action_title=action_title,
        evidence=evidence, time_window=time_window, lead_evidence=lead_evidence,
        nh_str=nh_str, road_str=road_str, pop_str=pop_str, station_str=station_str,
        zone_desc=zone_desc, baseline_rationale=baseline_rationale,
    )


def _build_fallback_en(
    ward_name, ward_id, population, aqi, category, signal, action_title,
    evidence, time_window, lead_evidence, nh_str, road_str, pop_str, station_str,
    zone_desc, baseline_rationale,
) -> str:
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
            f"combustion aerosols containing sub-micron PM2.5, black carbon, and organic compounds cause acute bronchial and ocular irritation across {nh_str}.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} is designated for immediate inter-agency activation during {time_window}. "
            f"Issuing targeted public health advisories via Aaple Sarkar and ward channels before peak exposure enables vulnerable cohorts to shelter indoors while the regional plume corridor clears."
        )

    if signal == "stagnation":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Ward {ward_id} ({ward_name}) within {zone_desc} is undergoing micro-meteorological stagnation. "
            f"Surface wind speeds have dropped below 1.5 m/s, ending sea-breeze flushing across {nh_str}. "
            f"A shallow nocturnal thermal inversion is trapping ground-level emissions. Field data: {lead_evidence}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Trapped emissions from heavy vehicular transit along {road_str} and active construction sites concentrate within the breathing zone. "
            f"{station_str} reflects PM2.5 and PM10 accumulation affecting {pop_str} residents under {category} conditions (AQI {round(aqi)}). "
            f"Prolonged stagnant-air exposure sharply increases cardiopulmonary distress and aggravates asthma.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} is operationally mandated during {time_window}. "
            f"Deploying high-pressure water misting and mechanical sweeping along {road_str} suppresses dust resuspension, directly counteracting the absence of natural atmospheric dispersion."
        )

    if signal == "traffic":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Ward {ward_id} ({ward_name}) experiences severe street-canyon trapping of vehicular exhaust along {road_str}. "
            f"Sensor data confirms: {lead_evidence}. "
            f"Multi-story structures flanking arterial roads restrict lateral wind dilution, creating elevated NO2 and CO micro-corridors through {nh_str}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Stop-and-go heavy vehicles, commuter buses, and delivery fleets emit concentrated nitrogen dioxide and carbon monoxide during rush hours. "
            f"{station_str} registers acute exposure spikes directly threatening pedestrians and street vendors among the ward's {pop_str} residents. "
            f"Inhalation of unburned hydrocarbons and NO2 inflames upper airways and reduces blood oxygen capacity.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} targets the congestion bottleneck during {time_window}. "
            f"Enforcing anti-idling rules, deploying traffic wardens, and coordinating signal green-waves along {road_str} reduces localized tailpipe emissions before concentrations spill into adjacent residential blocks."
        )

    if signal == "dust":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Ward {ward_id} ({ward_name}) shows dry ground conditions with low relative humidity. "
            f"Mechanical shear stress from heavy vehicles along {road_str} is continuously lofting mineral particles into the surface boundary layer. "
            f"Field data confirms: {lead_evidence}. Turbulent wakes resuspend settled soil and construction fines across {nh_str}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Construction excavation, unpaved road shoulders, and aggregate handling produce coarse PM10 loadings. "
            f"{station_str} shows elevated coarse-to-fine particulate ratios affecting {pop_str} residents under {category} conditions (AQI {round(aqi)}). "
            f"Inhaled coarse dust causes acute eye irritation, pharyngitis, and aggravates COPD.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} is required during {time_window}. "
            f"Operating anti-smog guns, wet-sweeping mechanical units, and enforcing dust barrier netting at construction plots across {nh_str} cuts fugitive dust resuspension by up to 60%."
        )

    if signal == "waste_burning":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Thermal sensors and municipal surveillance identify active open refuse combustion within or upwind of Ward {ward_id} ({ward_name}) in {zone_desc}. "
            f"Field evidence: {lead_evidence}. "
            f"Buoyant combustion plumes carry toxic carbonaceous particulate matter across {nh_str}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"Open burning of municipal solid waste and plastic releases dense PM2.5, dioxins, and toxic hydrocarbons. "
            f"With {pop_str} residents exposed to {category} air quality (AQI {round(aqi)}), smoke plumes pose severe hazards to infants, elderly, and individuals near {road_str}.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} requires immediate tactical deployment during {time_window}. "
            f"Direct suppression by municipal flying squads and water tankers quenches smoldering waste at source, preventing wider smoke dispersion across the urban canopy."
        )

    if signal == "forecast_crossing":
        return (
            f"**Atmospheric Dispersion Dynamics**\n"
            f"Predictive modeling for Ward {ward_id} ({ward_name}) projects a categorical worsening of air quality over the next 6 to 12 hours. "
            f"Forecast analysis: {lead_evidence}. "
            f"Diurnal boundary layer compression and wind shifts across {zone_desc} compound pollutant loading through {nh_str}.\n\n"
            f"**Emission Source Attribution and Population Exposure**\n"
            f"As concentrations escalate into a higher health-risk bracket, the cumulative toxic burden on {pop_str} residents intensifies significantly. "
            f"{station_str} provides the verification baseline for tracking escalation along {road_str}.\n\n"
            f"**Operational Mitigation Justification**\n"
            f"{action_title} executed during the proactive window ({time_window}) flattens the projected concentration peak. "
            f"Pre-emptive dust wetting and vehicle traffic management curb source emissions before meteorological conditions deteriorate."
        )

    return (
        f"**Atmospheric Dispersion Dynamics**\n"
        f"Localized air quality monitoring for Ward {ward_id} ({ward_name}) in {zone_desc} identifies an active anomaly ({lead_evidence}). "
        f"Current micro-meteorological conditions limit natural dispersion across {nh_str}, maintaining localized pollutant concentration.\n\n"
        f"**Emission Source Attribution and Population Exposure**\n"
        f"Ambient AQI is {round(aqi)} ({category}), directly affecting {pop_str} residents. "
        f"{station_str} records elevated exposure risk. {baseline_rationale}\n\n"
        f"**Operational Mitigation Justification**\n"
        f"{action_title} is the designated BMC intervention for {time_window}. "
        f"Prompt field deployment across {road_str} prevents further air quality degradation."
    )


def _build_fallback_hi(
    ward_name, ward_id, population, aqi, category, signal, action_title,
    evidence, time_window, lead_evidence, nh_str, road_str, pop_str, station_str,
    zone_desc,
) -> str:
    cat_hi = {"Good": "अच्छा", "Satisfactory": "संतोषजनक", "Moderate": "मध्यम",
               "Poor": "खराब", "Very Poor": "बहुत खराब", "Severe": "गंभीर"}.get(category, category)

    if signal == "stagnation":
        return (
            f"**वायुमंडलीय प्रसार गतिशीलता**\n"
            f"वार्ड {ward_id} ({ward_name}) में सतह पर हवा की गति 1.5 मीटर/सेकंड से नीचे आ गई है। "
            f"{nh_str} के ऊपर समुद्री हवा का प्रवाह रुक गया है और एक उथली तापमान व्युत्क्रमण परत ज़मीनी उत्सर्जन को फँसा रही है। "
            f"क्षेत्र डेटा: {lead_evidence}।\n\n"
            f"**उत्सर्जन स्रोत और जनसंख्या एक्सपोज़र**\n"
            f"{road_str} पर भारी वाहन यातायात और सक्रिय निर्माण स्थलों से फँसा हुआ उत्सर्जन साँस लेने की ऊँचाई पर जमा हो रहा है। "
            f"वार्ड {ward_id} के {pop_str} निवासी AQI {round(aqi)} ({cat_hi}) वायु गुणवत्ता के संपर्क में हैं। "
            f"लंबे समय तक ठहरी हुई हवा में रहने से हृदय-फेफड़े की बीमारियाँ और अस्थमा तीव्र होते हैं।\n\n"
            f"**परिचालन शमन औचित्य**\n"
            f"{time_window} के दौरान {action_title} अनिवार्य है। "
            f"{road_str} पर उच्च-दबाव जल-छिड़काव और यांत्रिक झाड़ू लगाने से धूल का पुनः उड़ान रुकती है और प्राकृतिक वायुमंडलीय प्रसार की कमी की भरपाई होती है।"
        )

    if signal == "waste_burning":
        return (
            f"**वायुमंडलीय प्रसार गतिशीलता**\n"
            f"थर्मल सेंसर और BMC निगरानी ने वार्ड {ward_id} ({ward_name}) में या उसके ऊपर की दिशा से सक्रिय खुले कचरे के दहन की पुष्टि की है। "
            f"क्षेत्र साक्ष्य: {lead_evidence}। "
            f"दहन की ऊष्मा-उत्प्लावन प्लूम PM2.5, dioxins और विषाक्त हाइड्रोकार्बन को {nh_str} में फैला रहे हैं।\n\n"
            f"**उत्सर्जन स्रोत और जनसंख्या एक्सपोज़र**\n"
            f"नगर ठोस कचरे और प्लास्टिक के खुले दहन से सघन PM2.5 और विषाक्त धुआँ निकल रहा है। "
            f"वार्ड के {pop_str} निवासी AQI {round(aqi)} ({cat_hi}) के संपर्क में हैं। "
            f"{road_str} के पास के शिशु, वृद्ध और श्वसन रोगी विशेष रूप से प्रभावित हैं।\n\n"
            f"**परिचालन शमन औचित्य**\n"
            f"{time_window} में {action_title} की तत्काल तैनाती आवश्यक है। "
            f"BMC फ्लाइंग स्क्वाड और जल टैंकर द्वारा सीधे दहन स्थल पर दमन करने से धुएँ का व्यापक प्रसार शहरी छत्र में फैलने से रोका जाता है।"
        )

    if signal == "dust":
        return (
            f"**वायुमंडलीय प्रसार गतिशीलता**\n"
            f"वार्ड {ward_id} ({ward_name}) में शुष्क ज़मीनी परिस्थितियाँ और कम आर्द्रता के कारण {road_str} पर भारी वाहनों की यांत्रिक कर्षण-शक्ति खनिज कण उड़ा रही है। "
            f"क्षेत्र डेटा: {lead_evidence}। वाहनों के पीछे की वायु-भँवर {nh_str} में बसी धूल और निर्माण महीन कण फिर से उड़ा देती है।\n\n"
            f"**उत्सर्जन स्रोत और जनसंख्या एक्सपोज़र**\n"
            f"निर्माण खुदाई, कच्चे सड़क कंधे और समुच्चय सामग्री प्रबंधन मोटे PM10 भार उत्पन्न कर रहे हैं। "
            f"वार्ड {ward_id} के {pop_str} निवासी AQI {round(aqi)} ({cat_hi}) में हैं। "
            f"मोटी धूल साँस में जाने से आँख में जलन, ग्रसनीशोथ और COPD की स्थिति बिगड़ती है।\n\n"
            f"**परिचालन शमन औचित्य**\n"
            f"{time_window} में {action_title} आवश्यक है। "
            f"{nh_str} में एंटी-स्मॉग गन, वेट-स्वीपिंग यंत्र और निर्माण स्थलों पर अनिवार्य धूल-अवरोधक जाल से भगोड़ी धूल 60% तक कम होती है।"
        )

    if signal == "traffic":
        return (
            f"**वायुमंडलीय प्रसार गतिशीलता**\n"
            f"वार्ड {ward_id} ({ward_name}) में {road_str} के साथ-साथ सड़क-खाई में वाहन उत्सर्जन गंभीर रूप से फँसा हुआ है। "
            f"सेंसर डेटा: {lead_evidence}। "
            f"ऊँची इमारतें पार्श्व वायु-तनुकरण को रोकती हैं जिससे {nh_str} में NO2 और CO की उच्च सांद्रता बन जाती है।\n\n"
            f"**उत्सर्जन स्रोत और जनसंख्या एक्सपोज़र**\n"
            f"रश-ऑवर में भारी वाहन, बसें और डिलीवरी वाहन NO2 और CO का उत्सर्जन करते हैं। "
            f"वार्ड के {pop_str} निवासियों में पैदल यात्री और सड़क विक्रेता सबसे अधिक प्रभावित हैं (AQI {round(aqi)}, {cat_hi})।\n\n"
            f"**परिचालन शमन औचित्य**\n"
            f"{time_window} में {action_title} से भीड़भाड़ के केंद्र बिंदु को लक्षित किया जाता है। "
            f"{road_str} पर एंटी-आइडलिंग नियम, ट्रैफिक वार्डन और सिग्नल ग्रीन-वेव से टेलपाइप उत्सर्जन घटता है।"
        )

    if signal == "forecast_crossing":
        return (
            f"**वायुमंडलीय प्रसार गतिशीलता**\n"
            f"वार्ड {ward_id} ({ward_name}) के लिए पूर्वानुमान मॉडलिंग अगले 6 से 12 घंटों में वायु गुणवत्ता में श्रेणीगत गिरावट दर्शाती है। "
            f"पूर्वानुमान विश्लेषण: {lead_evidence}। "
            f"{zone_desc} में दैनिक सीमा-परत संपीड़न और हवा की दिशा बदलाव {nh_str} में प्रदूषक भार बढ़ाते हैं।\n\n"
            f"**उत्सर्जन स्रोत और जनसंख्या एक्सपोज़र**\n"
            f"जैसे-जैसे सांद्रता उच्च स्वास्थ्य-जोखिम श्रेणी में प्रवेश करती है, {pop_str} निवासियों पर संचित विषाक्त बोझ तेज़ी से बढ़ता है। "
            f"AQI {round(aqi)} ({cat_hi}) की निगरानी {road_str} पर वृद्धि ट्रैक करने के लिए जारी है।\n\n"
            f"**परिचालन शमन औचित्य**\n"
            f"{time_window} में {action_title} सक्रिय करने से अनुमानित सांद्रता शिखर कम होता है। "
            f"अग्रिम धूल-भिगोना और यातायात प्रबंधन मौसमी स्थिति बिगड़ने से पहले स्रोत उत्सर्जन को सीमित करता है।"
        )

    if signal == "inflow":
        return (
            f"**वायुमंडलीय प्रसार गतिशीलता**\n"
            f"वायुमंडलीय बैक-ट्रैजेक्टरी मॉडलिंग {zone_desc} से होकर वार्ड {ward_id} ({ward_name}) में प्रवेश करने वाले वायु कणों को ट्रैक करती है। "
            f"विशेष रूप से: {lead_evidence}। "
            f"तापीय स्तरीकरण और सीमा परत संपीड़न ऊर्ध्वाधर वेंटिलेशन को रोकते हैं।\n\n"
            f"**उत्सर्जन स्रोत और जनसंख्या एक्सपोज़र**\n"
            f"ऊपर की दिशा से आने वाले क्षेत्र से PM2.5 की निगरानी हो रही है। "
            f"वार्ड {ward_id} के {pop_str} निवासी AQI {round(aqi)} ({cat_hi}) के संपर्क में हैं। "
            f"दहन एरोसोल में sub-micron PM2.5 और कार्बन कण {nh_str} में श्वसन और आँख की जलन पैदा कर रहे हैं।\n\n"
            f"**परिचालन शमन औचित्य**\n"
            f"{time_window} में {action_title} के लिए अंतर-एजेंसी सक्रियता की आवश्यकता है। "
            f"Aaple Sarkar और वार्ड चैनलों के माध्यम से सार्वजनिक स्वास्थ्य सलाह जारी करने से कमज़ोर समूह घर के अंदर सुरक्षित रह सकते हैं।"
        )

    return (
        f"**वायुमंडलीय प्रसार गतिशीलता**\n"
        f"वार्ड {ward_id} ({ward_name}) में स्थानीय वायु गुणवत्ता निगरानी एक सक्रिय विसंगति की पहचान करती है ({lead_evidence}). "
        f"वर्तमान सूक्ष्म-मौसम विज्ञान {nh_str} में प्राकृतिक प्रसार सीमित कर रहा है।\n\n"
        f"**उत्सर्जन स्रोत और जनसंख्या एक्सपोज़र**\n"
        f"परिवेश AQI {round(aqi)} ({cat_hi}) है, जो {pop_str} निवासियों को प्रभावित कर रहा है।\n\n"
        f"**परिचालन शमन औचित्य**\n"
        f"{time_window} के लिए {action_title} BMC का निर्दिष्ट हस्तक्षेप है। "
        f"{road_str} में त्वरित तैनाती से वायु गुणवत्ता में और गिरावट रोकी जा सकती है।"
    )


def _build_fallback_mr(
    ward_name, ward_id, population, aqi, category, signal, action_title,
    evidence, time_window, lead_evidence, nh_str, road_str, pop_str, station_str,
    zone_desc,
) -> str:
    cat_mr = {"Good": "चांगले", "Satisfactory": "समाधानकारक", "Moderate": "मध्यम",
               "Poor": "वाईट", "Very Poor": "अतिशय वाईट", "Severe": "तीव्र"}.get(category, category)

    if signal == "stagnation":
        return (
            f"**वायुमंडलीय प्रसार गतिशास्त्र**\n"
            f"प्रभाग {ward_id} ({ward_name}) मध्ये पृष्ठभागावरील वाऱ्याचा वेग 1.5 मीटर/सेकंदपेक्षा खाली आला आहे. "
            f"{nh_str} वरील सागरी वाऱ्याचा प्रवाह थांबला आहे आणि एक उथळ तापमान व्युत्क्रमण थर जमिनीवरील उत्सर्जन अडवत आहे. "
            f"क्षेत्र डेटा: {lead_evidence}.\n\n"
            f"**उत्सर्जन स्रोत आणि लोकसंख्या एक्सपोजर**\n"
            f"{road_str} वरील जड वाहतूक आणि सक्रिय बांधकाम स्थळांमधून अडकलेले उत्सर्जन श्वासोच्छ्वासाच्या उंचीवर जमा होत आहे. "
            f"प्रभाग {ward_id} च्या {pop_str} रहिवाशांना AQI {round(aqi)} ({cat_mr}) हवेची गुणवत्ता सहन करावी लागत आहे. "
            f"स्थिर हवेत दीर्घकाळ राहिल्याने हृदय-फुप्फुसाचे विकार आणि दमा तीव्र होतात.\n\n"
            f"**परिचालन उपशमन औचित्य**\n"
            f"{time_window} मध्ये {action_title} अनिवार्य आहे. "
            f"{road_str} वर उच्च-दाब जल-फवारणी आणि यांत्रिक झाडलोट केल्याने धुळीचे पुनरुत्थान थांबते आणि नैसर्गिक वायुमंडलीय प्रसाराच्या अभावाची भरपाई होते."
        )

    if signal == "waste_burning":
        return (
            f"**वायुमंडलीय प्रसार गतिशास्त्र**\n"
            f"थर्मल सेन्सर आणि BMC पाळत ठेवण्याने प्रभाग {ward_id} ({ward_name}) मध्ये किंवा त्याच्या वाऱ्याच्या दिशेने सक्रिय उघड्यावर कचरा जाळण्याची पुष्टी केली आहे. "
            f"क्षेत्र साक्ष्य: {lead_evidence}. "
            f"ज्वलनाची उष्णता-उत्प्लावन प्लूम PM2.5, dioxins आणि विषारी हायड्रोकार्बन {nh_str} मध्ये पसरवत आहेत.\n\n"
            f"**उत्सर्जन स्रोत आणि लोकसंख्या एक्सपोजर**\n"
            f"नगर घनकचरा आणि प्लास्टिकच्या उघड्या ज्वलनातून दाट PM2.5 आणि विषारी धूर निघत आहे. "
            f"प्रभागाच्या {pop_str} रहिवाशांना AQI {round(aqi)} ({cat_mr}) प्रदर्शनास सामोरे जावे लागत आहे. "
            f"{road_str} जवळील अर्भक, वृद्ध आणि श्वसन रोगी विशेषत: धोक्यात आहेत.\n\n"
            f"**परिचालन उपशमन औचित्य**\n"
            f"{time_window} मध्ये {action_title} ची तात्काळ तैनाती आवश्यक आहे. "
            f"BMC फ्लाइंग स्क्वॉड आणि जल टँकरद्वारे ज्वलन स्थळावर थेट दडपशाही केल्याने धुराचा शहरी छताखाली व्यापक प्रसार रोखला जातो."
        )

    if signal == "dust":
        return (
            f"**वायुमंडलीय प्रसार गतिशास्त्र**\n"
            f"प्रभाग {ward_id} ({ward_name}) मध्ये कोरड्या जमिनीची परिस्थिती आणि कमी आर्द्रतेमुळे {road_str} वरील जड वाहनांची यांत्रिक कर्षण-शक्ती खनिज कण उडवत आहे. "
            f"क्षेत्र डेटा: {lead_evidence}. वाहनांच्या मागे वायु-भोवरे {nh_str} मधील स्थिर माती आणि बांधकामाचे बारीक कण पुन्हा उडवत आहेत.\n\n"
            f"**उत्सर्जन स्रोत आणि लोकसंख्या एक्सपोजर**\n"
            f"बांधकाम उत्खनन, कच्च्या रस्त्याचे खांदे आणि समुच्चय सामग्री हाताळणी मोठ्या प्रमाणात PM10 भार निर्माण करत आहे. "
            f"प्रभाग {ward_id} च्या {pop_str} रहिवाशांना AQI {round(aqi)} ({cat_mr}) परिस्थितीत धोका आहे. "
            f"श्वासावाटे जड धूळ आल्याने डोळ्यांची जळजळ, घशाचा दाह आणि COPD बिघडतो.\n\n"
            f"**परिचालन उपशमन औचित्य**\n"
            f"{time_window} मध्ये {action_title} आवश्यक आहे. "
            f"{nh_str} मधील बांधकाम स्थळांवर अँटी-स्मॉग गन, ओला-झाडू यंत्र आणि अनिवार्य धूळ-अवरोधक जाळी वापरल्याने भटक्या धुळीत 60% पर्यंत घट होते."
        )

    if signal == "traffic":
        return (
            f"**वायुमंडलीय प्रसार गतिशास्त्र**\n"
            f"प्रभाग {ward_id} ({ward_name}) मध्ये {road_str} च्या बाजूने रस्त्याच्या घळईत वाहन उत्सर्जन गंभीरपणे अडकले आहे. "
            f"सेन्सर डेटा: {lead_evidence}. "
            f"उंच इमारती पार्श्वीय वायु-सौम्यीकरण रोखतात ज्यामुळे {nh_str} मध्ये NO2 आणि CO ची उच्च सांद्रता तयार होते.\n\n"
            f"**उत्सर्जन स्रोत आणि लोकसंख्या एक्सपोजर**\n"
            f"गर्दीच्या वेळी जड वाहने, बस आणि डिलिव्हरी वाहने NO2 आणि CO उत्सर्जन करतात. "
            f"प्रभागाच्या {pop_str} रहिवाशांपैकी पादचारी आणि रस्त्यावरील विक्रेते सर्वाधिक धोक्यात आहेत (AQI {round(aqi)}, {cat_mr}).\n\n"
            f"**परिचालन उपशमन औचित्य**\n"
            f"{time_window} मध्ये {action_title} गर्दीच्या अडथळ्याला लक्ष्य करते. "
            f"{road_str} वर अँटी-आयडलिंग नियम, वाहतूक वार्डन आणि सिग्नल ग्रीन-वेव्हमुळे उत्सर्जन कमी होते."
        )

    if signal == "forecast_crossing":
        return (
            f"**वायुमंडलीय प्रसार गतिशास्त्र**\n"
            f"प्रभाग {ward_id} ({ward_name}) साठी अंदाज मॉडेलिंग पुढील 6 ते 12 तासांत हवेच्या गुणवत्तेत श्रेणीगत बिघाड दर्शवत आहे. "
            f"अंदाज विश्लेषण: {lead_evidence}. "
            f"{zone_desc} मध्ये दैनिक सीमा-थर संकुचन आणि वाऱ्याची दिशा बदल {nh_str} मध्ये प्रदूषक भार वाढवतात.\n\n"
            f"**उत्सर्जन स्रोत आणि लोकसंख्या एक्सपोजर**\n"
            f"सांद्रता उच्च आरोग्य-जोखीम श्रेणीत प्रवेश करताना {pop_str} रहिवाशांवर एकत्रित विषारी बोजा झपाट्याने वाढतो. "
            f"AQI {round(aqi)} ({cat_mr}) निगरानी {road_str} वरील वाढ ट्रॅक करण्यासाठी सुरू आहे.\n\n"
            f"**परिचालन उपशमन औचित्य**\n"
            f"{time_window} मध्ये {action_title} सक्रिय केल्याने अपेक्षित सांद्रता शिखर कमी होते. "
            f"आगाऊ धुळीभिजवणे आणि वाहतूक व्यवस्थापन हवामान बिघडण्यापूर्वी स्रोत उत्सर्जन मर्यादित करते."
        )

    if signal == "inflow":
        return (
            f"**वायुमंडलीय प्रसार गतिशास्त्र**\n"
            f"वायुमंडलीय बॅक-ट्रॅजेक्टरी मॉडेलिंग {zone_desc} मधून प्रभाग {ward_id} ({ward_name}) मध्ये प्रवेश करणाऱ्या हवेचे कण ट्रॅक करते. "
            f"विशेषत:: {lead_evidence}. "
            f"थर्मल स्तरीकरण आणि सीमा थर संकुचन ऊर्ध्वाधर वेंटिलेशन रोखतात.\n\n"
            f"**उत्सर्जन स्रोत आणि लोकसंख्या एक्सपोजर**\n"
            f"वाऱ्याच्या वरील दिशेकडून येणाऱ्या PM2.5 ची निगरानी होत आहे. "
            f"प्रभाग {ward_id} च्या {pop_str} रहिवाशांना AQI {round(aqi)} ({cat_mr}) चा सामना करावा लागत आहे. "
            f"ज्वलन एरोसोलमध्ये sub-micron PM2.5 आणि कार्बन कण {nh_str} मध्ये श्वसन आणि डोळ्यांची जळजळ निर्माण करत आहेत.\n\n"
            f"**परिचालन उपशमन औचित्य**\n"
            f"{time_window} मध्ये {action_title} साठी आंतर-एजन्सी सक्रियता आवश्यक आहे. "
            f"Aaple Sarkar आणि प्रभाग चॅनेलद्वारे सार्वजनिक आरोग्य सूचना जारी केल्याने असुरक्षित गट घरात सुरक्षित राहू शकतात."
        )

    return (
        f"**वायुमंडलीय प्रसार गतिशास्त्र**\n"
        f"प्रभाग {ward_id} ({ward_name}) मधील स्थानिक हवा गुणवत्ता निरीक्षण एक सक्रिय विसंगती ओळखते ({lead_evidence}). "
        f"सध्याची सूक्ष्म-हवामानशास्त्रीय परिस्थिती {nh_str} मध्ये नैसर्गिक प्रसार मर्यादित करत आहे.\n\n"
        f"**उत्सर्जन स्रोत आणि लोकसंख्या एक्सपोजर**\n"
        f"परिवेश AQI {round(aqi)} ({cat_mr}) आहे, ज्यामुळे {pop_str} रहिवाशांवर परिणाम होत आहे.\n\n"
        f"**परिचालन उपशमन औचित्य**\n"
        f"{time_window} साठी {action_title} हे BMC चे निर्दिष्ट हस्तक्षेप आहे. "
        f"{road_str} मध्ये त्वरित तैनातीने हवेच्या गुणवत्तेत आणखी घट टाळता येते."
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
    lang: str = "en",
) -> str:
    """Generate thorough, scientifically grounded 'Why this action' reasoning using Gemini,
    with thread-safe caching and robust, localized fallback templates.
    Supports lang='en', 'hi', 'mr'."""
    safe_lang = lang if lang in SYSTEM_PROMPTS else "en"
    key = _cache_key(ward_id, signal, aqi, evidence, safe_lang)
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    fallback = _build_fallback_reasoning(
        ward_name=ward_name, ward_id=ward_id, population=population, aqi=aqi,
        category=category, signal=signal, action_title=action_title,
        evidence=evidence, time_window=time_window, baseline_rationale=baseline_rationale,
        station_name=station_name, station_distance_km=station_distance_km, lang=safe_lang,
    )

    global _quota_exhausted_until
    import os
    if os.getenv("PYTEST_CURRENT_TEST") or not settings.GEMINI_API_KEY or time.time() < _quota_exhausted_until:
        with _cache_lock:
            _cache[key] = fallback
        return fallback

    system_prompt = SYSTEM_PROMPTS[safe_lang]
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
        f"Specific Neighborhoods: {', '.join(WARD_ZONES.get(ward_id, ('', ['ward center'], []))[1][:3])}\n"
        f"Key Roads: {', '.join(WARD_ZONES.get(ward_id, ('', [], ['primary roads']))[2][:2])}\n"
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
                        system_instruction=system_prompt,
                        temperature=0.35,
                    ),
                )
                if response.text and response.text.strip():
                    text = response.text.strip()
                    text = text.replace("--", ": ").replace("\u2014", ": ").replace("\u2013", "-").replace("\u2015", ": ")
                    break
            except Exception as e:
                err_str = str(e)
                if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
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
