import { useState, useEffect, useCallback } from 'react';
import { fetchWardActions } from '../utils/api';

const REFRESH_MS = 5 * 60 * 1000;   // same cadence as the live readings (the backend caches for 5 min)

/**
 * Loads /api/actions for the Ward Actions page.
 *  - Refetches every 5 minutes AND whenever `lang` changes.
 *  - Keeps the last good data if a refresh fails, and reports the error alongside it.
 *  - `loading` is true only while there is neither data nor an error.
 */
export function useWardActions(lang = 'en') {
    const [result, setResult] = useState(null);     // last good response body
    const [failure, setFailure] = useState(null);   // last error message
    const [attempt, setAttempt] = useState(0);      // bumped by reload() to run the effect again

    useEffect(() => {
        // Reset stale data when language changes so UI doesn't show mismatched rationale
        setResult(null);
        setFailure(null);

        const ctrl = new AbortController();
        const run = () => fetchWardActions({ includeSignals: true, lang, signal: ctrl.signal })
            .then(body => {
                if (ctrl.signal.aborted) return;
                setResult(body);
                setFailure(null);
            })
            .catch(err => {
                if (ctrl.signal.aborted) return;
                setFailure(err?.message || 'Could not load ward actions.');
            });
        run();
        const id = setInterval(run, REFRESH_MS);
        return () => { clearInterval(id); ctrl.abort(); };
    }, [attempt, lang]);

    const data = result ?? null;
    const error = failure ?? null;
    const loading = data == null && error == null;

    const reload = useCallback(() => { setFailure(null); setAttempt(n => n + 1); }, []);
    return { data, loading, error, reload };
}