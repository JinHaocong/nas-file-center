import React, { createContext, useContext, useEffect, useState } from 'react';

const thumbnailKey = 'nfc_show_media_thumbnails';

interface DisplayPreferences {
  showThumbnails: boolean;
  setShowThumbnails: (enabled: boolean) => void;
}

const DisplayPreferencesContext = createContext<DisplayPreferences>({
  showThumbnails: true,
  setShowThumbnails: () => {},
});

/** Unknown or absent values use the default. Storage may be restricted on shared NAS browsers. */
function restoreThumbnailPreference(): boolean {
  try {
    return window.localStorage.getItem(thumbnailKey) !== 'off';
  } catch {
    return true;
  }
}

/** Keep one display preference across routes, reloads and tabs on this browser. */
export function DisplayPreferencesProvider({ children }: { children: React.ReactNode }) {
  const [showThumbnails, setEnabled] = useState(restoreThumbnailPreference);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    function synchronize(event: StorageEvent) {
      if (event.key !== null && event.key !== thumbnailKey) return;
      try {
        if (event.storageArea === window.localStorage) setEnabled(restoreThumbnailPreference());
      } catch {
        // The current tab can still use its in-memory preference.
      }
    }
    window.addEventListener('storage', synchronize);
    return () => window.removeEventListener('storage', synchronize);
  }, []);

  function setShowThumbnails(enabled: boolean) {
    setEnabled(enabled);
    try {
      window.localStorage.setItem(thumbnailKey, enabled ? 'on' : 'off');
    } catch {
      // The live setting still applies when persistence is unavailable.
    }
  }

  return (
    <DisplayPreferencesContext.Provider value={{ showThumbnails, setShowThumbnails }}>
      {children}
    </DisplayPreferencesContext.Provider>
  );
}

/** Read the current browser's media display preference. */
export function useDisplayPreferences() {
  return useContext(DisplayPreferencesContext);
}
