import React, { useState, useEffect } from 'react';
import './TopBar.css';

export default function TopBar({ lastUpdated }) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const fmtTime = d =>
    d.toLocaleTimeString('en-IN', {
      weekday:  'short',
      hour:     '2-digit',
      minute:   '2-digit',
      hour12:   true,
      timeZone: 'Asia/Kolkata',
    });

  const fmtUpdated = iso => {
    if (!iso) return null;
    const t = new Date(iso).toLocaleTimeString('en-IN', {
      hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata',
    });
    return t;
  };

  // e.g. "Wed, Sep 30, 02:10 PM"
  const dateStr = now.toLocaleDateString('en-IN', {
    weekday: 'short', month: 'short', day: 'numeric',
    timeZone: 'Asia/Kolkata',
  });
  const timeStr = now.toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata',
  });

  const updStr = fmtUpdated(lastUpdated);

  return (
    <header className="topbar" role="banner">
      {/* ── Brand ── */}
      <div className="topbar__brand">
        <span className="topbar__name">Shwas</span>
        <span className="topbar__name-hi">श्वास</span>
      </div>

      {/* ── City pill ── */}
      <div className="topbar__centre">
        <span className="topbar__city">Mumbai</span>
      </div>

      {/* ── Date / time / status ── */}
      <div className="topbar__right">
        <span className="topbar__datetime">{dateStr}, {timeStr}</span>
        {updStr ? (
          <span className="topbar__updated">
            Updated {updStr} &middot; refreshes every 5 min
          </span>
        ) : (
          <span className="topbar__updated">
            No live data &middot; refreshes every 5 min
          </span>
        )}
      </div>
    </header>
  );
}
