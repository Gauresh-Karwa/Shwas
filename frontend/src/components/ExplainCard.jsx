/**
 * ExplainCard.jsx
 *
 * Shows the backend's one-sentence explanation in a friendlier way:
 *  - a colour scale with a pin on today's AQI
 *  - the sentence in larger type with the important words picked out
 *    (AQI number, category, pollutants, wind direction)
 *  - short plain-language notes for any pollutant the sentence mentions
 *  - a "what this means for you" line for the current category
 *
 * The sentence itself is the backend's. This component only restyles it
 * and expands abbreviations (WNW -> west-north-west).
 *
 * Props:
 *   text   attribution.explanation
 *   aqi    AQI of the selected place
 */
import React from 'react';
import { CATS, getCategory } from '../utils/aqi';
import './ExplainCard.css';

const COMPASS = {
  NNE: 'north-north-east', ENE: 'east-north-east', ESE: 'east-south-east', SSE: 'south-south-east',
  SSW: 'south-south-west', WSW: 'west-south-west', WNW: 'west-north-west', NNW: 'north-north-west',
  NE: 'north-east', SE: 'south-east', SW: 'south-west', NW: 'north-west',
};

// Short, plain-language meanings (static explanatory text, not data)
const POLLUTANT_INFO = {
  'PM2.5': 'tiny dust and smoke particles that can reach deep into your lungs',
  'PM10': 'coarser dust, such as road and construction dust',
  'NO2': 'a gas that mostly comes from vehicle exhaust',
  'SO2': 'a gas released by burning coal and fuel in industry',
};

const ADVICE = {
  'Good': 'A great time to be outside.',
  'Satisfactory': 'Fine for most people. If you are unusually sensitive, go easy on long outdoor workouts.',
  'Moderate': 'Children, older adults and people with asthma or heart problems should cut down on long time outdoors.',
  'Poor': 'Many people may feel discomfort outside. Keep outdoor exercise short.',
  'Very Poor': 'Try to stay indoors and skip outdoor exercise.',
  'Severe': 'Stay indoors with windows closed and avoid outdoor exertion.',
};

// Words and numbers worth picking out (case-sensitive on purpose)
const TOKEN = new RegExp(
  '(PM2\\.5|PM10|NO[2\u2082]|SO[2\u2082]' +
  '|\\b(?:NNE|ENE|ESE|SSE|SSW|WSW|WNW|NNW|NE|SE|SW|NW)\\b' +
  '|\\b\\d+(?:\\.\\d+)?\\b' +
  '|\\b(?:[Vv]ery [Pp]oor|[Ss]evere|[Ss]atisfactory|[Mm]oderate|[Gg]ood|[Pp]oor)\\b)',
);

const normPollutant = s => s.replace('\u2082', '2');

// Dark text on pale colours (yellow, lime), white text on dark ones
function inkOn(hex) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.55 ? '#17241E' : '#FFFFFF';
}

// When the AI is unavailable the backend sends a stiff template sentence.
// Turn it into something a person would say.
function friendlier(text) {
  const m = text?.match(/^Air quality is (.+?) \(AQI \d+\), primarily driven by (.+?)\.?$/i);
  if (m) return `Air is ${m[1].toLowerCase()} right now, mostly because of ${m[2]}.`;
  return text ?? '';
}

function Gauge({ aqi, cat }) {
  const pct = Math.min(Math.max(aqi / 500, 0), 1) * 100;
  return (
    <div className="xc-gauge" aria-hidden="true">
      <div className="xc-gauge__bar">
        {CATS.map(c => (
          <span key={c.label} style={{ flex: c.max - c.min + 1, background: c.color }} />
        ))}
      </div>
      <span className="xc-gauge__pin" style={{ left: `${pct}%`, borderColor: cat.color }} />
      <div className="xc-gauge__ends"><span>Clean</span><span>Hazardous</span></div>
    </div>
  );
}

export default function ExplainCard({ text, aqi }) {
  const cat = getCategory(aqi);
  const sentence = friendlier(text);
  const mentioned = new Set();

  const parts = sentence.split(TOKEN).map((part, i) => {
    if (i % 2 === 0) return part; // plain text between matches

    if (/^(PM|NO|SO)/.test(part)) {
      const key = normPollutant(part);
      mentioned.add(key);
      return <span key={i} className="xc-pill">{part}</span>;
    }
    if (COMPASS[part]) return <span key={i} className="xc-wind">{COMPASS[part]}</span>;
    if (/^\d/.test(part)) {
      return Math.round(Number(part)) === Math.round(aqi)
        ? <span key={i} className="xc-num" style={{ background: cat.color, color: inkOn(cat.color) }}>{part}</span>
        : part;
    }
    return part.toLowerCase() === cat.label.toLowerCase()
      ? <strong key={i} className="xc-cat" style={{ background: `linear-gradient(transparent 58%, ${cat.color}77 58%)` }}>{part}</strong>
      : part;
  });

  const glossary = [...mentioned].filter(k => POLLUTANT_INFO[k]);

  return (
    <section
      className="xc"
      aria-label="Plain-English explanation"
      style={{ background: `linear-gradient(135deg, ${cat.color}1f, #ffffff 62%)`, borderColor: `${cat.color}55` }}
    >
      <div className="xc__top">
        <span className="xc__label">In plain words</span>
        <span className="xc__badge" style={{ background: cat.color, color: inkOn(cat.color) }}>{cat.label}, AQI {Math.round(aqi)}</span>
      </div>

      <Gauge aqi={aqi} cat={cat} />

      <p className="xc__text">{parts}</p>

      {glossary.length > 0 && (
        <ul className="xc__gloss">
          {glossary.map(k => (
            <li key={k}><b>{k}</b> is {POLLUTANT_INFO[k]}.</li>
          ))}
        </ul>
      )}

      <div className="xc__tip" style={{ borderLeftColor: cat.color }}>
        <b>What this means for you</b>
        <span>{ADVICE[cat.label] ?? ''}</span>
      </div>
    </section>
  );
}