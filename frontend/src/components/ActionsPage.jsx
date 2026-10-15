/**
 * ActionsPage.jsx: Executive Ward Action Centre.
 *
 * Left: all wards ranked by exposure priority.
 * Right: the selected ward's LIVE recommended actions with operational intelligence
 * (Department, SOP, Compliance Checkpoint), 12-hour forecast trajectory,
 * and deep LLM-generated scientific reasoning ('Why this action').
 *
 * Standard Operational Mitigations (SOP) are accessible via a dedicated modal
 * rather than cluttering each ward view.
 *
 * Zero emojis, clean typography, reliable ASCII text.
 */
import React, { useState, useMemo, useEffect } from 'react';
import './ActionsPage.css';

import { getCategory } from '../utils/aqi';
import {
    CONFIDENCE_HINT, signalLabel, severityInfo, formatPopulation, formatKm, trendInfo,
    actionCards, advisoryCards, baselineCards, wardTopSeverity, filterWards,
    signalsInUse, summarise, defaultWardId, rankOf,
} from '../utils/actions';
import { useWardActions } from '../hooks/useWardActions';

function Stat({ value, label, accent }) {
    return (
        <div className={`act-stat${accent ? ' act-stat--accent' : ''}`}>
            <div className="act-stat__value">{value ?? '-'}</div>
            <div className="act-stat__label">{label}</div>
        </div>
    );
}

function SeverityPill({ severity, baseline }) {
    if (baseline) return <span className="act-sev act-sev--baseline">Operational</span>;
    return <span className={`act-sev act-sev--${severity}`}>{severityInfo(severity).label}</span>;
}

function AqiBadge({ aqi }) {
    const rounded = aqi == null ? null : Math.round(aqi);
    return <span className="aqi-badge" style={{ background: getCategory(rounded).color }}>{rounded ?? '-'}</span>;
}

function WardRow({ ward, rank, selected, onSelect }) {
    const live = actionCards(ward).length;
    const top = wardTopSeverity(ward);
    const liveText = live > 0 ? `${live} live alert${live > 1 ? 's' : ''}` : 'Baseline status';
    return (
        <button type="button" className={`act-row${selected ? ' act-row--selected' : ''}`}
            aria-current={selected ? 'true' : undefined} onClick={() => onSelect(ward.ward_id)}>
            <span className={`act-row__rank${rank ? '' : ' act-row__rank--none'}`}>{rank ?? '-'}</span>
            <span className="act-row__main">
                <span className="act-row__name">{ward.ward_name}</span>
                <span className="act-row__sub">Ward {ward.ward_id} | {formatPopulation(ward.population)} residents | {liveText}</span>
            </span>
            <span className="act-row__right">
                {top && <span className={`act-dot act-dot--${top}`} title={severityInfo(top).label} />}
                <AqiBadge aqi={ward.current_aqi} />
            </span>
        </button>
    );
}

function ListSkeleton() {
    return (
        <div className="act-list__rows" aria-hidden="true">
            {Array.from({ length: 8 }).map((_, i) => (
                <div className="act-row act-row--skeleton" key={i}>
                    <span className="skeleton" style={{ width: 22, height: 22, borderRadius: 99 }} />
                    <span className="act-row__main">
                        <span className="skeleton" style={{ width: '60%', height: 13, marginBottom: 6 }} />
                        <span className="skeleton" style={{ width: '85%', height: 11 }} />
                    </span>
                    <span className="skeleton" style={{ width: 40, height: 24, borderRadius: 99 }} />
                </div>
            ))}
        </div>
    );
}

function ForecastSparkline({ fc }) {
    if (!fc) return null;
    const t = trendInfo(fc.trend);
    const cat = getCategory(Math.round(fc.predicted_aqi));
    const barPct = Math.min(100, Math.round((fc.predicted_aqi / 500) * 100));
    return (
        <div className="act-fc">
            <div className="act-fc__header">
                <span className="section-label">12-Hour Forecast</span>
                <span className="act-fc__trend-tag" style={{ color: cat.color }}>
                    {t.text.toUpperCase()}
                </span>
            </div>
            <div className="act-fc__body">
                <div className="act-fc__num" style={{ color: cat.color }}>
                    {Math.round(fc.predicted_aqi)}
                </div>
                <div className="act-fc__bar-col">
                    <div className="act-fc__bar-track">
                        <div className="act-fc__bar-fill" style={{ width: `${barPct}%`, background: cat.color }} />
                    </div>
                    <span className="act-fc__bar-label">{fc.predicted_category} in {fc.hours_ahead}h</span>
                </div>
            </div>
            <p className="act-fc__note">Model forecast without intervention; not a guaranteed outcome.</p>
        </div>
    );
}

function OpsBlock({ department, sop, compliance_checkpoint }) {
    const rows = [
        { label: 'Target Department', value: department },
        { label: 'Standard SOP', value: sop },
        { label: 'Compliance Checkpoint', value: compliance_checkpoint },
    ].filter(r => r.value && r.value.trim());
    if (!rows.length) return null;
    return (
        <div className="act-ops">
            {rows.map((r, i) => (
                <div key={i} className={`act-ops__row${i === rows.length - 1 ? ' act-ops__row--last' : ''}`}>
                    <div className="act-ops__label">{r.label}</div>
                    <div className="act-ops__value">{r.value}</div>
                </div>
            ))}
        </div>
    );
}

function FormattedRationale({ text }) {
    if (!text) return null;
    const paragraphs = text.split('\n\n');
    return (
        <div className="act-card__why-text">
            {paragraphs.map((para, i) => {
                const trimmed = para.trim();
                if (!trimmed) return null;
                const match = trimmed.match(/^\*\*([^*]+)\*\*\s*(.*)$/s);
                if (match) {
                    return (
                        <div key={i} className="act-why-section">
                            <strong className="act-why-heading">{match[1]}</strong>
                            <p className="act-why-body">{match[2]}</p>
                        </div>
                    );
                }
                return <p key={i} className="act-why-body">{trimmed}</p>;
            })}
        </div>
    );
}

function ActionCard({ card }) {
    const [opsOpen, setOpsOpen] = useState(false);
    const hasOps = card.department || card.sop || card.compliance_checkpoint;

    return (
        <article className={`act-card act-card--${card.baseline ? 'baseline' : card.advisory ? 'advisory' : card.severity}`}>
            <div className="act-card__top">
                <SeverityPill severity={card.severity} baseline={card.baseline} />
                {!card.baseline && <span className="act-chip">{signalLabel(card.signal)}</span>}
                {card.estimated && <span className="act-chip" title="Nearest station > 6 km away.">Estimated</span>}
                <span className="act-card__conf" title={CONFIDENCE_HINT[card.confidence] ?? ''}>
                    Confidence: {card.confidence}
                </span>
            </div>

            <h3 className="act-card__title">{card.action_title}</h3>
            <p className="act-card__when"><b>When:</b> {card.time_window}</p>

            <div className="act-card__block">
                <div className="section-label">Evidence</div>
                <ul className="act-card__evidence">
                    {card.evidence.map((line, i) => <li key={i}>{line}</li>)}
                </ul>
            </div>

            {hasOps && (
                <div className="act-ops-wrap">
                    <button type="button" className="act-ops-toggle"
                        aria-expanded={opsOpen} onClick={() => setOpsOpen(o => !o)}>
                        <span className="act-ops-toggle__icon">{opsOpen ? '[-] ' : '[+] '}</span>
                        Operational Guidance
                    </button>
                    {opsOpen && (
                        <OpsBlock
                            department={card.department}
                            sop={card.sop}
                            compliance_checkpoint={card.compliance_checkpoint}
                        />
                    )}
                </div>
            )}

            {!card.baseline && card.forecast_without_action && (
                <ForecastSparkline fc={card.forecast_without_action} />
            )}

            {!card.baseline && card.rationale && (
                <details className="act-card__why" open>
                    <summary>Why this action (Operational Rationale)</summary>
                    <FormattedRationale text={card.rationale} />
                    {card.source_verified && card.source_reference &&
                        <p className="act-card__source">Source: {card.source_reference}</p>}
                </details>
            )}
        </article>
    );
}

function StandardMitigationsModal({ isOpen, onClose, baselineCards }) {
    useEffect(() => {
        function onKeyDown(e) {
            if (e.key === 'Escape') onClose();
        }
        if (isOpen) {
            window.addEventListener('keydown', onKeyDown);
            document.body.style.overflow = 'hidden';
        }
        return () => {
            window.removeEventListener('keydown', onKeyDown);
            document.body.style.overflow = '';
        };
    }, [isOpen, onClose]);

    if (!isOpen) return null;

    return (
        <div className="act-modal-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="modal-title">
            <div className="act-modal" onClick={e => e.stopPropagation()}>
                <div className="act-modal__header">
                    <div>
                        <div className="section-label">BMC / MCGM Standing Orders</div>
                        <h2 id="modal-title" className="act-modal__title">Standard Operational Mitigations</h2>
                        <p className="act-modal__sub">
                            These protocols are active across all 24 wards of Mumbai regardless of live detection spikes, based on the municipal risk profile.
                        </p>
                    </div>
                    <button type="button" className="act-modal__close" onClick={onClose} aria-label="Close modal">
                        Close
                    </button>
                </div>
                <div className="act-modal__body">
                    {baselineCards.map(c => (
                        <div key={c.card_id} className="act-modal-card">
                            <div className="act-modal-card__top">
                                <span className="act-sev act-sev--baseline">Standing Order</span>
                                <span className="act-modal-card__when">Schedule: {c.time_window}</span>
                            </div>
                            <h3 className="act-modal-card__title">{c.action_title}</h3>
                            <p className="act-modal-card__rationale">{c.rationale}</p>
                            <OpsBlock
                                department={c.department}
                                sop={c.sop}
                                compliance_checkpoint={c.compliance_checkpoint}
                            />
                        </div>
                    ))}
                </div>
                <div className="act-modal__footer">
                    <span className="act-modal__note">MCGM Environmental Management Order | Standing Protocols</span>
                    <button type="button" className="act-btn act-btn--primary" onClick={onClose}>
                        Done
                    </button>
                </div>
            </div>
        </div>
    );
}

function DetailSkeleton() {
    return (
        <div aria-hidden="true">
            <span className="skeleton" style={{ width: 120, height: 11, marginBottom: 12 }} />
            <span className="skeleton" style={{ width: 240, height: 28, marginBottom: 10 }} />
            <span className="skeleton" style={{ width: '55%', height: 13, marginBottom: 24 }} />
            <span className="skeleton" style={{ width: '100%', height: 180, borderRadius: 12 }} />
        </div>
    );
}

function WardDetail({ ward, rank, onOpenModal }) {
    const live = actionCards(ward);
    const adv = advisoryCards(ward).filter(c => !c.baseline);
    const cat = getCategory(ward.current_aqi == null ? null : Math.round(ward.current_aqi));

    const stationText = ward.nearest_station
        ? `Station: ${ward.nearest_station} (${formatKm(ward.distance_to_station_km)} away)`
        : 'No monitoring station nearby';

    return (
        <div className="fade-up" key={ward.ward_id}>
            <header className="act-detail__head">
                <div className="act-detail__who">
                    <div className="section-label">
                        Ward {ward.ward_id}{rank ? ` | Exposure Rank #${rank}` : ''}
                    </div>
                    <h2 className="act-detail__name">{ward.ward_name}</h2>
                    <div className="act-detail__meta">
                        <span className="act-detail__meta-item">
                            {formatPopulation(ward.population)} residents
                        </span>
                        <span className="act-detail__meta-sep"> | </span>
                        <span className="act-detail__meta-item">
                            {stationText}
                        </span>
                        {ward.is_estimated && (
                            <span className="act-chip act-chip--estimated" style={{ marginLeft: 8 }}
                                title="Nearest station is more than 6 km away">Estimated</span>
                        )}
                    </div>
                </div>
                <div className="act-detail__aqi">
                    <div className="act-detail__aqi-num" style={{ color: cat.color }}>
                        {ward.current_aqi == null ? '-' : Math.round(ward.current_aqi)}
                    </div>
                    <span className="city-card__cat" style={{ background: cat.color }}>{cat.label}</span>
                </div>
            </header>

            {live.length > 0 && (
                <section className="act-section">
                    <div className="act-section__hd">
                        <div className="section-label">Live Recommended Actions</div>
                        <span className="act-badge act-badge--live">{live.length} action{live.length > 1 ? 's' : ''}</span>
                    </div>
                    {live.map(c => <ActionCard key={c.card_id} card={c} />)}
                </section>
            )}

            {adv.length > 0 && (
                <section className="act-section">
                    <div className="section-label">For Information</div>
                    {adv.map(c => <ActionCard key={c.card_id} card={c} />)}
                </section>
            )}

            {live.length === 0 && adv.length === 0 && (
                <div className="act-ward-normal">
                    <div className="act-ward-normal__badge">Normal Municipal Baseline</div>
                    <h3 className="act-ward-normal__title">No Emergency Alerts Active</h3>
                    <p className="act-ward-normal__desc">
                        Ward {ward.ward_id} ({ward.ward_name}) has no critical open burning, stagnation, or acute traffic spike alerts. Routine preventive operations proceed under BMC standing orders.
                    </p>
                    <button type="button" className="act-btn-sop act-btn-sop--inline" onClick={onOpenModal}>
                        View Standard Operational Mitigations (SOP)
                    </button>
                </div>
            )}
        </div>
    );
}

export function ActionsView({
    data, loading, error, onRetry,
    selectedId, onSelect, signalFilter, onSignalFilter,
}) {
    const [modalOpen, setModalOpen] = useState(false);
    const wards = useMemo(() => data?.wards ?? [], [data]);
    const stats = useMemo(() => summarise(data), [data]);
    const chips = useMemo(() => signalsInUse(wards).filter(s => s !== 'inflow'), [wards]);
    const visible = useMemo(() => filterWards(wards, { signal: signalFilter }), [wards, signalFilter]);
    const selected = wards.find(w => w.ward_id === selectedId) ?? null;
    const modalCards = useMemo(() => {
        if (!selected) return [];
        return baselineCards(selected);
    }, [selected]);

    return (
        <div className="act-page">
            {error && (
                <div className="backend-banner act-banner" role="alert">
                    <span>{data ? 'Could not refresh ward actions: ' : 'Ward actions are unavailable: '}{error}</span>
                    <button type="button" className="act-banner__btn" onClick={onRetry}>Retry</button>
                </div>
            )}

            <div className="act-body">
                <aside className="panel act-list" aria-label="Wards ranked by exposure">
                    <div className="act-list__head">
                        <div className="act-list__head-top">
                            <div>
                                <h1 className="act-title">Ward Action Centre</h1>
                                <p className="act-sub">Ranked by population-weighted AQI exposure. Live emergency triggers with operational guidance.</p>
                            </div>
                            <button type="button" className="act-btn-sop-header" onClick={() => setModalOpen(true)} title="View BMC Standard Operational Protocols">
                                Standard SOPs
                            </button>
                        </div>

                        <div className="act-stats">
                            <Stat value={stats.total} label="Wards monitored" />
                            <Stat value={stats.needAction} label="Live alerts" accent />
                            <Stat value={stats.high} label="High priority" accent />
                        </div>

                        {chips.length > 0 && (
                            <div className="act-chips" role="group" aria-label="Filter by signal">
                                {['all', ...chips].map(id => (
                                    <button key={id} type="button"
                                        className={`act-filter${signalFilter === id ? ' act-filter--on' : ''}`}
                                        aria-pressed={signalFilter === id}
                                        onClick={() => onSignalFilter(id)}>
                                        {id === 'all' ? 'All' : signalLabel(id)}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    {loading && !data ? <ListSkeleton /> : (
                        <div className="act-list__rows">
                            {visible.length === 0 && <p className="station-list__empty">No wards match these filters.</p>}
                            {visible.map(w => (
                                <WardRow key={w.ward_id} ward={w} rank={rankOf(wards, w.ward_id)}
                                    selected={w.ward_id === selectedId} onSelect={onSelect} />
                            ))}
                        </div>
                    )}
                </aside>

                <main className="act-detail" aria-label="Ward detail">
                    {loading && !data && <DetailSkeleton />}
                    {!loading && !data && !error && <p className="act-empty__sub">No ward data yet.</p>}
                    {data && !selected && <p className="act-empty__sub">Choose a ward from the list.</p>}
                    {selected && (
                        <WardDetail
                            ward={selected}
                            rank={rankOf(wards, selected.ward_id)}
                            onOpenModal={() => setModalOpen(true)}
                        />
                    )}

                    {data && (
                        <p className="act-foot">
                            AQI shown is the model estimate at the ward centre. Measured readings are used where a live station lies inside the ward boundary.
                            {data.warnings?.length > 0 && <> {data.warnings.join(' ')}</>}
                        </p>
                    )}
                </main>
            </div>

            <StandardMitigationsModal
                isOpen={modalOpen}
                onClose={() => setModalOpen(false)}
                baselineCards={modalCards}
            />
        </div>
    );
}

export default function ActionsPage() {
    const { data, loading, error, reload } = useWardActions();
    const [pickedId, setPickedId] = useState(null);
    const [pickedFilter, setPickedFilter] = useState('all');

    const wards = useMemo(() => data?.wards ?? [], [data]);
    const selectedId = wards.some(w => w.ward_id === pickedId) ? pickedId : defaultWardId(wards);
    const validSignals = signalsInUse(wards).filter(s => s !== 'inflow');
    const signalFilter = pickedFilter !== 'all' && validSignals.includes(pickedFilter) ? pickedFilter : 'all';

    return (
        <ActionsView
            data={data} loading={loading} error={error} onRetry={reload}
            selectedId={selectedId} onSelect={setPickedId}
            signalFilter={signalFilter} onSignalFilter={setPickedFilter}
        />
    );
}
