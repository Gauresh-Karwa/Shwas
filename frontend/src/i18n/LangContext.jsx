/**
 * LangContext.jsx — React context for the active language.
 *
 * Usage:
 *   import { useLang, useT } from '../i18n/LangContext';
 *   const t = useT();          // returns t('key') → translated string
 *   const { lang, setLang } = useLang();  // 'en' | 'hi' | 'mr'
 *
 * Language is persisted in localStorage under 'shwas_lang'.
 */
import React, { createContext, useContext, useState, useCallback } from 'react';
import { makeT, DEFAULT_LANG } from './translations';

const LangCtx = createContext({ lang: DEFAULT_LANG, setLang: () => {}, t: makeT(DEFAULT_LANG) });

export function LangProvider({ children }) {
    const [lang, setLangState] = useState(() => {
        try { return localStorage.getItem('shwas_lang') ?? DEFAULT_LANG; } catch { return DEFAULT_LANG; }
    });

    const setLang = useCallback((code) => {
        setLangState(code);
        try { localStorage.setItem('shwas_lang', code); } catch { /* incognito */ }
    }, []);

    const t = makeT(lang);

    return <LangCtx.Provider value={{ lang, setLang, t }}>{children}</LangCtx.Provider>;
}

export const useLang = () => useContext(LangCtx);
export const useT    = () => useContext(LangCtx).t;
