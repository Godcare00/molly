import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  buildTypeScale,
  type FontChoice,
  type TypeSizeChoice,
  type TypeWeightChoice,
  type TypeScale,
} from '@/theme';

const STORAGE_KEY = 'molly.typography_prefs';

interface TypographyPrefs {
  fontChoice: FontChoice;
  sizeChoice: TypeSizeChoice;
  weightChoice: TypeWeightChoice;
}

const DEFAULT_PREFS: TypographyPrefs = {
  fontChoice: 'inter',
  sizeChoice: 'medium',
  weightChoice: 'regular',
};

interface TypographyContextValue extends TypographyPrefs {
  type: TypeScale;
  ready: boolean;
  setFontChoice: (v: FontChoice) => void;
  setSizeChoice: (v: TypeSizeChoice) => void;
  setWeightChoice: (v: TypeWeightChoice) => void;
  resetToDefaults: () => void;
}

const TypographyContext = createContext<TypographyContextValue | undefined>(undefined);

export function TypographyProvider({ children }: { children: React.ReactNode }) {
  const [prefs, setPrefs] = useState<TypographyPrefs>(DEFAULT_PREFS);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => {
        if (raw) {
          const parsed = JSON.parse(raw);
          setPrefs({ ...DEFAULT_PREFS, ...parsed });
        }
      })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  const persist = useCallback((next: TypographyPrefs) => {
    setPrefs(next);
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next)).catch(() => {});
  }, []);

  const setFontChoice = useCallback((v: FontChoice) => persist({ ...prefs, fontChoice: v }), [prefs, persist]);
  const setSizeChoice = useCallback((v: TypeSizeChoice) => persist({ ...prefs, sizeChoice: v }), [prefs, persist]);
  const setWeightChoice = useCallback((v: TypeWeightChoice) => persist({ ...prefs, weightChoice: v }), [prefs, persist]);
  const resetToDefaults = useCallback(() => persist(DEFAULT_PREFS), [persist]);

  const typeScale = useMemo(
    () => buildTypeScale(prefs.fontChoice, prefs.sizeChoice, prefs.weightChoice),
    [prefs.fontChoice, prefs.sizeChoice, prefs.weightChoice]
  );

  const value = useMemo<TypographyContextValue>(
    () => ({ ...prefs, type: typeScale, ready, setFontChoice, setSizeChoice, setWeightChoice, resetToDefaults }),
    [prefs, typeScale, ready, setFontChoice, setSizeChoice, setWeightChoice, resetToDefaults]
  );

  return <TypographyContext.Provider value={value}>{children}</TypographyContext.Provider>;
}

/** Returns the live `type` scale plus setters, reflecting Settings > Text & Display. */
export function useTypography() {
  const ctx = useContext(TypographyContext);
  if (!ctx) throw new Error('useTypography must be used within a TypographyProvider');
  return ctx;
}
