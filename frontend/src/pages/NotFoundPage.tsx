import { Link } from "react-router-dom";

import { PageContainer } from "../components/PageContainer";

export function NotFoundPage() {
  return (
    <PageContainer
      title="Page not found"
      description="The page you are looking for does not exist."
    >
      <Link to="/dashboard" className="inline-link">
        Go back to Dashboard
      </Link>
    </PageContainer>
  );
}
