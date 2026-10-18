import type { ReactNode } from "react";

export function StatusCode({ children, hold = false }: { children: ReactNode; hold?: boolean }) {
  return <span className={hold ? "code hold" : "code"}>{children}</span>;
}
