import { ReactNode, createContext, useCallback, useMemo, useState } from "react";

type LoadingContextValue = {
  isLoading: boolean;
  startLoading: () => void;
  stopLoading: () => void;
  setLoading: (value: boolean) => void;
};

export const LoadingContext = createContext<LoadingContextValue | undefined>(
  undefined
);

type LoadingProviderProps = {
  children: ReactNode;
};

export function LoadingProvider({ children }: LoadingProviderProps) {
  const [loadingCount, setLoadingCount] = useState(0);

  const startLoading = useCallback(() => {
    setLoadingCount((prev) => prev + 1);
  }, []);

  const stopLoading = useCallback(() => {
    setLoadingCount((prev) => (prev > 0 ? prev - 1 : 0));
  }, []);

  const setLoading = useCallback((value: boolean) => {
    setLoadingCount(value ? 1 : 0);
  }, []);

  const value = useMemo(
    () => ({
      isLoading: loadingCount > 0,
      startLoading,
      stopLoading,
      setLoading,
    }),
    [loadingCount, setLoading, startLoading, stopLoading]
  );

  return (
    <LoadingContext.Provider value={value}>{children}</LoadingContext.Provider>
  );
}
