import React, { useState, useEffect } from 'react';
import './TopBar.css';
import { useLang, useT } from '../i18n/LangContext';
import { LANGUAGES } from '../i18n/translations';

export default function TopBar({ lastUpdated, view = 'map', onNavigate }) {
  const [now, setNow] = useState(new Date());
  const { lang, setLang } = useLang();
  const t = useT();

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const fmtUpdated = iso => {
    if (!iso) return null;
    return new Date(iso).toLocaleTimeString('en-IN', {
      hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata',
    });
  };

  const dateStr = now.toLocaleDateString('en-IN', {
    weekday: 'short', month: 'short', day: 'numeric', timeZone: 'Asia/Kolkata',
  });
  const timeStr = now.toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata',
  });
  const updStr = fmtUpdated(lastUpdated);

  return (
    <header className="topbar" role="banner">
      {/* ── Brand ── */}
      <div className="topbar__brand">
        <span className="topbar__name">{t('appName')}</span>
        <span className="topbar__name-hi">{t('appNameDevanagari')}</span>
      </div>

      {/* ── City pill + nav ── */}
      <div className="topbar__centre">
        <span className="topbar__city">{t('city')}</span>
        {onNavigate && (
          <nav className="topbar__nav" aria-label="Pages">
            <button type="button"
              className={`topbar__tab${view === 'map' ? ' topbar__tab--active' : ''}`}
              aria-current={view === 'map' ? 'page' : undefined}
              onClick={() => onNavigate('map')}>
              {t('navMap')}
            </button>
            <button type="button"
              className={`topbar__tab${view === 'actions' ? ' topbar__tab--active' : ''}`}
              aria-current={view === 'actions' ? 'page' : undefined}
              onClick={() => onNavigate('actions')}>
              {t('navWardActions')}
            </button>
          </nav>
        )}
      </div>

      {/* ── Right: date/time + lang toggle side by side ── */}
      <div className="topbar__right">
        <div className="topbar__timebox">
          <span className="topbar__datetime">{dateStr}, {timeStr}</span>
          {updStr ? (
            <span className="topbar__updated">
              {t('live')} &middot; {t('updatedAt')} {updStr}
            </span>
          ) : (
            <span className="topbar__updated">{t('noLiveData')}</span>
          )}
        </div>

        <div className="topbar__divider" aria-hidden="true" />

        {/* Language toggle */}
        <div className="topbar__lang" role="group" aria-label="Language">
          {LANGUAGES.map(({ code, label, full }) => (
            <button
              key={code}
              type="button"
              title={full}
              aria-pressed={lang === code}
              className={`topbar__lang-btn${lang === code ? ' topbar__lang-btn--on' : ''}`}
              onClick={() => setLang(code)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}