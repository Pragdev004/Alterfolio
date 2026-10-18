import { useCallback, useState } from "react";

const KEY = "alterfolio.gShortcuts";

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "off";
  } catch {
    return true; // storage can be blocked; the default is on
  }
}

/** The `g`-shortcuts setting, remembered in this browser only. */
export function useGShortcutsSetting() {
  const [enabled, setEnabled] = useState(read);
  const update = useCallback((next: boolean) => {
    setEnabled(next);
    try {
      window.localStorage.setItem(KEY, next ? "on" : "off");
    } catch {
      /* the choice still applies for this visit */
    }
  }, []);
  return [enabled, update] as const;
}
