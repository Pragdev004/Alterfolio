import { Link } from "react-router-dom";

import { EmptyState } from "../shared/ui/States";

/** Screens designed but not built yet (Holdings, Costs, Ask, Upload). */
export function NotBuilt({ name }: { name: string }) {
  return (
    <>
      <h1 style={{ margin: "var(--s-6) 0 var(--s-3)" }}>{name}</h1>
      <EmptyState title="This screen is not built yet.">
        <p>It arrives in the next step. <Link to="/trips">Go to Trips</Link>.</p>
      </EmptyState>
    </>
  );
}

export function NotFound() {
  return (
    <EmptyState title="There is nothing at this address.">
      <p><Link to="/trips">Go to Trips</Link>.</p>
    </EmptyState>
  );
}
