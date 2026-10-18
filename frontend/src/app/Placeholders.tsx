import { Link } from "react-router-dom";

import { EmptyState } from "../shared/ui/States";

export function NotFound() {
  return (
    <EmptyState title="There is nothing at this address.">
      <p><Link to="/trips">Go to Trips</Link>.</p>
    </EmptyState>
  );
}
